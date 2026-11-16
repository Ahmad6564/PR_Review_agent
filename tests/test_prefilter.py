from prlens.context.prefilter import select_files, should_review


def _f(name, add=5, dele=0, status="modified", patch="@@ -1 +1 @@\n+x"):
    d = {"filename": name, "additions": add, "deletions": dele, "status": status}
    if patch is not None:
        d["patch"] = patch
    return d


def test_skips_lockfiles():
    ok, reason = should_review(_f("package-lock.json"))
    assert not ok and "generated" in reason


def test_skips_nested_vendor():
    ok, reason = should_review(_f("a/b/vendor/lib.go"))
    assert not ok


def test_skips_deleted_files():
    ok, reason = should_review(_f("src/x.py", status="removed"))
    assert not ok and "deleted" in reason


def test_skips_oversized():
    ok, reason = should_review(_f("src/x.py", add=900, dele=200))
    assert not ok and "large" in reason


def test_skips_no_patch():
    ok, reason = should_review(_f("src/x.py", patch=None))
    assert not ok and "patch" in reason


def test_reviews_normal_file():
    ok, reason = should_review(_f("src/x.py"))
    assert ok and reason == ""


def test_exclude_glob():
    ok, reason = should_review(_f("docs/guide.md"), exclude=["docs/**"])
    assert not ok and "excluded" in reason


def test_select_files_partitions():
    files = [_f("src/a.py"), _f("yarn.lock"), _f("src/b.py")]
    reviewed, skipped = select_files(files)
    names = {f["filename"] for f in reviewed}
    assert names == {"src/a.py", "src/b.py"}
    assert any("yarn.lock" == n for n, _ in skipped)
