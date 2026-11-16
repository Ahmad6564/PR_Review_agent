"""The precision filter pipeline: runs all five stages and logs every rejection.

Order matters. Cheap, deterministic stages (category, confidence) run before the
expensive critic so we spend LLM calls only on findings that already passed the free
gates. Dedupe runs after, and the hard cap last.

Every dropped finding is recorded in ``trace`` with the stage and reason. Rejection
logs are excellent README material and show the filter working.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent.schema import Finding
from ..config import Config
from . import categories, confidence, dedupe
from . import critic as critic_mod


@dataclass
class Rejection:
    stage: str
    finding: Finding
    reason: str


@dataclass
class FilterResult:
    kept: list[Finding]
    rejections: list[Rejection] = field(default_factory=list)
    suppressed_by_cap: int = 0

    def to_log(self) -> list[dict]:
        return [
            {
                "stage": r.stage,
                "path": r.finding.path,
                "line": r.finding.line,
                "category": r.finding.category,
                "title": r.finding.title,
                "reason": r.reason,
            }
            for r in self.rejections
        ]


def apply_cap(findings: list[Finding], max_comments: int) -> tuple[list[Finding], int]:
    ordered = sorted(findings, key=lambda f: f.rank_score(), reverse=True)
    kept = ordered[:max_comments]
    return kept, max(0, len(ordered) - len(kept))


def run_filter(
    findings: list[Finding],
    cfg: Config,
    client=None,
    hunk_text_for=lambda f: "",
    existing_comments: list[dict] | None = None,
) -> FilterResult:
    rejections: list[Rejection] = []
    work = list(findings)

    # Stage 1 — category allowlist
    if cfg.use_category_allowlist:
        work, dropped = categories.filter_categories(work, cfg.categories)
        rejections += [Rejection("category", f, r) for f, r in dropped]

    # Stage 2 — confidence threshold
    if cfg.use_confidence_threshold:
        work, dropped = confidence.filter_confidence(work, cfg.min_confidence)
        rejections += [Rejection("confidence", f, r) for f, r in dropped]

    # Stage 3 — critic pass (needs a client; skipped cleanly if unavailable)
    if cfg.use_critic and client is not None and work:
        work, dropped = critic_mod.filter_critic(client, work, hunk_text_for)
        rejections += [Rejection("critic", f, r) for f, r in dropped]

    # Stage 4 — dedupe (collapse repeats, then drop already-posted)
    if cfg.use_dedupe:
        work, dropped = dedupe.collapse_repeats(work)
        rejections += [Rejection("dedupe-collapse", f, r) for f, r in dropped]
        if existing_comments:
            work, dropped = dedupe.drop_already_posted(work, existing_comments)
            rejections += [Rejection("dedupe-posted", f, r) for f, r in dropped]

    # Stage 5 — the hard cap
    suppressed = 0
    if cfg.use_cap:
        work, suppressed = apply_cap(work, cfg.max_comments)

    return FilterResult(kept=work, rejections=rejections, suppressed_by_cap=suppressed)
