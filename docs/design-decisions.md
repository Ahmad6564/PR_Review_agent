# Design decisions

The decisions that shaped PRLens, and the reasoning behind each. The theme throughout
is **precision, not coverage**: a reviewer that leaves two correct comments is valuable;
one that leaves fifteen comments, twelve of them noise, gets uninstalled within a day.

## Why a GitHub Action, not a GitHub App

| | Action (chosen) | App |
|---|---|---|
| Install effort | ~10 lines of YAML | OAuth flow, grant permissions |
| Hosting you run | none | a server, 24/7 |
| Cost to you | $0 | a VM + uptime responsibility |

The Action gives zero hosting cost, zero ops burden, and an install path simple enough
that people actually try it. The App version is future work.

## Why GitHub Models as the default provider

An Action that requires every installer to provision an OpenAI key gets installed by
almost nobody. GitHub Models is free for developers, OpenAI-compatible, and reachable
from inside the Action with the built-in token and a `models: read` permission — so
installers need **no API key at all**. That single fact is what makes the project free
*for its users*, not just its author.

The provider is pluggable (`prlens/llm/client.py`): a failover chain (Groq / Gemini /
Cerebras / OpenRouter free tiers, or a user key) and a local Ollama option for offline
development sit behind the same OpenAI-compatible interface. The base URL and model IDs
live in config, never hard-coded, because both have churned.

**Graceful degradation is a product requirement, not a nicety.** If the model
permission is missing or rate-limited, PRLens falls back, and failing that exits 0 with
a clear log line. An Action that turns someone's PR red is an Action they uninstall, so
PRLens never fails the check.

## The precision filter is the project

Everyone builds "fetch the PR → ask a model → post comments." Almost nobody builds the
stage in between that suppresses the model's eagerness. That stage — five independently
measurable components — is the actual engineering and the source of the evaluation.

1. **Category allowlist.** Style comments from a bot are pure noise; linters do it
   better and without opinions. `maintainability`/`style`/`test` are opt-in.
2. **Confidence threshold.** The schema forces a number and the prompt explains the
   consequence, which makes self-reported confidence informative enough to gate on. The
   correlation with usefulness is measured, not assumed.
3. **The critic pass.** A second model that sees the finding and tries to knock it down,
   told to default to rejection. The single highest-impact component: it rejects a large
   share of findings, disproportionately the bad ones. Every rejection is logged.
4. **Dedupe.** A PR gets 3–8 pushes; without dropping already-posted comments the bot
   re-posts every time and becomes hated. Repeats across many lines collapse into one.
5. **The hard cap.** Ten comments reads as an attack; three reads as a review. A product
   decision as much as a technical one.

The order is deliberate: cheap deterministic stages run before the expensive critic, so
LLM calls are spent only on findings that already passed the free gates.

## Per-hunk review, with a cheap cross-file pass

Reviewing per hunk (with the PR title/description as shared context) keeps attention
tight, maps findings cleanly to lines, parallelizes, and never blows the context window
on a 40-file PR. The cost is lost cross-file reasoning, recovered by one cheap whole-PR
pass that looks *only* for cross-cutting issues (a signature changed in one file but not
its callers). Those go in the summary, not inline.

## Only comment on added lines

PRLens only comments on lines the PR actually **added**. Commenting on untouched context
lines annoys authors who did not write them and often cannot fix them in this PR. The
rule costs a little recall and buys a lot of goodwill — and it makes the `422
Unprocessable Entity` errors (commenting outside the diff) largely disappear.

## `event: "COMMENT"`, never `REQUEST_CHANGES`

A bot that blocks merges is removed from the repo within a day. This is a product
judgment: PRLens informs, it does not gate. Saying so out loud signals that the design
optimizes for adoption, not just capability.

## The mined benchmark and its ground-truth signal

A human review comment is not necessarily a *good* comment. But a human review comment
**followed by a change to the exact lines it referenced, in a later commit on the same
PR** is strong evidence the comment identified something real. That yields an
automatically-derived label for *usefulness* (`mining/label_actionable.py`).

It is imperfect — the author may have changed that region for an unrelated reason, and
some good comments are resolved in discussion rather than code. The methodology handles
this honestly: hand-label a sample and report the agreement rate between the heuristic
and human judgment (`mining.label_actionable.verify_agreement`). That single number
turns a hack into a methodology.

The benchmark has three classes, weighted toward `clean`:

- **`clean`** — merged with approval, no changes requested. The precision target, and
  the most important class: any comment here is probably a false positive.
- **`real_bug`** — a human comment that was actioned. The recall target.
- **`injected_bug`** — a clean PR with a known defect introduced. Unambiguous ground
  truth, broken down by bug type.

## Mining route A vs route B

- **Route A (chosen for v1): GitHub Search + REST API.** Pick active, well-reviewed open
  source repos and pull merged PRs with review comments. Slower, but it definitely works
  on a Tuesday night. `mining/collect_prs.py`.
- **Route B: GH Archive on BigQuery.** The full public GitHub event stream is a BigQuery
  public dataset; the free tier includes 1 TB/month of query processing, far more than
  needed if you partition by day and select only the columns you need. Better résumé
  story, more setup. Documented here as the big-data enhancement; Route A ships first.

## The simulated model in evaluation

The evaluation harness runs in two modes. **Real mode** drives GitHub Models against the
mined benchmark — those are the numbers to cite. **Simulated mode** uses a deterministic
offline stand-in (`prlens/llm/simulate.py`) so the whole pipeline, including the ablation
table, reproduces with no network — which is what keeps CI green and lets a reader run
`make eval` in ten seconds. Every simulated result is labelled as such.

## What's deliberately out of scope

Multi-language deep analysis, repo-wide architectural review, test generation, a
dashboard. One thing done precisely is the pitch. Scope creep is the fastest way to turn
a sharp tool into a mediocre one.

## What I'd do next

Learn per-repo. The filter is global today. If maintainers resolve or 👎 certain
categories of comment, that is feedback, and a per-repo threshold adjusted from it would
be strictly better than one global setting.
