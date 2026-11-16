"""Phase 7 — derive a usefulness label for each human review comment.

Key insight: a human review comment is not necessarily a *good* comment. But a review
comment followed by a change to the exact lines it referenced, in a later commit on
the same PR, is strong evidence the comment identified something real. That gives an
automatically-derived label for usefulness.

It is imperfect — the author may have changed that region for an unrelated reason, and
some good comments are answered in discussion rather than code. Quantify the error by
hand-labelling a sample and reporting the agreement rate (see verify_agreement).
"""

from __future__ import annotations

import re
from datetime import datetime

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def touches_region(patch: str | None, target_line: int, window: int = 5) -> bool:
    """Does a file's patch modify lines within +/- window of target_line (new-file)?"""
    if not patch or target_line is None:
        return False
    new_line = 0
    for raw in patch.splitlines():
        m = HUNK_HEADER.match(raw)
        if m:
            new_line = int(m.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if abs(new_line - target_line) <= window:
                return True
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue  # removed line: new-file pointer does not advance
        else:
            new_line += 1
    return False


def is_actionable(comment: dict, commits: list[dict], files_by_commit) -> bool:
    """Did the author change the referenced region after this comment was posted?

    commits: [{"sha", "date"}], newest or any order.
    files_by_commit: callable sha -> [file dicts with 'filename','patch'].
    """
    c_time = _parse_dt(comment.get("created_at"))
    if c_time is None:
        return False
    later = [c for c in commits if (_parse_dt(c.get("date")) or c_time) > c_time]
    for commit in later:
        for f in files_by_commit(commit["sha"]):
            if f.get("filename") != comment.get("path"):
                continue
            if touches_region(f.get("patch"), comment.get("line"), window=5):
                return True
    return False


def label_record(record: dict, files_by_commit=None) -> dict:
    """Attach an 'actionable' flag to each review comment of a mined PR record.

    Without live API access (``files_by_commit=None``) this cannot inspect per-commit
    diffs, so it marks comments as ``actionable=None`` (unknown) — the heuristic needs
    commit-level patches, which collect_prs can hydrate.
    """
    out = dict(record)
    labelled = []
    for c in record.get("review_comments", []):
        if files_by_commit is None:
            actionable = None
        else:
            actionable = is_actionable(c, record.get("commits", []), files_by_commit)
        labelled.append({**c, "actionable": actionable})
    out["review_comments"] = labelled
    return out


def verify_agreement(heuristic_labels: list[bool], human_labels: list[bool]) -> dict:
    """Agreement rate between the heuristic and hand labels (Phase 7 methodology).

    Report this single number to turn the hack into a methodology.
    """
    assert len(heuristic_labels) == len(human_labels)
    n = len(human_labels)
    if n == 0:
        return {"n": 0, "agreement": None}
    pairs = list(zip(heuristic_labels, human_labels, strict=False))
    agree = sum(1 for a, b in pairs if a == b)
    tp = sum(1 for a, b in pairs if a and b)
    fp = sum(1 for a, b in pairs if a and not b)
    fn = sum(1 for a, b in pairs if not a and b)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "n": n,
        "agreement": agree / n,
        "heuristic_precision": precision,
        "heuristic_recall": recall,
    }
