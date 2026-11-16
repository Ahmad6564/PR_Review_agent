"""Phase 8 — precision metrics (the headline).

Reports, for the full pipeline:
  * False positives per clean PR (flagship number) — target < 0.5
  * Silence rate on clean PRs — should be high
  * Useful % on PRs with real issues
  * Correlation between self-reported confidence and whether a comment was useful
    (Phase 4.2 — shows the confidence signal is informative)
"""

from __future__ import annotations

import argparse
import json

from prlens.config import Config

from . import metrics
from .harness import load_benchmark, run_all


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Precision evaluation")
    ap.add_argument("--benchmark", default="evaluation/benchmark/prs.jsonl")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args(argv)

    cases = load_benchmark(args.benchmark)
    cfg = Config()  # full pipeline (all stages on by default)
    grouped = run_all(cases, cfg, simulate=not args.real, repo_root=args.repo_root)
    mixed = grouped["injected"] + grouped["real"]

    posted_with_match = [
        (c.confidence, metrics._matches_gold(c, gold))
        for comments, gold in mixed
        for c in comments
    ]

    report = {
        "mode": "live" if args.real else "simulated",
        "n_clean": len(grouped["clean"]),
        "fp_per_clean_pr": round(metrics.false_positives_per_clean_pr(grouped["clean"]), 3),
        "silence_rate": round(metrics.silence_rate(grouped["clean"]), 3),
        "useful_pct": round(metrics.useful_fraction(mixed) * 100, 1),
        "confidence_correlation": metrics.confidence_precision_correlation(posted_with_match),
    }
    print(json.dumps(report, indent=2))
    flag = "PASS" if report["fp_per_clean_pr"] < 0.5 else "REVIEW"
    print(f"\nFlagship FP/clean PR = {report['fp_per_clean_pr']:.2f}  [{flag}] (target < 0.5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
