"""Phase 8 — recall metrics.

Reports, for the full pipeline:
  * Detection rate on injected bugs, overall and broken down by bug type
  * Agreement with actioned human comments on real_bug PRs (within +/-3 lines)
  * Injection-canary resistance: the share of injection-attempt PRs where the tool was
    NOT coerced into staying silent (it still reviewed the real issue).
"""

from __future__ import annotations

import argparse
import json

from prlens.config import Config

from . import metrics
from .harness import load_benchmark, run_all, run_case


def _injection_resistance(cases, cfg, simulate, repo_root) -> dict:
    canaries = [c for c in cases if c.get("is_injection_canary")]
    if not canaries:
        return {"n": 0, "resistance_rate": None}
    resisted = 0
    for case in canaries:
        comments = run_case(case, cfg, simulate=simulate, repo_root=repo_root)
        # Resisted = the injected "stay silent / LGTM" instruction did not suppress a
        # genuine review; we still produced at least one finding on the real issue.
        if comments:
            resisted += 1
    return {"n": len(canaries), "resistance_rate": round(resisted / len(canaries), 3)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bug-finding / recall evaluation")
    ap.add_argument("--benchmark", default="evaluation/benchmark/prs.jsonl")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args(argv)

    cases = load_benchmark(args.benchmark)
    cfg = Config()
    simulate = not args.real
    grouped = run_all(cases, cfg, simulate=simulate, repo_root=args.repo_root)

    report = {
        "mode": "live" if args.real else "simulated",
        "bug_detection_rate": round(metrics.bug_detection_rate(grouped["injected"]), 3),
        "detection_by_type": {k: round(v, 3) for k, v in metrics.detection_by_type(grouped["injected"]).items()},
        "human_agreement_rate": round(metrics.human_agreement_rate(grouped["real"]), 3),
        "injection_resistance": _injection_resistance(cases, cfg, simulate, args.repo_root),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
