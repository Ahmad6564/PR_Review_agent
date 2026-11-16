"""OpenAI-compatible LLM client with failover and caching.

GitHub Models is the default provider: it is free for developers, OpenAI-compatible,
and callable from inside an Action using the built-in ``GITHUB_TOKEN`` with a
``models: read`` permission — so installers need no API key of their own.

Design for degradation (Phase 0 / Phase 10):
  * If the primary model is unavailable or rate-limited, fall through a chain of
    fallback endpoints (Groq / Gemini / Cerebras / OpenRouter free tiers, or a
    user-supplied key).
  * A ``MockProvider`` lets the whole pipeline run fully offline against fixtures,
    which is how ``--dry-run`` and the test suite work without burning quota.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from ..cache import DiskCache


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Raised when every provider in the chain has failed — handled gracefully upstream."""


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    # Some providers nest the model under a path; keep it OpenAI-compatible by default.
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, resp: dict) -> None:
        self.calls += 1
        u = (resp or {}).get("usage") or {}
        self.prompt_tokens += int(u.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(u.get("completion_tokens", 0) or 0)


class LLMClient:
    """Chat-completions client with tool-calling, a failover chain and caching."""

    def __init__(
        self,
        providers: list[Provider],
        cache: DiskCache | None = None,
        timeout: int = 60,
        max_retries: int = 2,
        session: requests.Session | None = None,
    ):
        if not providers:
            raise ValueError("LLMClient requires at least one provider")
        self.providers = providers
        self.cache = cache or DiskCache(enabled=False)
        self.timeout = timeout
        self.max_retries = max_retries
        self.usage = Usage()
        self.s = session or requests.Session()

    # ------------------------------------------------------------------ public
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        response_format: dict | None = None,
        cache_salt: str = "",
    ) -> dict:
        """Return a single chat-completion response dict (OpenAI shape).

        Tries each provider in order; on the last provider's failure raises
        ``LLMUnavailable`` so the caller can exit cleanly rather than crash the check.
        """
        cache_payload = {
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "response_format": response_format,
            "model": self.providers[0].model,
            "salt": cache_salt,
        }
        ckey = DiskCache.key(cache_payload)
        if (hit := self.cache.get(ckey)) is not None:
            return hit

        last_err: Exception | None = None
        for provider in self.providers:
            try:
                resp = self._call_provider(
                    provider, messages, tools, temperature, response_format
                )
                self.usage.add(resp)
                self.cache.set(ckey, resp)
                return resp
            except LLMError as e:
                last_err = e
                continue
        raise LLMUnavailable(f"All providers failed; last error: {last_err}")

    # --------------------------------------------------------------- internals
    def _call_provider(
        self,
        provider: Provider,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        response_format: dict | None,
    ) -> dict:
        url = provider.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if response_format:
            body["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            **provider.extra_headers,
        }

        for attempt in range(self.max_retries + 1):
            try:
                r = self.s.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt >= self.max_retries:
                    raise LLMError(f"{provider.name}: network error: {e}") from e
                time.sleep(1.5 * (attempt + 1))
                continue

            if r.status_code == 429 or (r.status_code == 403 and "rate" in r.text.lower()):
                reset = r.headers.get("x-ratelimit-reset") or r.headers.get("retry-after")
                wait = _retry_wait(reset)
                if attempt >= self.max_retries:
                    raise LLMError(f"{provider.name}: rate limited")
                time.sleep(wait)
                continue

            if r.status_code >= 500:
                if attempt >= self.max_retries:
                    raise LLMError(f"{provider.name}: server error {r.status_code}")
                time.sleep(1.5 * (attempt + 1))
                continue

            if r.status_code >= 400:
                raise LLMError(f"{provider.name}: {r.status_code} {r.text[:200]}")

            try:
                return r.json()
            except json.JSONDecodeError as e:
                raise LLMError(f"{provider.name}: bad JSON response") from e

        raise LLMError(f"{provider.name}: exhausted retries")


def _retry_wait(reset_header: str | None) -> float:
    if not reset_header:
        return 2.0
    try:
        val = float(reset_header)
    except (TypeError, ValueError):
        return 2.0
    # Could be a unix timestamp or a seconds delta; clamp to something sane.
    delta = val - time.time() if val > 1e6 else val
    return max(0.5, min(delta + 1, 30.0))


# --------------------------------------------------------------------- mock
class MockProvider:
    """A deterministic, offline stand-in for an LLM.

    Drives the pipeline from a scripted ``responder`` so tests and ``--dry-run``
    work without any network or token. The responder receives the message list and
    returns an OpenAI-shaped response dict.
    """

    def __init__(self, responder: Callable[[list[dict], list[dict] | None], dict]):
        self.responder = responder
        self.usage = Usage()
        self.cache = DiskCache(enabled=False)

    def chat(self, messages, tools=None, temperature=0.0, response_format=None, cache_salt=""):
        resp = self.responder(messages, tools)
        self.usage.add(resp)
        return resp


def build_client(cfg, cache: DiskCache | None = None) -> LLMClient:
    """Construct an ``LLMClient`` from config + environment.

    Primary: GitHub Models via ``GITHUB_TOKEN`` (the token the Action already has).
    Fallbacks: any ``PRLENS_FALLBACK_*`` env providers the user configured.
    """
    providers: list[Provider] = []

    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("INPUT_GITHUB_TOKEN")
    if gh_token:
        providers.append(
            Provider(
                name="github-models",
                base_url=cfg.base_url,
                api_key=gh_token,
                model=cfg.model,
            )
        )

    # Optional explicit fallback (e.g. a user-supplied OpenAI-compatible key).
    fb_key = os.environ.get("PRLENS_FALLBACK_API_KEY")
    fb_url = os.environ.get("PRLENS_FALLBACK_BASE_URL")
    fb_model = os.environ.get("PRLENS_FALLBACK_MODEL")
    if fb_key and fb_url and fb_model:
        providers.append(
            Provider(name="fallback", base_url=fb_url, api_key=fb_key, model=fb_model)
        )

    # Local Ollama for offline development (no key required).
    if os.environ.get("PRLENS_OLLAMA"):
        providers.append(
            Provider(
                name="ollama",
                base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                api_key="ollama",
                model=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            )
        )

    if not providers:
        raise LLMUnavailable(
            "No LLM provider configured. Set GITHUB_TOKEN (with models: read) or a "
            "PRLENS_FALLBACK_* provider, or run with --dry-run against fixtures."
        )

    return LLMClient(providers, cache=cache)
