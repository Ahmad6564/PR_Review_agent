from prlens.github.diff import all_commentable_lines, parse_patch, parse_pr_files

SAMPLE_PATCH = (
    "@@ -28,7 +28,10 @@ class Cache:\n"
    "     def set(self, key, value):\n"
    "         self._store[key] = value\n"
    "-        return value\n"
    "+        self._evict_if_needed()\n"
    "+        return value\n"
    "+\n"
    "+    def _evict_if_needed(self):\n"
    "+        pass"
)


def test_parse_patch_extracts_added_lines():
    hunks = parse_patch("src/cache.py", SAMPLE_PATCH)
    assert len(hunks) == 1
    h = hunks[0]
    assert h.path == "src/cache.py"
    # Added lines should be commentable; context/removed lines should not.
    assert h.added_lines, "expected some added lines"
    for ln in h.added_lines:
        assert h.commentable[ln] == "RIGHT"


def test_only_added_lines_are_commentable():
    hunks = parse_patch("src/cache.py", SAMPLE_PATCH)
    h = hunks[0]
    # The unchanged 'def set' / 'self._store' context lines must not be commentable.
    assert all(h.is_commentable(ln) for ln in h.added_lines)
    # There must be at least one non-commentable (context) line number in the hunk.
    content_line_numbers = {
        int(part.split()[0])
        for part in h.content.splitlines()
        if part.split() and part.split()[0].isdigit()
    }
    non_added = content_line_numbers - h.added_lines
    assert non_added, "expected context lines that are not commentable"


def test_empty_patch_returns_no_hunks():
    assert parse_patch("x.py", "") == []


def test_parse_pr_files_skips_missing_patch():
    files = [
        {"filename": "a.py", "patch": SAMPLE_PATCH},
        {"filename": "huge.bin"},  # no patch
    ]
    by_file = parse_pr_files(files)
    assert "a.py" in by_file
    assert "huge.bin" not in by_file


def test_all_commentable_lines():
    by_file = parse_pr_files([{"filename": "a.py", "patch": SAMPLE_PATCH}])
    commentable = all_commentable_lines(by_file)
    assert commentable["a.py"]
