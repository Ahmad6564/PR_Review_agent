"""The review engine: orchestrates prefilter → parse → agent → filter → summary.

Used by both entrypoints:
  * ``prlens.cli`` runs it against a saved fixture, offline, with ``--dry-run``.
  * ``prlens.action`` runs it inside a GitHub Action against the live PR.

Keeping the orchestration here (not in either entrypoint) is what lets the whole
pipeline be exercised by the test suite with a ``MockProvider``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent.reviewer import cross_file_review, review_hunk
from .agent.schema import Finding
from .config import Config
from .context.prefilter import select_files
from .context.tools import ToolBox
from .filter.pipeline import FilterResult, run_filter
from .github.diff import parse_pr_files


@dataclass
class PRData:
    owner: str
    repo: str
    number: int
    title: str
    body: str
    head_sha: str
    files: list[dict]
    existing_comments: list[dict] = field(default_factory=list)

    @classmethod
    def from_fixture(cls, data: dict) -> PRData:
        return cls(
            owner=data.get("owner", "owner"),
            repo=data.get("repo", "repo"),
            number=int(data.get("number", 0)),
            title=data.get("title", ""),
            body=data.get("body", ""),
            head_sha=data.get("head_sha", "HEAD"),
            files=data.get("files", []),
            existing_comments=data.get("existing_comments", []),
        )


@dataclass
class ReviewResult:
    findings: list[Finding]
    summary: str
    filter_result: FilterResult
    skipped: list[tuple[str, str]]
    cross_file: list[Finding] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    @property
    def would_post(self) -> bool:
        return bool(self.findings)


def _build_summary(result_findings, skipped, suppressed, cross_file, cross_summary) -> str:
    lines: list[str] = []
    if result_findings:
        lines.append(
            f"**PRLens** reviewed this PR and left {len(result_findings)} "
            f"inline comment{'s' if len(result_findings) != 1 else ''}."
        )
    else:
        lines.append("**PRLens** reviewed this PR and found nothing worth flagging. ✅")

    if cross_file:
        lines.append("")
        lines.append("**Cross-cutting notes:**")
        for f in cross_file:
            loc = f" (`{f.path}`)" if f.path else ""
            lines.append(f"- {f.title}{loc}: {f.body}")
    elif cross_summary:
        pass  # a clean cross-file pass needs no note

    if suppressed:
        lines.append("")
        lines.append(
            f"_{suppressed} lower-ranked finding(s) suppressed by the comment cap; "
            f"lower `min-confidence` or raise `max-comments` to see them._"
        )

    if skipped:
        lines.append("")
        lines.append("<details><summary>Files not reviewed</summary>")
        lines.append("")
        for name, reason in skipped[:40]:
            lines.append(f"- `{name}` — {reason}")
        lines.append("")
        lines.append("</details>")

    lines.append("")
    lines.append("<sub>🔎 PRLens · comments only, never blocks your merge · tune with `.prlens.yml`</sub>")
    return "\n".join(lines)


def review_pr(
    pr: PRData,
    cfg: Config,
    client,
    repo_root: str = ".",
) -> ReviewResult:
    """Run the full review pipeline and return the result (without posting)."""
    # Phase 1 — pre-filter files.
    to_review, skipped = select_files(pr.files, cfg.exclude)

    # Phase 1 — parse diffs into hunks.
    hunks_by_file = parse_pr_files(to_review)

    # Phase 2 — tools bound to the checked-out tree.
    pr_context = {
        "title": pr.title,
        "body": pr.body,
        "files": [f["filename"] for f in pr.files],
    }
    toolbox = ToolBox(repo_root, pr_context)

    # Phase 3 — per-hunk review.
    raw_findings: list[Finding] = []
    hunk_text_by_key: dict[tuple[str, int], str] = {}
    for _path, hunks in hunks_by_file.items():
        for hunk in hunks:
            out = review_hunk(
                client,
                hunk,
                pr.title,
                pr.body,
                toolbox,
                categories=cfg.categories if cfg.use_category_allowlist else _ALL_CATEGORIES,
                min_confidence=cfg.min_confidence,
                instructions=cfg.instructions,
                use_context_tools=cfg.use_context_tools,
                max_tool_calls=cfg.max_tool_calls_per_hunk,
                use_prefer_silence=cfg.use_prefer_silence,
            )
            for f in out.findings:
                raw_findings.append(f)
                hunk_text_by_key[f.key()] = hunk.content

    # Phase 4 — the precision filter.
    def hunk_text_for(f: Finding) -> str:
        return hunk_text_by_key.get(f.key(), "")

    filt = run_filter(
        raw_findings,
        cfg,
        client=client if cfg.use_critic else None,
        hunk_text_for=hunk_text_for,
        existing_comments=pr.existing_comments,
    )

    # Optional cheap cross-file pass (reported in the summary, not inline).
    cross = []
    cross_summary = ""
    if cfg.cross_file_pass and hunks_by_file:
        cf = cross_file_review(
            client, hunks_by_file, pr.title, pr.body, cfg.categories, cfg.min_confidence
        )
        cross = [f for f in cf.findings if f.confidence >= cfg.min_confidence]
        cross_summary = cf.summary

    summary = _build_summary(
        filt.kept, skipped, filt.suppressed_by_cap, cross, cross_summary
    )
    usage = getattr(getattr(client, "usage", None), "__dict__", {}) or {}

    return ReviewResult(
        findings=filt.kept,
        summary=summary,
        filter_result=filt,
        skipped=skipped,
        cross_file=cross,
        usage=dict(usage),
    )


_ALL_CATEGORIES = [
    "bug",
    "security",
    "correctness",
    "performance",
    "maintainability",
    "style",
    "test",
]
