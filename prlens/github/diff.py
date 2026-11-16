"""Unified-diff parsing and line mapping.

The classic trap: to post an inline comment you must target a line that exists in
the diff, addressed by ``path`` + ``line`` + ``side`` (the modern API), not the old
``position`` offset counted within a hunk. Mixing them up is the single most common
bug in tools like this and yields opaque ``422 Unprocessable Entity`` responses.

Design rule: we only ever let the model comment on lines this PR *added*
(``line.is_added``). Commenting on untouched context lines annoys authors who did
not write them, costs a little recall, and buys a lot of goodwill. It also makes the
422s go away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from unidiff import PatchSet

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


@dataclass
class Hunk:
    path: str
    header: str
    content: str  # the hunk rendered with +/- markers and new-file line numbers
    added_lines: set[int] = field(default_factory=set)
    commentable: dict[int, str] = field(default_factory=dict)  # new_line -> side ("RIGHT")

    def is_commentable(self, line: int) -> bool:
        return line in self.commentable


def _line_repr(line) -> str:
    """Render one diff line with its marker and the resulting new-file line number."""
    marker = "+" if line.is_added else "-" if line.is_removed else " "
    ln = line.target_line_no if line.target_line_no is not None else ""
    return f"{str(ln):>5} {marker} {line.value.rstrip(chr(10))}"


def normalize_patch(patch_text: str) -> str:
    """Recompute each hunk header's line counts from the actual lines.

    Real GitHub ``patch`` fields already carry correct counts (so this is a no-op on
    them), but hand-written fixtures and lightly edited diffs often don't, and unidiff
    is strict ("Hunk is shorter than expected"). Recomputing makes parsing resilient.
    """
    lines = patch_text.splitlines()
    # Locate hunk headers and the spans between them.
    headers = [i for i, ln in enumerate(lines) if _HUNK_HEADER.match(ln)]
    if not headers:
        return patch_text
    out = list(lines)
    for idx, h in enumerate(headers):
        end = headers[idx + 1] if idx + 1 < len(headers) else len(lines)
        src = tgt = 0
        for ln in lines[h + 1 : end]:
            if ln.startswith("+") and not ln.startswith("+++"):
                tgt += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                src += 1
            elif ln.startswith("\\"):  # "\ No newline at end of file"
                continue
            else:
                src += 1
                tgt += 1
        m = _HUNK_HEADER.match(lines[h])
        s_start, t_start, heading = m.group(1), m.group(2), m.group(3)
        out[h] = f"@@ -{s_start},{src} +{t_start},{tgt} @@{heading}"
    return "\n".join(out)


def parse_patch(filename: str, patch_text: str) -> list[Hunk]:
    """Parse a single file's ``patch`` (unified diff fragment) into ``Hunk`` objects."""
    if not patch_text:
        return []
    patch_text = normalize_patch(patch_text)
    patch = PatchSet(f"--- a/{filename}\n+++ b/{filename}\n{patch_text}")
    hunks: list[Hunk] = []
    for f in patch:
        for h in f:
            commentable: dict[int, str] = {}
            added: set[int] = set()
            lines: list[str] = []
            for line in h:
                if line.is_added and line.target_line_no is not None:
                    commentable[line.target_line_no] = "RIGHT"
                    added.add(line.target_line_no)
                lines.append(_line_repr(line))
            hunks.append(
                Hunk(
                    path=filename,
                    header=str(h).split("\n", 1)[0],
                    content="\n".join(lines),
                    added_lines=added,
                    commentable=commentable,
                )
            )
    return hunks


def parse_pr_files(files: list[dict]) -> dict[str, list[Hunk]]:
    """Parse every file's patch. Files without a ``patch`` (too large) are skipped."""
    out: dict[str, list[Hunk]] = {}
    for f in files:
        patch = f.get("patch")
        if not patch:
            continue
        out[f["filename"]] = parse_patch(f["filename"], patch)
    return out


def all_commentable_lines(hunks_by_file: dict[str, list[Hunk]]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for path, hunks in hunks_by_file.items():
        s: set[int] = set()
        for h in hunks:
            s |= set(h.commentable.keys())
        out[path] = s
    return out
