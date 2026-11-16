"""Configuration resolution.

Precedence (highest wins):
    1. ``.prlens.yml`` in the repository root (per-repo, author controlled)
    2. GitHub Action ``inputs`` (surfaced as ``INPUT_*`` environment variables)
    3. Built-in defaults

Keeping repo-level config above action inputs lets a repository owner tighten the
reviewer (e.g. a stricter confidence threshold) without the installer having to
edit their workflow file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

DEFAULT_CATEGORIES = ["bug", "security", "correctness", "performance"]

# GitHub Models is OpenAI-compatible. Verify the current base URL and model IDs in
# GitHub's docs before relying on them in production — both have churned. They live
# here and in action.yml, never hard-coded at a call site.
DEFAULT_BASE_URL = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4o-mini"


@dataclass
class Config:
    # Review behaviour
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    max_comments: int = 5
    min_confidence: float = 0.7
    exclude: list[str] = field(default_factory=list)
    instructions: str = ""

    # Model / provider
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    fallback_models: list[str] = field(default_factory=list)
    max_tool_calls_per_hunk: int = 4

    # Filter toggles (every stage is independently switchable — this is what the
    # Phase 8 ablation table is built from).
    use_prefer_silence: bool = True
    use_category_allowlist: bool = True
    use_confidence_threshold: bool = True
    use_critic: bool = True
    use_dedupe: bool = True
    use_cap: bool = True
    use_context_tools: bool = True

    # Operational
    dry_run: bool = False
    cross_file_pass: bool = True

    def with_overrides(self, **kw) -> Config:
        return replace(self, **{k: v for k, v in kw.items() if v is not None})


def _as_bool(val: str | bool | None, default: bool) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(val) -> list[str] | None:
    if val is None:
        return None
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return [x.strip() for x in str(val).split(",") if x.strip()]


def load_repo_config(path: str | os.PathLike) -> dict:
    """Load ``.prlens.yml`` if present; return {} otherwise."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _input(name: str) -> str | None:
    """Read a GitHub Action input (``INPUT_<NAME>``) or a plain env var fallback."""
    env = f"INPUT_{name.upper().replace('-', '_')}"
    return os.environ.get(env) or os.environ.get(name.upper().replace("-", "_"))


def build_config(
    repo_config_path: str | None = None,
    cli_overrides: dict | None = None,
) -> Config:
    """Resolve the effective configuration from all sources."""
    cfg = Config()

    # Layer 2: action inputs / env.
    cfg.model = _input("model") or cfg.model
    if (base := os.environ.get("PRLENS_BASE_URL")):
        cfg.base_url = base
    if (mc := _input("max-comments")) is not None:
        try:
            cfg.max_comments = int(mc)
        except ValueError:
            pass
    if (conf := _input("min-confidence")) is not None:
        try:
            cfg.min_confidence = float(conf)
        except ValueError:
            pass
    if (cats := _as_list(_input("categories"))) is not None:
        cfg.categories = cats

    # Layer 1: repo config overrides action inputs.
    config_file = (
        repo_config_path
        or _input("config-file")
        or ".prlens.yml"
    )
    repo = load_repo_config(config_file)
    if (v := _as_list(repo.get("categories"))) is not None:
        cfg.categories = v
    if "max_comments" in repo:
        cfg.max_comments = int(repo["max_comments"])
    if "min_confidence" in repo:
        cfg.min_confidence = float(repo["min_confidence"])
    if (v := _as_list(repo.get("exclude"))) is not None:
        cfg.exclude = v
    if "instructions" in repo and repo["instructions"]:
        cfg.instructions = str(repo["instructions"])
    if "model" in repo and repo["model"]:
        cfg.model = str(repo["model"])
    if (v := _as_list(repo.get("fallback_models"))) is not None:
        cfg.fallback_models = v

    # Filter toggles (mostly used by evaluation ablations, surfaced as env overrides).
    cfg.use_prefer_silence = _as_bool(os.environ.get("PRLENS_PREFER_SILENCE"), cfg.use_prefer_silence)
    cfg.use_category_allowlist = _as_bool(os.environ.get("PRLENS_CATEGORY_ALLOWLIST"), cfg.use_category_allowlist)
    cfg.use_confidence_threshold = _as_bool(os.environ.get("PRLENS_CONFIDENCE_THRESHOLD"), cfg.use_confidence_threshold)
    cfg.use_critic = _as_bool(os.environ.get("PRLENS_CRITIC"), cfg.use_critic)
    cfg.use_dedupe = _as_bool(os.environ.get("PRLENS_DEDUPE"), cfg.use_dedupe)
    cfg.use_cap = _as_bool(os.environ.get("PRLENS_CAP"), cfg.use_cap)
    cfg.use_context_tools = _as_bool(os.environ.get("PRLENS_CONTEXT_TOOLS"), cfg.use_context_tools)

    # Layer 0: explicit CLI overrides win over everything.
    if cli_overrides:
        cfg = cfg.with_overrides(**cli_overrides)

    return cfg
