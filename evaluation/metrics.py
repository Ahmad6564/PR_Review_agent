"""Shared evaluation metrics.

Precision is the headline. The flagship number is false positives per clean PR: a
clean PR (merged with approval, no changes requested) should receive at or near zero
comments. Recall is measured as detection on injected bugs and agreement with actioned
human comments, both within a small line tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass

LINE_TOLERANCE = 3


@dataclass
class PostedComment:
    path: str
    line: int
    category: str
    confidence: float


def _matches_gold(comment: PostedComment, gold: list[dict], tol: int = LINE_TOLERANCE) -> bool:
    for g in gold:
        if g.get("path") == comment.path and abs((g.get("line") or -999) - comment.line) <= tol:
            return True
    return False


def false_positives_per_clean_pr(clean_results: list[list[PostedComment]]) -> float:
    if not clean_results:
        return 0.0
    total = sum(len(r) for r in clean_results)
    return total / len(clean_results)


def silence_rate(clean_results: list[list[PostedComment]]) -> float:
    if not clean_results:
        return 1.0
    silent = sum(1 for r in clean_results if len(r) == 0)
    return silent / len(clean_results)


def bug_detection_rate(injected: list[tuple[list[PostedComment], list[dict]]]) -> float:
    """Fraction of injected-bug PRs where some posted comment matches a gold line."""
    if not injected:
        return 0.0
    detected = 0
    for comments, gold in injected:
        if any(_matches_gold(c, gold) for c in comments):
            detected += 1
    return detected / len(injected)


def detection_by_type(injected: list[tuple[list[PostedComment], list[dict]]]) -> dict[str, float]:
    by_type_total: dict[str, int] = {}
    by_type_hit: dict[str, int] = {}
    for comments, gold in injected:
        btype = (gold[0].get("bug_type") if gold else None) or "unknown"
        by_type_total[btype] = by_type_total.get(btype, 0) + 1
        if any(_matches_gold(c, gold) for c in comments):
            by_type_hit[btype] = by_type_hit.get(btype, 0) + 1
    return {
        t: by_type_hit.get(t, 0) / by_type_total[t] for t in by_type_total
    }


def human_agreement_rate(real: list[tuple[list[PostedComment], list[dict]]]) -> float:
    """Fraction of real_bug PRs where a posted comment lands within tolerance of gold."""
    if not real:
        return 0.0
    agree = 0
    for comments, gold in real:
        if any(_matches_gold(c, gold) for c in comments):
            agree += 1
    return agree / len(real)


def useful_fraction(mixed: list[tuple[list[PostedComment], list[dict]]]) -> float:
    """Among all posted comments on PRs that DO have gold, the fraction that match gold.

    A proxy for precision on PRs that contain real issues (full 'useful/harmless/noise'
    judgment is done by hand against evaluation/rubric.md).
    """
    total = 0
    useful = 0
    for comments, gold in mixed:
        for c in comments:
            total += 1
            if _matches_gold(c, gold):
                useful += 1
    return (useful / total) if total else 1.0


def confidence_precision_correlation(
    posted_with_match: list[tuple[float, bool]],
) -> float | None:
    """Pearson correlation between a comment's confidence and whether it matched gold.

    Reported in Phase 4.2 to show self-reported confidence is informative.
    """
    n = len(posted_with_match)
    if n < 2:
        return None
    xs = [c for c, _ in posted_with_match]
    ys = [1.0 if m else 0.0 for _, m in posted_with_match]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx**0.5 * vy**0.5)
