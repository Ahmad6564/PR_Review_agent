"""Stage 4 — deduplication.

Two kinds:
  * drop_already_posted — when a PR gets new commits, don't repeat comments already
    made. A PR typically gets 3-8 pushes; without this the bot re-posts every time and
    becomes actively hated.
  * collapse_repeats — the same issue on 12 lines becomes one comment that says it
    occurs 12 times.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..agent.schema import Finding

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    # Strip the PRLens footer and collapse whitespace so re-renders compare equal.
    text = re.split(r"<sub>.*?PRLens</sub>", text, flags=re.DOTALL)[0]
    text = text.replace("**", "").strip().lower()
    return _WS.sub(" ", text)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def drop_already_posted(
    findings: list[Finding],
    existing_comments: list[dict],
    threshold: float = 0.85,
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    seen = {(c.get("path"), c.get("line"), normalize(c.get("body", ""))) for c in existing_comments}
    kept, dropped = [], []
    for f in findings:
        exact = (f.path, f.line, normalize(f.body)) in seen
        fuzzy = any(
            c.get("path") == f.path
            and abs((c.get("line") or -999) - f.line) <= 2
            and similar(f.body, c.get("body", "")) > threshold
            for c in existing_comments
        )
        if exact or fuzzy:
            dropped.append((f, "already posted on an earlier commit"))
        else:
            kept.append(f)
    return kept, dropped


def collapse_repeats(findings: list[Finding], similarity: float = 0.9) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    """Collapse near-identical findings (same path, same message) into one."""
    kept: list[Finding] = []
    canonical: dict[int, str] = {}  # id(representative) -> original body used for matching
    dropped: list[tuple[Finding, str]] = []
    for f in findings:
        match = None
        for k in kept:
            if (
                k.path == f.path
                and k.category == f.category
                and similar(canonical[id(k)], f.body) > similarity
            ):
                match = k
                break
        if match is None:
            kept.append(f)
            canonical[id(f)] = f.body
        else:
            # Annotate the representative (but match against its original body above).
            count = getattr(match, "_repeat_count", 1) + 1
            object.__setattr__(match, "_repeat_count", count)
            if "occurs" not in match.body:
                match.body = f"{match.body} (this pattern occurs on multiple lines)"
            dropped.append((f, f"collapsed into {match.path}:{match.line}"))
    return kept, dropped
