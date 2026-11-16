"""Command-line entrypoint for local development.

The ``--dry-run`` flag — print what it *would* post instead of posting — saves more
time than anything else in the build. Combined with ``--fixture`` it runs the whole
agent against a saved PR payload offline, with no GitHub token and no LLM quota.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cache import DiskCache
from .config import build_config
from .engine import PRData, review_pr
from .github.review import render_body


def _load_fixture(path: str) -> PRData:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PRData.from_fixture(data)


def _make_client(cfg, offline_responder=None):
    if offline_responder is not None:
        from .llm.client import MockProvider

        return MockProvider(offline_responder)
    from .llm.client import build_client

    return build_client(cfg, cache=DiskCache(enabled=True))


def _print_result(result, pr: PRData) -> None:
    print(f"\n=== PRLens dry run: {pr.owner}/{pr.repo}#{pr.number} ===\n")
    print(result.summary)
    print(f"\n--- {len(result.findings)} inline comment(s) ---\n")
    for f in result.findings:
        print(f"{f.path}:{f.line}  [{f.category}/{f.severity}  conf={f.confidence:.2f}]")
        print(render_body(f))
        print()
    if result.filter_result.rejections:
        print(f"--- {len(result.filter_result.rejections)} finding(s) rejected by the filter ---")
        for r in result.filter_result.rejections:
            print(f"  [{r.stage}] {r.finding.path}:{r.finding.line} — {r.reason}")
    if result.skipped:
        print(f"\n--- {len(result.skipped)} file(s) skipped ---")
        for name, reason in result.skipped:
            print(f"  {name}: {reason}")


def main(argv: list[str] | None = None) -> int:
    # Make output robust to a non-UTF-8 console (e.g. Windows cp1252) so emoji in
    # the summary never crash a dry run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(prog="prlens", description="PRLens local runner")
    ap.add_argument("--fixture", help="Path to a saved PR payload JSON")
    ap.add_argument("--repo-root", default=".", help="Checked-out repo root for tools")
    ap.add_argument("--dry-run", action="store_true", help="Print instead of posting")
    ap.add_argument("--max-comments", type=int)
    ap.add_argument("--min-confidence", type=float)
    ap.add_argument("--model")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument(
        "--simulate",
        action="store_true",
        help="Use the offline simulated reviewer (no token/network; demo only)",
    )
    ap.add_argument("--json", action="store_true", help="Emit the result as JSON")
    args = ap.parse_args(argv)

    overrides = {
        "max_comments": args.max_comments,
        "min_confidence": args.min_confidence,
        "model": args.model,
        "dry_run": True if args.dry_run else None,
    }
    cfg = build_config(cli_overrides=overrides)

    if not args.fixture:
        print("error: --fixture is required for the CLI runner", file=sys.stderr)
        return 2

    pr = _load_fixture(args.fixture)

    if args.simulate:
        from .llm.simulate import simulated_provider

        client = simulated_provider(
            noise_per_hunk=2, prefer_silence_effective=cfg.use_prefer_silence
        )
    else:
        try:
            client = _make_client(cfg)
        except Exception as e:  # noqa: BLE001 - surface a friendly message
            print(f"error: could not create LLM client: {e}", file=sys.stderr)
            print("hint: run with --simulate to see the pipeline offline.", file=sys.stderr)
            return 1

    result = review_pr(pr, cfg, client, repo_root=args.repo_root)

    if args.json:
        print(
            json.dumps(
                {
                    "findings": [f.model_dump() for f in result.findings],
                    "summary": result.summary,
                    "skipped": result.skipped,
                    "rejections": result.filter_result.to_log(),
                },
                indent=2,
            )
        )
    else:
        _print_result(result, pr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
