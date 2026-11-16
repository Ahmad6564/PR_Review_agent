"""GitHub Action entrypoint.

Runs inside the container PRLens ships as. Reads the PR from the event payload,
fetches the diff purely as data (never executing PR code — see docs/security.md and
the pull_request_target trap), runs the engine, and posts a single review.

Designed to degrade gracefully: a missing model permission, a rate limit, or an
unexpected error should exit 0 with a clear log line, never turn the author's PR red.
An Action that fails the check is an Action people uninstall.
"""

from __future__ import annotations

import json
import os
import sys

from .cache import DiskCache
from .config import build_config
from .engine import PRData, review_pr
from .github.client import GitHub
from .github.review import post_review
from .llm.client import LLMUnavailable, build_client


def _log(msg: str) -> None:
    print(f"[prlens] {msg}", flush=True)


def _load_event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _pr_coordinates(event: dict) -> tuple[str, str, int] | None:
    pr = event.get("pull_request")
    repo = event.get("repository")
    if not pr or not repo:
        return None
    full = repo.get("full_name", "")
    if "/" not in full:
        return None
    owner, name = full.split("/", 1)
    return owner, name, int(pr["number"])


def run() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("INPUT_GITHUB_TOKEN")
    if not token:
        _log("No GITHUB_TOKEN available; nothing to do. Exiting cleanly.")
        return 0

    event = _load_event()
    coords = _pr_coordinates(event)
    if not coords:
        _log("Event is not a pull_request with a resolvable repository. Exiting cleanly.")
        return 0
    owner, repo, number = coords

    cfg = build_config()
    gh = GitHub(token)

    try:
        pr_json = gh.pr(owner, repo, number)
        files = gh.pr_files(owner, repo, number)
        existing = gh.existing_comments(owner, repo, number)
    except Exception as e:  # noqa: BLE001
        _log(f"Failed to fetch PR data: {e}. Exiting cleanly.")
        return 0

    pr = PRData(
        owner=owner,
        repo=repo,
        number=number,
        title=pr_json.get("title", ""),
        body=pr_json.get("body", "") or "",
        head_sha=pr_json.get("head", {}).get("sha", ""),
        files=files,
        existing_comments=existing,
    )

    try:
        client = build_client(cfg, cache=DiskCache(enabled=True))
    except LLMUnavailable as e:
        _log(f"No LLM provider available ({e}). Exiting cleanly without posting.")
        return 0

    try:
        result = review_pr(pr, cfg, client, repo_root=os.environ.get("GITHUB_WORKSPACE", "."))
    except LLMUnavailable as e:
        _log(f"LLM became unavailable mid-review ({e}). Exiting cleanly.")
        return 0
    except Exception as e:  # noqa: BLE001
        _log(f"Unexpected error during review: {e}. Exiting cleanly.")
        return 0

    _log(
        f"{len(result.findings)} comment(s) to post, "
        f"{len(result.filter_result.rejections)} rejected by filter, "
        f"{len(result.skipped)} file(s) skipped."
    )
    for r in result.filter_result.rejections:
        _log(f"  reject[{r.stage}] {r.finding.path}:{r.finding.line} — {r.reason}")

    if cfg.dry_run or os.environ.get("PRLENS_DRY_RUN"):
        _log("Dry run: not posting.")
        _log(result.summary)
        return 0

    try:
        post_review(
            gh, owner, repo, number,
            result.findings, result.summary, pr.head_sha,
        )
        _log("Review posted.")
    except Exception as e:  # noqa: BLE001
        _log(f"Failed to post review: {e}. Exiting cleanly (no merge blocked).")
        return 0

    return 0


def main() -> int:
    try:
        return run()
    except Exception as e:  # noqa: BLE001 - last-resort guard; never fail the check
        _log(f"Fatal but swallowed error: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
