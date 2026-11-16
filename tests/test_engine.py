import json
from pathlib import Path

from prlens.config import Config
from prlens.engine import PRData, review_pr
from prlens.github.diff import parse_pr_files
from tests.helpers import make_mock_client

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return PRData.from_fixture(json.loads((FIX / name).read_text(encoding="utf-8")))


def _an_added_line(pr: PRData) -> tuple[str, int]:
    by_file = parse_pr_files(pr.files)
    for path, hunks in by_file.items():
        for h in hunks:
            if h.added_lines:
                return path, sorted(h.added_lines)[0]
    raise AssertionError("fixture has no added lines")


def test_injected_bug_produces_a_comment():
    pr = _load("pr_injected_bug.json")
    path, line = _an_added_line(pr)
    finding = {
        "path": path, "line": line, "category": "bug", "severity": "major",
        "confidence": 0.9, "title": "Stale index", "body": "Order list never trimmed.",
        "evidence": "del self._store[oldest]",
    }
    client = make_mock_client(review_findings=[finding], critic_keep=True)
    cfg = Config(cross_file_pass=False, use_context_tools=False)
    result = review_pr(pr, cfg, client, repo_root=str(FIX))
    assert result.would_post
    assert result.findings[0].line == line


def test_clean_pr_posts_nothing_and_skips_lockfile():
    pr = _load("pr_clean.json")
    client = make_mock_client(review_findings=[], critic_keep=True)
    cfg = Config(cross_file_pass=False, use_context_tools=False)
    result = review_pr(pr, cfg, client, repo_root=str(FIX))
    assert not result.would_post
    skipped_names = {n for n, _ in result.skipped}
    assert "package-lock.json" in skipped_names


def test_finding_on_non_added_line_is_dropped():
    pr = _load("pr_injected_bug.json")
    # Line 1 is (almost certainly) not an added line in this hunk.
    finding = {
        "path": "src/cache.py", "line": 1, "category": "bug", "severity": "major",
        "confidence": 0.95, "title": "x", "body": "y", "evidence": "z",
    }
    client = make_mock_client(review_findings=[finding], critic_keep=True)
    cfg = Config(cross_file_pass=False, use_context_tools=False)
    result = review_pr(pr, cfg, client, repo_root=str(FIX))
    assert not result.would_post  # dropped because line 1 was not added


def test_critic_rejection_suppresses_finding():
    pr = _load("pr_injected_bug.json")
    path, line = _an_added_line(pr)
    finding = {
        "path": path, "line": line, "category": "bug", "severity": "major",
        "confidence": 0.9, "title": "t", "body": "b", "evidence": "e",
    }
    client = make_mock_client(review_findings=[finding], critic_keep=False)
    cfg = Config(cross_file_pass=False, use_context_tools=False)
    result = review_pr(pr, cfg, client, repo_root=str(FIX))
    assert not result.would_post
    assert any(r.stage == "critic" for r in result.filter_result.rejections)


def test_summary_mentions_skipped_files():
    pr = _load("pr_clean.json")
    client = make_mock_client(review_findings=[])
    cfg = Config(cross_file_pass=False, use_context_tools=False)
    result = review_pr(pr, cfg, client, repo_root=str(FIX))
    assert "nothing worth flagging" in result.summary
