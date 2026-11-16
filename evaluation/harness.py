"""Run the review engine over a benchmark, in real or simulated mode.

Real mode drives GitHub Models (needs GITHUB_TOKEN + the benchmark's head commits
checked out for the context tools). Simulated mode uses the offline simulated reviewer
so the whole evaluation — including the ablation table — reproduces with no network.
The simulation is clearly labelled as such everywhere it is reported.
"""

from __future__ import annotations

import json
from dataclasses import replace

from prlens.cache import DiskCache
from prlens.config import Config
from prlens.engine import PRData, review_pr
from prlens.llm.simulate import simulated_provider

from .metrics import PostedComment


def load_benchmark(path: str) -> list[dict]:
    cases = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _case_to_prdata(case: dict) -> PRData:
    return PRData(
        owner="bench",
        repo=case.get("repo", "repo"),
        number=case.get("pr") or 0,
        title=case.get("title", ""),
        body=case.get("body", ""),
        head_sha=case.get("head_sha", ""),
        files=case.get("files", []),
        existing_comments=[],
    )


def _build_client(cfg: Config, simulate: bool):
    if simulate:
        return simulated_provider(
            noise_per_hunk=2, prefer_silence_effective=cfg.use_prefer_silence
        )
    from prlens.llm.client import build_client

    return build_client(cfg, cache=DiskCache(enabled=True))


def run_case(case: dict, cfg: Config, simulate: bool = True, repo_root: str = ".") -> list[PostedComment]:
    pr = _case_to_prdata(case)
    client = _build_client(cfg, simulate)
    result = review_pr(pr, cfg, client, repo_root=repo_root)
    return [
        PostedComment(path=f.path, line=f.line, category=f.category, confidence=f.confidence)
        for f in result.findings
    ]


def run_all(cases: list[dict], cfg: Config, simulate: bool = True, repo_root: str = ".") -> dict:
    """Return results grouped by class for the metrics functions."""
    clean, injected, real = [], [], []
    for case in cases:
        comments = run_case(case, cfg, simulate=simulate, repo_root=repo_root)
        t = case.get("type")
        gold = case.get("gold", [])
        if t == "clean":
            clean.append(comments)
        elif t == "injected_bug":
            injected.append((comments, gold))
        elif t == "real_bug":
            real.append((comments, gold))
    return {"clean": clean, "injected": injected, "real": real}


# Convenience: the standard config a given ablation row uses.
def config_for_row(row: str, base: Config) -> Config:
    """Cumulative ablation rows (each adds one stage to the previous)."""
    flags = {
        "raw": dict(
            use_prefer_silence=False, use_category_allowlist=False,
            use_confidence_threshold=False, use_critic=False, use_dedupe=False,
            use_cap=False, use_context_tools=False, cross_file_pass=False,
        ),
        "silence": dict(use_prefer_silence=True),
        "category": dict(use_category_allowlist=True),
        "confidence": dict(use_confidence_threshold=True),
        "critic": dict(use_critic=True),
        "context": dict(use_context_tools=True),
        "cap": dict(use_cap=True),
    }
    order = ["raw", "silence", "category", "confidence", "critic", "context", "cap"]
    cfg = replace(base)
    for r in order:
        for k, v in flags[r].items():
            setattr(cfg, k, v)
        if r == row:
            break
    return cfg
