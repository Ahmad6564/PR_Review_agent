"""Agent tools, executed against the checked-out working directory.

After ``actions/checkout`` the repo is on disk at the PR's head commit, so
``read_file`` and ``search_repo`` are local reads: fast, free, and not rate-limited.

Security: both tools are driven by model output, which may itself be influenced by
attacker-controlled diff text. ``read_file`` resolves and confines every path to the
repository root (blocking ``../../etc/passwd``), and tool calls are budgeted per hunk
so the agent cannot read twelve files on a one-line change.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

MAX_FILE_BYTES = 1_000_000
MAX_READ_LINES = 400
MAX_SEARCH_HITS = 40

# Tool specs advertised to the model (OpenAI function-calling shape).
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read lines from a file in the repository at the PR's head commit. "
                "Use this to see the function containing a change, its callers, or a "
                "definition referenced by the diff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_repo",
            "description": (
                "Search the repository for a string or symbol. Use this to find where a "
                "changed function is called, or whether a pattern exists elsewhere."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path_filter": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pr_context",
            "description": "Get the PR title, description, and the list of all changed files.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class ToolBox:
    """Bound tool implementations for one review run."""

    def __init__(self, repo_root: str | os.PathLike, pr_context: dict):
        self.root = Path(repo_root).resolve()
        self.pr_context = pr_context  # {"title", "body", "files": [...]}

    # ----------------------------------------------------------- read_file
    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        try:
            resolved = (self.root / path).resolve()
        except (OSError, ValueError):
            return "Error: invalid path."
        # Path traversal protection — confine to the repo root.
        if not (resolved == self.root or str(resolved).startswith(str(self.root) + os.sep)):
            return "Error: path outside repository."
        if not resolved.exists() or not resolved.is_file():
            return "Error: file not found."
        try:
            if resolved.stat().st_size > MAX_FILE_BYTES:
                return "Error: file too large."
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return f"Error: could not read file ({e})."

        start = max(1, int(start_line))
        end = int(end_line) if end_line else start + MAX_READ_LINES - 1
        end = min(end, len(lines), start + MAX_READ_LINES - 1)
        selected = lines[start - 1 : end]
        numbered = [f"{start + i:>6}  {ln}" for i, ln in enumerate(selected)]
        return "\n".join(numbered) if numbered else "(empty range)"

    # ---------------------------------------------------------- search_repo
    def search_repo(self, query: str, path_filter: str | None = None) -> str:
        if not query or len(query) > 200:
            return "Error: invalid query."
        # Prefer ripgrep if available; fall back to a bounded Python walk.
        hits = self._ripgrep(query, path_filter)
        if hits is None:
            hits = self._python_search(query, path_filter)
        if not hits:
            return "No matches."
        return "\n".join(hits[:MAX_SEARCH_HITS])

    def _ripgrep(self, query: str, path_filter: str | None):
        try:
            cmd = ["rg", "--no-heading", "--line-number", "--fixed-strings",
                   "--max-count", "5", query]
            if path_filter:
                cmd += ["--glob", path_filter]
            out = subprocess.run(
                cmd, cwd=self.root, capture_output=True, text=True, timeout=15
            )
            if out.returncode not in (0, 1):  # 1 = no matches
                return None
            return [ln for ln in out.stdout.splitlines() if ln][:MAX_SEARCH_HITS]
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

    def _python_search(self, query: str, path_filter: str | None) -> list[str]:
        from fnmatch import fnmatch

        hits: list[str] = []
        for p in self.root.rglob("*"):
            if len(hits) >= MAX_SEARCH_HITS:
                break
            if not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            if any(seg in rel for seg in (".git/", "node_modules/", "dist/", "build/")):
                continue
            if path_filter and not fnmatch(rel, path_filter):
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                for i, ln in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if query in ln:
                        hits.append(f"{rel}:{i}:{ln.strip()[:160]}")
                        if len(hits) >= MAX_SEARCH_HITS:
                            break
            except OSError:
                continue
        return hits

    # -------------------------------------------------------- get_pr_context
    def get_pr_context(self) -> str:
        c = self.pr_context
        files = "\n".join(f"- {f}" for f in c.get("files", []))
        return (
            f"Title: {c.get('title', '')}\n"
            f"Description:\n{c.get('body', '') or '(none)'}\n"
            f"Changed files:\n{files}"
        )

    # --------------------------------------------------------------- dispatch
    def call(self, name: str, args: dict) -> str:
        if name == "read_file":
            return self.read_file(
                args.get("path", ""),
                args.get("start_line", 1),
                args.get("end_line"),
            )
        if name == "search_repo":
            return self.search_repo(args.get("query", ""), args.get("path_filter"))
        if name == "get_pr_context":
            return self.get_pr_context()
        return f"Error: unknown tool {name!r}."
