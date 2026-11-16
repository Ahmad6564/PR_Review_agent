"""A deterministic, offline *simulated* reviewer.

This is a development convenience, not the product. It lets ``prlens --dry-run
--simulate`` and the evaluation harness run the whole pipeline with no token and no
network, by pattern-matching the hunk instead of calling a model:

  * It raises a finding on the first added line of any hunk whose text contains a
    ``BUG`` marker (the test/benchmark fixtures use this), and can be told to emit a
    tunable amount of low-value "noise" to exercise the precision filter.
  * As a critic it rejects noise (low confidence or opt-in categories) and keeps the
    rest — a crude but useful stand-in for the real adversarial pass.

Point PRLens at GitHub Models for real reviews; use this only to see the machinery move.
"""

from __future__ import annotations

import json

from .client import MockProvider, Usage


def _tool_call(findings: list[dict], summary: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "sim",
                            "type": "function",
                            "function": {
                                "name": "submit_review",
                                "arguments": json.dumps(
                                    {"findings": findings, "summary": summary}
                                ),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10},
    }


def _content(text: str) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 6, "completion_tokens": 3},
    }


_NOISE = [
    {
        "category": "maintainability",
        "severity": "minor",
        "confidence": 0.45,
        "title": "Consider extracting a helper",
        "body": "This block could be factored into a helper for readability.",
        "evidence": "",
    },
    {
        "category": "style",
        "severity": "minor",
        "confidence": 0.5,
        "title": "Add a docstring",
        "body": "This function would benefit from a docstring.",
        "evidence": "",
    },
]


def _parse_hunk(messages) -> tuple[str | None, int | None, bool]:
    """Pull (path, first_added_line, has_bug_marker) out of the user message."""
    user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    text = (user or {}).get("content", "") or ""
    path = None
    for line in text.splitlines():
        if line.startswith("File: "):
            path = line[len("File: ") :].strip()
            break
    first_added = None
    for line in text.splitlines():
        if "Added (commentable) line numbers:" in line:
            nums = line.split(":", 1)[1].strip()
            for tok in nums.replace(",", " ").split():
                if tok.isdigit():
                    first_added = int(tok)
                    break
            break
    has_bug = "BUG" in text
    return path, first_added, has_bug


def simulated_provider(noise_per_hunk: int = 1, prefer_silence_effective: bool = True) -> MockProvider:
    def responder(messages, tools):
        # Critic path.
        if any(
            m.get("role") == "system" and "determine whether it" in (m.get("content") or "")
            for m in messages
        ):
            user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            body = (user or {}).get("content", "")
            # Reject anything that looks like style/maintainability noise.
            reject = any(k in body for k in ("Consider extracting", "docstring", "maintainability", "style"))
            verdict = "reject" if reject else "keep"
            return _content(json.dumps({"verdict": verdict, "reason": "simulated"}))

        # Cross-file path: stay silent.
        if any(
            m.get("role") == "system" and "cross-cutting pass" in (m.get("content") or "")
            for m in messages
        ):
            return _tool_call([], "")

        path, first_added, has_bug = _parse_hunk(messages)
        user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        hunk_text = (user or {}).get("content", "") or ""
        findings: list[dict] = []
        if has_bug and path and first_added is not None:
            # A "subtle" bug is reported with lower confidence, so the confidence
            # threshold drops it — this is what lets the ablation show a recall cost.
            subtle = "SUBTLE" in hunk_text
            findings.append(
                {
                    "path": path,
                    "line": first_added,
                    "category": "bug",
                    "severity": "major" if not subtle else "minor",
                    "confidence": 0.62 if subtle else 0.88,
                    "title": "Likely defect introduced here",
                    "body": "This added code appears to contain a logic error; verify the loop/index handling.",
                    "evidence": "marked with a BUG comment in the diff",
                }
            )
        # Inject noise to exercise the filter (reduced when 'prefer silence' is on).
        n = noise_per_hunk if not prefer_silence_effective else max(0, noise_per_hunk - 1)
        if path and first_added is not None:
            for noise in _NOISE[:n]:
                findings.append({**noise, "path": path, "line": first_added})
        return _tool_call(findings, "simulated review")

    prov = MockProvider(responder)
    prov.usage = Usage()
    return prov
