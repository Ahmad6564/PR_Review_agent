"""Phase 9 (optional) — build a supervised fine-tuning dataset.

Format each example as (diff hunk + file context) -> Finding JSON, drawn from the
mined, actioned human comments of Phase 7. Crucially, include NEGATIVE examples:
hunks from clean PRs whose correct output is {"findings": []}. Roughly half the set
should be negatives, or you train a model that always finds something — the exact
failure the precision filter exists to fix.

Input: the benchmark JSONL (or the raw mined JSONL). Output: a chat-format JSONL ready
for TRL/transformers SFT.
"""

from __future__ import annotations

import argparse
import json

from prlens.agent import prompts
from prlens.github.diff import parse_pr_files

SYSTEM = prompts.system_review(
    ["bug", "security", "correctness", "performance"], 0.7
)


def _hunk_prompt(path: str, hunk_content: str, title: str, body: str) -> str:
    return (
        f"PR title: {title}\nPR description: {body or '(none)'}\n\n"
        f"File: {path}\nDiff hunk:\n{hunk_content}\n\n"
        "Return a JSON object: {\"findings\": [...], \"summary\": \"...\"}."
    )


def example(system: str, user: str, assistant_json: dict) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(assistant_json)},
        ]
    }


def build(cases: list[dict]) -> tuple[list[dict], dict]:
    positives: list[dict] = []
    negatives: list[dict] = []
    for case in cases:
        title = case.get("title", "")
        body = case.get("body", "")
        by_file = parse_pr_files(case.get("files", []))
        gold = case.get("gold", [])
        gold_by_path: dict[str, list[dict]] = {}
        for g in gold:
            gold_by_path.setdefault(g.get("path"), []).append(g)

        for path, hunks in by_file.items():
            for hunk in hunks:
                user = _hunk_prompt(path, hunk.content, title, body)
                hunk_gold = [
                    g for g in gold_by_path.get(path, [])
                    if any(abs((g.get("line") or -999) - ln) <= 3 for ln in hunk.added_lines)
                ]
                if hunk_gold:
                    findings = [
                        {
                            "path": path,
                            "line": g.get("line"),
                            "category": g.get("category", "bug") if g.get("category") != "unknown" else "bug",
                            "severity": "major",
                            "confidence": 0.85,
                            "title": g.get("note", "Issue")[:60],
                            "body": g.get("note", ""),
                            "evidence": "derived from an actioned human review comment",
                        }
                        for g in hunk_gold
                    ]
                    positives.append(example(SYSTEM, user, {"findings": findings, "summary": "issue found"}))
                else:
                    negatives.append(example(SYSTEM, user, {"findings": [], "summary": "no issues found"}))

    # Balance: cap negatives to roughly match positives (keep >= as many negatives).
    target_neg = max(len(positives), min(len(negatives), len(positives) * 1 + len(positives)))
    balanced = positives + negatives[: max(target_neg, len(positives))]
    stats = {
        "positives": len(positives),
        "negatives_kept": len(balanced) - len(positives),
        "total": len(balanced),
    }
    return balanced, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build an SFT dataset")
    ap.add_argument("--benchmark", default="evaluation/benchmark/prs.jsonl")
    ap.add_argument("--out", default="finetune/sft.jsonl")
    args = ap.parse_args(argv)

    cases = []
    with open(args.benchmark, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    examples, stats = build(cases)
    with open(args.out, "w", encoding="utf-8") as fh:
        for ex in examples:
            fh.write(json.dumps(ex) + "\n")
    print(f"Wrote {stats['total']} SFT examples to {args.out}: {stats}")
    if stats["positives"] and stats["negatives_kept"] / max(1, stats["positives"]) < 0.8:
        print("WARNING: fewer negatives than positives — add clean-PR hunks to avoid an "
              "always-finds-something model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
