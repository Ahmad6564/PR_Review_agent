from prlens.context.tools import ToolBox


def _box(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def login(user):\n    return check(user)\n\ndef check(u):\n    return True\n",
        encoding="utf-8",
    )
    return ToolBox(tmp_path, {"title": "t", "body": "b", "files": ["src/app.py"]})


def test_read_file_returns_numbered_lines(tmp_path):
    box = _box(tmp_path)
    out = box.read_file("src/app.py", 1, 2)
    assert "def login" in out
    assert out.splitlines()[0].strip().startswith("1")


def test_read_file_blocks_path_traversal(tmp_path):
    box = _box(tmp_path)
    out = box.read_file("../../../../etc/passwd")
    assert out.startswith("Error: path outside repository")


def test_read_file_missing(tmp_path):
    box = _box(tmp_path)
    assert "not found" in box.read_file("src/nope.py")


def test_search_repo_finds_symbol(tmp_path):
    box = _box(tmp_path)
    out = box.search_repo("def check")
    assert "app.py" in out


def test_search_repo_no_match(tmp_path):
    box = _box(tmp_path)
    assert box.search_repo("zzz_nonexistent_symbol") in ("No matches.", "")


def test_get_pr_context(tmp_path):
    box = _box(tmp_path)
    out = box.get_pr_context()
    assert "Title:" in out and "src/app.py" in out


def test_dispatch_unknown_tool(tmp_path):
    box = _box(tmp_path)
    assert "unknown tool" in box.call("frobnicate", {})
