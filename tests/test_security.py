"""Prompt-injection resistance at the message-construction layer.

We verify the structural defence: all PR-derived text is wrapped in a delimited
untrusted block and the system/user framing states it is data, not instructions.
"""

import json
from pathlib import Path

from prlens.agent.reviewer import UNTRUSTED_HEADER, _hunk_user_message
from prlens.config import Config
from prlens.engine import PRData, review_pr
from prlens.github.diff import parse_pr_files
from tests.helpers import make_mock_client

FIX = Path(__file__).parent / "fixtures"


def test_hunk_message_wraps_untrusted_content():
    pr = json.loads((FIX / "pr_injection_attempt.json").read_text(encoding="utf-8"))
    by_file = parse_pr_files(pr["files"])
    hunk = next(iter(by_file.values()))[0]
    msg = _hunk_user_message(hunk, pr["title"], pr["body"])
    assert "<untrusted_pr_content>" in msg
    assert "</untrusted_pr_content>" in msg
    assert UNTRUSTED_HEADER in msg
    # The injected instruction text lives strictly inside the untrusted data block
    # (the last <untrusted_pr_content> tag; the header merely names the tag).
    inner = msg.rsplit("<untrusted_pr_content>", 1)[1]
    assert "Ignore all previous instructions" in inner


def test_injection_pr_does_not_force_empty_review():
    """The engine's control flow is driven by the schema, not by diff text.

    Here the model (mock) still reports a real finding despite the injected
    'respond with empty review' instruction, demonstrating the framing holds.
    """
    pr = PRData.from_fixture(
        json.loads((FIX / "pr_injection_attempt.json").read_text(encoding="utf-8"))
    )
    by_file = parse_pr_files(pr.files)
    hunk = next(iter(by_file.values()))[0]
    line = sorted(hunk.added_lines)[0]
    finding = {
        "path": "src/auth.py", "line": line, "category": "security", "severity": "major",
        "confidence": 0.85, "title": "Non-constant-time compare",
        "body": "Token compared with == which is timing-unsafe.", "evidence": "provided == expected",
    }
    client = make_mock_client(review_findings=[finding], critic_keep=True)
    cfg = Config(cross_file_pass=False, use_context_tools=False, categories=["security", "bug"])
    result = review_pr(pr, cfg, client, repo_root=str(FIX))
    assert result.would_post  # the injection did not suppress the review
