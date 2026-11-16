"""Pre-filtering: half the precision problem is solved before the LLM sees anything.

Skip generated, vendored, lockfile and oversized changes. Report what was skipped
and why in the summary — transparency about what the tool did *not* look at builds
more trust than silently covering everything badly.
"""

from __future__ import annotations

from fnmatch import fnmatch

SKIP_PATTERNS = [
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "Cargo.lock",
    "go.sum",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.snap",
    "vendor/*",
    "node_modules/*",
    "dist/*",
    "build/*",
    "*.svg",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.ico",
    "*.pdf",
    "*.pb.go",
    "*_pb2.py",
    "*.generated.*",
    "*.designer.cs",
]

MAX_FILE_CHANGES = 800  # a 2000-line diff is a refactor, not a review target
MAX_FILES_REVIEWED = 25


def _matches_any(path: str, patterns: list[str]) -> bool:
    # Match the full path and also any path suffix segment so "vendor/*" catches
    # "a/b/vendor/x.go".
    if any(fnmatch(path, p) for p in patterns):
        return True
    parts = path.split("/")
    for i in range(len(parts)):
        tail = "/".join(parts[i:])
        if any(fnmatch(tail, p) for p in patterns):
            return True
    return False


def should_review(f: dict, exclude: list[str] | None = None) -> tuple[bool, str]:
    """Return (review?, reason-if-not)."""
    exclude = exclude or []
    if f.get("status") == "removed":
        return False, "file deleted"
    if _matches_any(f["filename"], SKIP_PATTERNS):
        return False, "generated or vendored"
    if exclude and _matches_any(f["filename"], exclude):
        return False, "excluded by .prlens.yml"
    if f.get("additions", 0) + f.get("deletions", 0) > MAX_FILE_CHANGES:
        return False, "too large to review meaningfully"
    if not f.get("patch"):
        return False, "no patch available"
    return True, ""


def select_files(files: list[dict], exclude: list[str] | None = None) -> tuple[list[dict], list[tuple[str, str]]]:
    """Split files into (to-review, [(filename, skip-reason), ...])."""
    reviewed: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for f in files:
        ok, reason = should_review(f, exclude)
        if ok and len(reviewed) < MAX_FILES_REVIEWED:
            reviewed.append(f)
        elif ok:
            skipped.append((f["filename"], f"over the {MAX_FILES_REVIEWED}-file review cap"))
        else:
            skipped.append((f["filename"], reason))
    return reviewed, skipped
