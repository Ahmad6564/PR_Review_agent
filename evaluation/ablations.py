"""Phase 8 — the ablation table, the README centrepiece.

Seven cumulative rows, each a real component with a measured cost and benefit. The
story the table tells — the raw model posts many comments per clean PR; the full
pipeline posts a fraction of that, while keeping most injected-bug detection — is a
precision/recall tradeoff chosen deliberately and defensible.

Run (offline, simulated model):
    python -m evaluation.ablations --benchmark evaluation/benchmark/prs.jsonl \
        --out evaluation/results --simulate

Run against the real model (needs GITHUB_TOKEN and checked-out head commits):
    python -m evaluation.ablations --benchmark <mined>.jsonl --out evaluation/results --real
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prlens.config import Config

from . import metrics
from .harness import config_for_row, load_benchmark, run_all

ROWS = [
    ("raw", "Raw model, no filter"),
    ("silence", '+ "prefer silence" prompt'),
    ("category", "+ category allowlist"),
    ("confidence", "+ confidence threshold (0.7)"),
    ("critic", "+ critic pass"),
    ("context", "+ context tools (read_file, search)"),
    ("cap", "+ cap at 5 comments"),
]


def evaluate_row(row_key: str, cases: list[dict], base: Config, simulate: bool, repo_root: str) -> dict:
    cfg = config_for_row(row_key, base)
    grouped = run_all(cases, cfg, simulate=simulate, repo_root=repo_root)
    mixed = grouped["injected"] + grouped["real"]
    posted_with_match = []
    for comments, gold in mixed:
        for c in comments:
            posted_with_match.append(
                (c.confidence, metrics._matches_gold(c, gold))
            )
    return {
        "fp_per_clean": round(metrics.false_positives_per_clean_pr(grouped["clean"]), 3),
        "silence_rate": round(metrics.silence_rate(grouped["clean"]), 3),
        "bug_detection": round(metrics.bug_detection_rate(grouped["injected"]), 3),
        "useful_pct": round(metrics.useful_fraction(mixed) * 100, 1),
        "detection_by_type": {k: round(v, 3) for k, v in metrics.detection_by_type(grouped["injected"]).items()},
        "human_agreement": round(metrics.human_agreement_rate(grouped["real"]), 3),
        "confidence_correlation": metrics.confidence_precision_correlation(posted_with_match),
    }


def render_table(results: list[tuple[str, dict]]) -> str:
    header = (
        "| Configuration | FP/clean PR | Silence rate | Bug detection | Useful % |\n"
        "|---|---|---|---|---|"
    )
    lines = [header]
    for label, r in results:
        lines.append(
            f"| {label} | {r['fp_per_clean']:.2f} | {r['silence_rate']:.0%} | "
            f"{r['bug_detection']:.0%} | {r['useful_pct']:.0f}% |"
        )
    return "\n".join(lines)


def _charts(results: list[tuple[str, dict]], out_dir: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    labels = [lbl.replace("+ ", "+\n") for lbl, _ in results]
    fp = [r["fp_per_clean"] for _, r in results]
    det = [r["bug_detection"] for _, r in results]

    made = []
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(range(len(fp)), fp, color="#6b4fbb")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("False positives per clean PR")
    ax.set_title("Precision improves as filter stages are added (simulated)")
    fig.tight_layout()
    p1 = out_dir / "fp_per_clean.png"
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    made.append(str(p1))

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(range(len(fp)), fp, "o-", label="FP / clean PR", color="#6b4fbb")
    ax.plot(range(len(det)), det, "s-", label="Bug detection", color="#2a9d8f")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.legend()
    ax.set_title("Precision/recall tradeoff across the pipeline (simulated)")
    fig.tight_layout()
    p2 = out_dir / "precision_recall.png"
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    made.append(str(p2))
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Produce the ablation table")
    ap.add_argument("--benchmark", default="evaluation/benchmark/prs.jsonl")
    ap.add_argument("--out", default="evaluation/results")
    ap.add_argument("--repo-root", default=".")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="Offline simulated model (default)")
    mode.add_argument("--real", action="store_true", help="Use the real LLM (needs GITHUB_TOKEN)")
    args = ap.parse_args(argv)

    simulate = not args.real
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = load_benchmark(args.benchmark)
    base = Config()

    results = []
    for key, label in ROWS:
        r = evaluate_row(key, cases, base, simulate=simulate, repo_root=args.repo_root)
        results.append((label, r))
        print(
            f"{label:38s}  FP/clean={r['fp_per_clean']:.2f}  "
            f"silence={r['silence_rate']:.0%}  detect={r['bug_detection']:.0%}  "
            f"useful={r['useful_pct']:.0f}%"
        )

    table = render_table(results)
    mode_note = "simulated model" if simulate else "live model"
    (out_dir / "ablation_table.md").write_text(
        f"# Ablation table ({mode_note})\n\n"
        f"Benchmark: `{args.benchmark}` "
        f"({len(cases)} PRs). Generated by `evaluation/ablations.py`.\n\n"
        + table
        + "\n\n_Note: FP/clean PR is the flagship precision metric — comments posted "
        "on PRs that needed none. 'Useful %' is the share of posted comments on PRs "
        "with real issues that matched a gold line (±3). The simulated model is a "
        "deterministic stand-in so the pipeline reproduces offline; run with `--real` "
        "against the mined benchmark for the numbers you cite._\n",
        encoding="utf-8",
    )
    (out_dir / "ablation.json").write_text(
        json.dumps({"mode": mode_note, "n": len(cases), "rows": results}, indent=2, default=str),
        encoding="utf-8",
    )
    charts = _charts(results, out_dir)

    print("\n" + table)
    print("\nWrote ablation_table.md, ablation.json" + (f", {len(charts)} chart(s)" if charts else " (matplotlib not installed; charts skipped)"))
    print(f"Output dir: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
