"""Stage 1 — category allowlist.

Default to bug / security / correctness / performance. maintainability, style and
test are opt-in via .prlens.yml. Style comments from a bot are pure noise: linters do
it better and without opinions.
"""

from __future__ import annotations

from ..agent.schema import Finding


def filter_categories(findings: list[Finding], allowed: list[str]) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    allowed_set = {c.strip().lower() for c in allowed}
    kept, dropped = [], []
    for f in findings:
        if f.category in allowed_set:
            kept.append(f)
        else:
            dropped.append((f, f"category '{f.category}' not in allowlist"))
    return kept, dropped
