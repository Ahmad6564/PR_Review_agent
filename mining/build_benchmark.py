"""Phase 7 — assemble the benchmark file.

Three classes, all required:
  * real_bug    — a human comment that was actioned. Recall target.
  * clean       — merged with approval and no change requests. Precision target, and
                  the most important class: make it at least half the benchmark.
  * injected_bug— a clean PR with a deliberately introduced defect. Unambiguous ground
                  truth, broken down by bug type.

60-100 benchmark PRs is enough. Weight toward `clean`.

Input: the JSONL produced by collect_prs.py (optionally run through label_actionable).
Output: evaluation/benchmark/prs.jsonl in the schema the evaluators consume.
"""

from __future__ import annotations

import argparse
import json
import sys

from .label_actionable import label_record


def _to_bench_clean(rec: dict, idx: int) -> dict:
    return {
        "id": f"bench{idx:04d}",
        "repo": rec["repo"],
        "pr": rec["pr"],
        "type": "clean",
        "head_sha": rec.get("head_sha", ""),
        "title": rec.get("title", ""),
        "body": rec.get("body", ""),
        "files": rec.get("files", []),
        "gold": [],
        "note": "merged with approving review and no change requests",
    }


def _to_bench_real_bug(rec: dict, idx: int) -> dict | None:
    gold = []
    for c in rec.get("review_comments", []):
        if c.get("actionable"):
            gold.append(
                {
                    "path": c["path"],
                    "line": c["line"],
                    "category": "unknown",
                    "note": c["body"][:200],
                    "source": "human_review_actioned",
                }
            )
    if not gold:
        return None
    return {
        "id": f"bench{idx:04d}",
        "repo": rec["repo"],
        "pr": rec["pr"],
        "type": "real_bug",
        "head_sha": rec.get("head_sha", ""),
        "title": rec.get("title", ""),
        "body": rec.get("body", ""),
        "files": rec.get("files", []),
        "gold": gold,
    }


def build(records: list[dict], clean_ratio: float = 0.5) -> list[dict]:
    bench: list[dict] = []
    idx = 1
    real_bugs, cleans = [], []
    for rec in records:
        labelled = label_record(rec)
        rb = _to_bench_real_bug(labelled, idx)
        if rb is not None:
            real_bugs.append(rec)
        else:
            cleans.append(rec)

    # Interleave to hit the target clean ratio, weighting toward clean.
    for rec in real_bugs:
        bench.append(_to_bench_real_bug(label_record(rec), idx))
        idx += 1
    target_clean = int(len(real_bugs) / max(1e-9, 1 - clean_ratio) * clean_ratio)
    for rec in cleans[: max(target_clean, len(real_bugs))]:
        bench.append(_to_bench_clean(rec, idx))
        idx += 1
    return bench


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the benchmark JSONL")
    ap.add_argument("--raw", required=True, help="JSONL from collect_prs.py")
    ap.add_argument("--out", default="evaluation/benchmark/prs.jsonl")
    ap.add_argument("--clean-ratio", type=float, default=0.5)
    args = ap.parse_args(argv)

    records = []
    with open(args.raw, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    bench = build(records, clean_ratio=args.clean_ratio)
    with open(args.out, "w", encoding="utf-8") as fh:
        for b in bench:
            fh.write(json.dumps(b) + "\n")

    n_clean = sum(1 for b in bench if b["type"] == "clean")
    n_bug = sum(1 for b in bench if b["type"] == "real_bug")
    print(
        f"Wrote {len(bench)} benchmark PRs ({n_clean} clean, {n_bug} real_bug) to {args.out}\n"
        f"Add injected_bug cases by hand or with mining/inject_bugs (not included).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
