"""Shared test helpers: a scriptable, fully-offline mock LLM.

The mock speaks the same OpenAI-shaped protocol the real client returns, so the
entire engine (agent loop, critic, filter) runs in tests with no network and no token.
"""

from __future__ import annotations

import json

from prlens.llm.client import MockProvider


def tool_call_response(name: str, args: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def content_response(text: str) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4},
    }


def is_critic(messages) -> bool:
    return any(
        m.get("role") == "system" and "determine whether it" in (m.get("content") or "")
        for m in messages
    )


def is_crossfile(messages) -> bool:
    return any(
        m.get("role") == "system" and "cross-cutting pass" in (m.get("content") or "")
        for m in messages
    )


def make_mock_client(review_findings=None, review_summary="", critic_keep=True, crossfile_findings=None):
    """Build a MockProvider.

    review_findings: list[dict] the reviewer returns for every hunk (submit_review).
    critic_keep: whether the critic keeps each finding.
    """
    review_findings = review_findings or []
    crossfile_findings = crossfile_findings or []

    def responder(messages, tools):
        if is_critic(messages):
            verdict = "keep" if critic_keep else "reject"
            return content_response(json.dumps({"verdict": verdict, "reason": "test"}))
        if is_crossfile(messages):
            return tool_call_response(
                "submit_review", {"findings": crossfile_findings, "summary": "xfile"}
            )
        return tool_call_response(
            "submit_review", {"findings": review_findings, "summary": review_summary}
        )

    return MockProvider(responder)
