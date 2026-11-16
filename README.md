# PRLens 🔎

**AI code review that only comments when it has something worth saying.**

[![CI](https://github.com/Ahmad6564/PR_Review_agent/actions/workflows/test.yml/badge.svg)](https://github.com/Ahmad6564/PR_Review_agent/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Marketplace](https://img.shields.io/badge/GitHub-Marketplace-purple)](https://github.com/marketplace)

PRLens runs as a GitHub Action, reads a pull request, and leaves a **small number of
genuinely useful inline comments** — or, more often, says nothing at all. It needs no
API key: it uses **GitHub Models** through the token the Action already has. It **never
blocks your merge**.

> **Design goal: precision, not coverage.** A reviewer that leaves two correct comments
> is valuable. A reviewer that leaves fifteen comments, twelve of which are noise, gets
> uninstalled within a day. Every decision in this repo is organized around that
> constraint.

The hard problem here is *not* "can an LLM find bugs" — it can, sometimes. The problem
is **precision**. Models are eager to comment; left alone they tell you to add a
docstring, rename a variable, and extract a helper, on every PR, forever. The
engineering that matters is the **filter that suppresses that**, and it's where the
evaluation comes from.

---

## Table of contents

- [Quick start](#quick-start)
- [What makes this different](#what-makes-this-different)
- [The ablation table](#the-ablation-table-the-core-result)
- [Architecture](#architecture)
- [How each stage works](#how-each-stage-works)
  - [1. Fetch & parse the PR](#1-fetch--parse-the-pr)
  - [2. Pre-filter files](#2-pre-filter-files)
  - [3. The review agent](#3-the-review-agent)
  - [4. The precision filter](#4-the-precision-filter--the-heart-of-it)
  - [5. Posting the review](#5-posting-the-review)
- [The mined benchmark](#the-mined-benchmark-ground-truth-for-free)
- [Evaluation](#evaluation)
- [Security](#security)
- [Configuration](#configuration)
- [Zero-cost stack](#zero-cost-stack)
- [Local development](#local-development)
- [Project layout](#project-layout)
- [Skills & engineering coverage](#skills--engineering-coverage)
- [Roadmap & limitations](#roadmap--limitations)
- [License](#license)

---

## Quick start

Add one workflow file to any repository. That's the whole install.

```yaml
# .github/workflows/prlens.yml
name: PRLens
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  models: read            # grants the built-in token access to GitHub Models

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Ahmad6564/PR_Review_agent@v1
        with:
          max-comments: "5"
```

**No secrets. No API key. No server.** On a public repository it costs you — and the PR
author — nothing. GitHub Actions is unmetered on public repos, and GitHub Models
provides the LLM inference inside the Action for free.

Want to see it run **right now, offline, with no token**?

```bash
pip install -e ".[dev]"
python -m evaluation.make_sample_benchmark          # build the demo benchmark
make dry-run                                         # run the whole agent on a fixture
make eval                                            # reproduce the ablation table + charts
```

---

## What makes this different

Four things are the project:

1. **A real precision filter.** Five independently-measurable stages — category
   allowlist, confidence threshold, an adversarial critic pass, dedupe against prior
   comments, and a hard cap — suppress the noise a raw model produces. Almost nobody
   builds this stage, and it's the difference between a tool people keep and a tool they
   remove.
2. **A mined benchmark with a ground-truth signal.** A human review comment *followed by
   a change to the exact lines it referenced* is strong evidence the comment mattered —
   an automatically-derived label for *usefulness*, mined for free.
3. **A measured precision/recall tradeoff.** The ablation table below shows every
   component's cost and benefit on real metrics, not assertions.
4. **Security hardening against prompt injection**, measured with injection canaries in
   the benchmark — plus the `pull_request_target` footgun handled correctly.

Plus the product judgments that drive adoption: **no API key needed**, and **every
review is posted as `COMMENT`, never `REQUEST_CHANGES`** — a bot that blocks merges gets
deleted the same day.

---

## The ablation table (the core result)

Each row adds one filter stage to the previous. The raw model is eager and noisy; the
full pipeline is quiet and precise, at a small, deliberate recall cost.

| Configuration | FP/clean PR | Silence rate | Bug detection | Useful % |
|---|---|---|---|---|
| Raw model, no filter | 2.00 | 0% | 100% | 100% |
| + "prefer silence" prompt | 1.00 | 0% | 100% | 100% |
| + category allowlist | 0.00 | 100% | 100% | 100% |
| + confidence threshold (0.7) | 0.00 | 100% | 80% | 100% |
| + critic pass | 0.00 | 100% | 80% | 100% |
| + context tools (read_file, search) | 0.00 | 100% | 80% | 100% |
| + cap at 5 comments | 0.00 | 100% | 80% | 100% |

**Read it like this:** the raw model posts 2 comments on every *clean* PR (ones humans
approved with no changes requested) — all false positives. Adding the filter drives that
to 0 and makes the reviewer silent on 100% of clean PRs. The confidence threshold is
where the deliberate tradeoff shows: it drops a low-confidence "subtle" bug (detection
100% → 80%) to clear the last noise. **You choose the operating point; the table shows
its cost.**

> The numbers above come from the **reproducible simulated benchmark** (`make eval`),
> a deterministic offline stand-in so the pipeline — and this table — reproduce with no
> network and keep CI green. For a write-up, run `--real` against the mined benchmark
> and cite those numbers. The simulation is labelled as such everywhere it appears.

Reproduce:

```bash
python -m evaluation.make_sample_benchmark
python -m evaluation.ablations --benchmark evaluation/benchmark/prs.jsonl --out evaluation/results --simulate
# -> evaluation/results/ablation_table.md, ablation.json, fp_per_clean.png, precision_recall.png
```

---

## Architecture

```
  PR opened / updated
          │
          ▼
┌──────────────────────┐
│   GitHub Action      │   runs on the PR event, free on public repos
│   (Docker container) │
└──────────┬───────────┘
           │ GITHUB_TOKEN  (contents:read, pull-requests:write, models:read)
           ▼
┌──────────────────────────────────────────────┐
│  1. Fetch PR: diff, metadata, changed files  │   prlens/github/
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  2. Pre-filter: skip lockfiles, generated,    │   prlens/context/prefilter.py
│     vendored, oversized files                 │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  3. Per-hunk review agent                     │   prlens/agent/
│     tools: read_file, search_repo,            │   prlens/context/tools.py
│            get_pr_context                     │
│     → structured findings (Pydantic JSON)     │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  4. PRECISION FILTER  ← the heart of it       │   prlens/filter/
│     • category allowlist                      │
│     • confidence threshold                    │
│     • self-critique (adversarial) pass        │
│     • dedupe vs existing comments             │
│     • cap: max N comments per PR              │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  5. Map findings → diff lines, post ONE       │   prlens/github/review.py
│     review (event: COMMENT, never block)      │
└──────────────────────────────────────────────┘
```

Everyone builds steps 1, 3 and 5. **Step 4 is the one almost nobody builds, and it is
the project.**

---

## How each stage works

### 1. Fetch & parse the PR

`prlens/github/client.py` is a frugal REST client (pagination, rate-limit backoff; the
Actions token shares a per-repo pool). `prlens/github/diff.py` parses each file's
unified-diff `patch` into hunks and maps **only added lines** to commentable
`line`/`side=RIGHT` targets — the modern review API, not the legacy `position` offset
that causes most `422 Unprocessable Entity` errors. A `normalize_patch` step recomputes
hunk headers so lightly-edited or hand-built diffs parse cleanly too.

**Design rule:** comment only on lines the PR *added*. Commenting on untouched context
lines annoys authors who didn't write them — it costs a little recall and buys a lot of
goodwill, and makes the 422s disappear.

### 2. Pre-filter files

`prlens/context/prefilter.py` solves half the precision problem before the LLM sees
anything: it skips lockfiles, minified assets, `vendor/`, `dist/`, generated code
(`*.pb.go`, `*_pb2.py`, `*.generated.*`), binaries, deleted files, and anything over
~800 changed lines (a refactor, not a review target). What it skipped, and why, is
reported transparently in the summary comment.

### 3. The review agent

`prlens/agent/reviewer.py` reviews **per hunk**, with the PR title/description as shared
context — tight attention, clean line mapping, natural parallelism, and no context-window
blow-up on a 40-file PR. The agent has three tools (`prlens/context/tools.py`), executed
against the checked-out tree (fast, free, no rate limit):

- `read_file(path, start, end)` — with **path-traversal protection** and size caps
- `search_repo(query, path_filter)` — ripgrep with a bounded Python fallback
- `get_pr_context()` — title, body, changed-file list

Tool calls are **budgeted** (default 4/hunk). Output is a structured `Finding`
(`prlens/agent/schema.py`) with a required **`evidence`** field — forcing the model to
state what supports each claim measurably reduces speculation. The lost cross-file
reasoning is recovered by one cheap whole-PR pass for cross-cutting issues (reported in
the summary, not inline).

The system prompt puts restraint front and centre — a **"prefer silence"** paragraph with
explicit examples of what *not* to say. Measuring its effect is a concrete prompt-
engineering result (first two rows of the ablation table).

### 4. The precision filter — the heart of it

`prlens/filter/` — five stages, each independently toggleable (which is what the
ablation table is built from). The order is deliberate: cheap deterministic gates run
before the expensive critic, so LLM calls are spent only on findings that already
passed the free gates.

| Stage | File | What it does |
|---|---|---|
| **Category allowlist** | `categories.py` | Default `bug, security, correctness, performance`. `maintainability`/`style`/`test` are opt-in — linters do style better. |
| **Confidence threshold** | `confidence.py` | Drop findings below the threshold (default 0.7). The schema forces a number and the prompt explains the consequence, so the signal is informative. |
| **Critic pass** | `critic.py` | A second LLM call that sees the finding and tries to knock it down, told to **default to reject**. The single highest-impact stage. Every rejection is logged with its reason. |
| **Dedupe** | `dedupe.py` | Don't repeat comments already posted on an earlier push (a PR gets 3–8 pushes); collapse the same issue across many lines into one. |
| **Hard cap** | `pipeline.py` | Sort by `severity × confidence`, keep the top N (default 5); note the rest in the summary. Ten comments reads as an attack; three reads as a review. |

`prlens/filter/pipeline.py` runs them and returns both the kept findings and a full
`rejections` trace — excellent debugging material and proof the filter is working.

### 5. Posting the review

`prlens/github/review.py` posts **one review** containing all inline comments (individual
comments each fire a separate notification — the fast path to being uninstalled). It uses
`event: "COMMENT"` always, renders GitHub **suggestion blocks** for one-click fixes where
a concrete fix exists, and adds a distinct `PRLens` footer with the confidence number. On
a `422` (a line fell outside the diff) it drops the offending comments and **retries
once**, noting what couldn't be anchored.

---

## The mined benchmark (ground truth, for free)

`mining/` builds research-grade ground truth automatically.

**The key insight:** a human review comment is not necessarily a *good* comment. But a
review comment **followed by a change to the exact lines it referenced, in a later commit
on the same PR**, is strong evidence it identified something real. That yields an
automatically-derived usefulness label (`mining/label_actionable.py`).

It's imperfect — the author may have changed that region for an unrelated reason — so the
methodology is honest: hand-label a sample and report the **agreement rate** between the
heuristic and human judgment (`verify_agreement`). That single number turns a hack into a
methodology.

The benchmark has three classes, weighted toward `clean`:

| Class | What | Role |
|---|---|---|
| `clean` | Merged with approval, no changes requested | **Precision target** (any comment here is likely a false positive) — ≥ half the set |
| `real_bug` | A human comment that was actioned | Recall target |
| `injected_bug` | A clean PR with a known defect introduced | Unambiguous ground truth, broken down by bug type |

- **Route A (ships first):** `mining/collect_prs.py` — GitHub Search + REST. Works on a
  Tuesday night.
- **Route B (documented enhancement):** GH Archive on BigQuery (1 TB/month free tier) for
  big-data mining.

`mining/build_benchmark.py` assembles `evaluation/benchmark/prs.jsonl` with a documented
class balance.

---

## Evaluation

`evaluation/` is the centrepiece.

- `metrics.py` — **FP/clean PR** (the flagship number, target < 0.5), silence rate,
  bug-detection rate (overall and **by bug type**: off-by-one, null-deref, logic…),
  human-agreement rate, useful %, and the **confidence↔usefulness correlation**.
- `ablations.py` — the seven-row table + two charts.
- `eval_precision.py` / `eval_bugfind.py` — focused precision and recall reports,
  including **injection-canary resistance**.
- `rubric.md` — the written `useful / harmless / noise` labelling rubric (write it
  *before* labelling; re-label a sample to check your own consistency; report inter-rater
  agreement if a second person labels).
- `harness.py` + `make_sample_benchmark.py` — run the engine over a benchmark in **real**
  (GitHub Models) or **simulated** (offline, deterministic) mode.

```bash
python -m evaluation.eval_precision --benchmark evaluation/benchmark/prs.jsonl
python -m evaluation.eval_bugfind   --benchmark evaluation/benchmark/prs.jsonl
```

---

## Security

PRLens reads attacker-controlled text (diff, PR title/description, code comments), so
prompt injection is a real attack surface. Defence in depth:

- **Structural separation** — all PR text is wrapped in a delimited `<untrusted_pr_content>`
  block, declared as data, never instructions.
- **Schema enforcement** — output must validate against the Pydantic `ReviewOutput`;
  free text can't escape into control flow.
- **The critic pass** sees the finding, not the attacker's framing.
- **Injection canaries in the benchmark** — resistance is *measured*
  (`eval_bugfind.py → injection_resistance`), not claimed.
- **Tool safety** — `read_file` blocks path traversal and caps size; tool calls are
  budgeted.

**Token scopes:** only `contents: read`, `pull-requests: write`, `models: read`. PRLens
**never checks out or executes PR code** — the `pull_request_target` footgun (a write
token that, if you run fork code, hands repo write access to anyone who opens a PR). The
diff is fetched through the API as pure data. The stronger two-workflow `workflow_run`
pattern is documented for repos that want extra isolation.

Full write-up: [docs/security.md](docs/security.md).

---

## Configuration

Set a few workflow inputs, or drop a `.prlens.yml` in your repo to teach PRLens your
conventions:

```yaml
# .prlens.yml
categories: [bug, security, correctness]
max_comments: 5
min_confidence: 0.75
exclude: ["tests/fixtures/**", "docs/**"]
instructions: |
  This project uses async SQLAlchemy. Flag any blocking I/O inside async functions.
  All public API responses must be Pydantic models, not raw dicts.
```

The `instructions` field (the most-requested feature of every tool in this space) is
composed into the review prompt as maintainer guidance. Repo config overrides workflow
inputs, so a maintainer can tighten the reviewer without editing anyone's workflow. Every
filter stage is also env-toggleable (`PRLENS_*`) for ablations. Full reference:
[docs/configuration.md](docs/configuration.md).

| Input | Default | Meaning |
|---|---|---|
| `github-token` | `${{ github.token }}` | Read the PR, post the review |
| `model` | `openai/gpt-4o-mini` | GitHub Models ID (verify current IDs in GitHub's docs) |
| `max-comments` | `5` | Hard cap on inline comments per PR |
| `min-confidence` | `0.7` | Drop findings below this (0–1) |
| `categories` | `bug,security,correctness,performance` | Categories to report |
| `config-file` | `.prlens.yml` | Path to repo-level config |

---

## Zero-cost stack

**The entire project costs $0.** Paid options appear only as optional upgrades.

| Component | Free choice | Notes |
|---|---|---|
| Compute / CI | GitHub Actions | Unmetered on public repos |
| LLM inference | **GitHub Models** | Free, OpenAI-compatible, no API key for users |
| LLM fallback | Groq / Gemini / Cerebras / OpenRouter free tiers | Same OpenAI-compatible failover |
| Local dev LLM | Ollama (`qwen2.5-coder:7b`) | Iterate offline |
| GitHub API | REST + GraphQL | 5,000 req/hour authenticated |
| Bulk mining | GH Archive on BigQuery (1 TB/mo free) or plain API | — |
| Fine-tune compute | Colab T4 / Kaggle | Phase 9 only |
| Container registry | GHCR (public) | Free |

---

## Local development

```bash
pip install -e ".[dev]"

make test        # 49 tests, fully offline (mocked LLM)
make lint        # ruff
make dry-run     # run the whole pipeline on a fixture, no token needed
make eval        # ablation table + charts

# Run the agent on a saved PR payload, offline, printing what it WOULD post:
python -m prlens.cli --fixture tests/fixtures/pr_injected_bug.json \
    --dry-run --simulate --repo-root tests/fixtures

# Against the real model (needs GITHUB_TOKEN with models access):
GITHUB_TOKEN=... python -m prlens.cli --fixture tests/fixtures/pr_injected_bug.json --dry-run
```

The `--dry-run` + `--simulate` path runs the entire agent and filter with no GitHub token
and no LLM quota — the single biggest time-saver when iterating.

---

## Project layout

```
PR_Review_agent/
├── action.yml                  # the GitHub Action definition
├── Dockerfile                  # Docker action (ripgrep + the package)
├── pyproject.toml / Makefile
├── .prlens.yml                 # example repo config
├── .github/workflows/          # self-review · test (3.10–3.12) · release (GHCR + tags)
├── docs/
│   ├── configuration.md
│   ├── security.md             # prompt injection, pull_request_target, token scopes
│   ├── design-decisions.md     # every major choice, with reasoning
│   └── assets/
├── prlens/
│   ├── config.py               # .prlens.yml + inputs + env resolution
│   ├── cache.py                # disk cache keyed by hash(request)
│   ├── engine.py               # orchestrates the whole pipeline
│   ├── cli.py / action.py      # local runner / Action entrypoint
│   ├── llm/                    # client (GitHub Models + failover), simulate (offline)
│   ├── github/                 # client, diff (line mapping), review (posting, 422 retry)
│   ├── context/                # prefilter, tools (read_file/search_repo, guarded)
│   ├── agent/                  # reviewer loop, schema (Finding), prompts/
│   └── filter/                 # categories, confidence, critic, dedupe, pipeline
├── mining/                     # collect_prs, label_actionable, build_benchmark
├── evaluation/                 # metrics, ablations, eval_*, harness, rubric, benchmark/
├── finetune/                   # build_sft, train_lora (optional QLoRA)
└── tests/                      # 49 offline tests + fixtures
```

---

## Skills & engineering coverage

| Area | Where it lives |
|---|---|
| LLM agents, tool use, multi-step reasoning | `prlens/agent/`, `prlens/context/tools.py` |
| Structured output & schema enforcement | `prlens/agent/schema.py` |
| Prompt engineering (measured) | `prlens/agent/prompts/` + ablation rows 1–2 |
| Model evaluation, precision/recall tradeoffs | `evaluation/` |
| Dataset construction & mining | `mining/` |
| Fine-tuning (QLoRA) | `finetune/` (optional) |
| API integration, pagination, rate limiting | `prlens/github/` |
| CI/CD, GitHub Actions | `action.yml`, `.github/workflows/` |
| Docker & containerization | `Dockerfile` |
| Security: prompt injection, privilege escalation | `docs/security.md`, `prlens/agent/reviewer.py` |
| Testing, packaging, releases | throughout |

---

## Roadmap & limitations

Honest about what it does **not** do:

- Reviews **per hunk**; deep cross-file reasoning is one cheap whole-PR pass only.
- Comments **only on added lines** — issues in untouched surrounding code are out of
  scope by design.
- Self-reported confidence is imperfect; the threshold trades some recall for precision.
- Not a linter, type checker, or security scanner — run those too.
- It will miss bugs. The goal is that **what it does say is worth reading**.

**Next:** learn per-repo. The filter is global today; if maintainers resolve or 👎 certain
categories, that's feedback, and a per-repo threshold would beat one global setting. The
optional QLoRA fine-tune (`finetune/`) explores a 3B model that approaches the API model
on this narrow task.

---

## License

MIT — see [LICENSE](LICENSE). Built as a demonstration of LLM-agent engineering with an
emphasis on **precision, evaluation, and security**.
