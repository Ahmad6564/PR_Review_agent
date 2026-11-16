# Configuration

PRLens is configured in two places. **Action inputs** live in your workflow YAML and
are set by whoever installs the Action. A **`.prlens.yml`** file lives in the reviewed
repository and is controlled by its maintainers. When both set the same option, the
repo file wins — a maintainer can tighten the reviewer without editing the workflow.

## Action inputs

| Input | Default | Meaning |
|---|---|---|
| `github-token` | `${{ github.token }}` | Token used to read the PR and post the review. |
| `model` | `openai/gpt-4o-mini` | Model ID (GitHub Models, OpenAI-compatible). Verify current IDs in GitHub's docs — they churn. |
| `max-comments` | `5` | Hard cap on inline comments per PR. |
| `min-confidence` | `0.7` | Findings below this confidence are dropped (0–1). |
| `categories` | `bug,security,correctness,performance` | Comma-separated categories to report. |
| `config-file` | `.prlens.yml` | Path to the repo-level config. |

```yaml
- uses: Ahmad6564/PR_Review_agent@v1
  with:
    max-comments: "3"
    min-confidence: "0.8"
    categories: "bug,security"
```

## `.prlens.yml`

Place this in the root of the repository being reviewed.

```yaml
categories: [bug, security, correctness]
max_comments: 5
min_confidence: 0.75
exclude:
  - "tests/fixtures/**"
  - "docs/**"
instructions: |
  This project uses async SQLAlchemy. Flag any blocking I/O inside async functions.
  All public API responses must be Pydantic models, not raw dicts.
```

| Key | Type | Meaning |
|---|---|---|
| `categories` | list | Which categories are reported. Opt in to `maintainability`, `style`, `test`. |
| `max_comments` | int | Hard cap per PR. |
| `min_confidence` | float | Drop findings below this. |
| `exclude` | list(glob) | Files never reviewed (in addition to the built-in skip list). |
| `instructions` | string | Repo-specific guidance composed into the review prompt. |
| `model` | string | Override the model for this repo. |
| `fallback_models` | list | Reserved for the failover chain. |

### The `instructions` field

This is the most-requested feature of every tool in this space. It lets a repository
teach the reviewer its own conventions, and it is a clean demonstration of prompt
composition — the text is appended to the system prompt as maintainer guidance, inside
the normal restraint rules (so "flag X" never turns the reviewer chatty about
everything else).

## Categories

| Category | On by default | Notes |
|---|---|---|
| `bug` | ✅ | Logic errors, incorrect behaviour. |
| `security` | ✅ | Injection, auth, unsafe comparisons, secrets. |
| `correctness` | ✅ | Edge cases, error handling, contract violations. |
| `performance` | ✅ | Obvious inefficiency with real impact. |
| `maintainability` | ❌ opt-in | Structural concerns. Off by default — noisy. |
| `style` | ❌ opt-in | Linters do this better; off by default. |
| `test` | ❌ opt-in | Only with a specific untested case named. |

## Environment variables (advanced / evaluation)

Every filter stage can be toggled independently via environment variables. These exist
mainly for the ablation harness, but they work in the Action too.

| Variable | Effect |
|---|---|
| `PRLENS_PREFER_SILENCE` | Toggle the "prefer silence" prompt paragraph. |
| `PRLENS_CATEGORY_ALLOWLIST` | Toggle stage 1. |
| `PRLENS_CONFIDENCE_THRESHOLD` | Toggle stage 2. |
| `PRLENS_CRITIC` | Toggle the critic pass. |
| `PRLENS_DEDUPE` | Toggle dedupe. |
| `PRLENS_CAP` | Toggle the hard cap. |
| `PRLENS_CONTEXT_TOOLS` | Toggle `read_file` / `search_repo`. |
| `PRLENS_BASE_URL` | Override the GitHub Models base URL. |
| `PRLENS_DRY_RUN` | Compute the review but do not post it. |
| `PRLENS_FALLBACK_BASE_URL` / `_API_KEY` / `_MODEL` | A failover provider. |
| `PRLENS_OLLAMA` + `OLLAMA_MODEL` | Use a local Ollama model for offline dev. |

## Local development

```bash
pip install -e ".[dev]"

# Offline, no token, no quota — see the whole pipeline on a fixture:
python -m prlens.cli --fixture tests/fixtures/pr_injected_bug.json \
    --dry-run --simulate --repo-root tests/fixtures

# Against the real model (needs GITHUB_TOKEN with models access):
GITHUB_TOKEN=... python -m prlens.cli --fixture tests/fixtures/pr_injected_bug.json --dry-run
```
