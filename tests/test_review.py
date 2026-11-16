from prlens.agent.schema import Finding
from prlens.github.review import build_payload, post_review, render_body


def _f(**kw):
    base = dict(
        path="src/x.py", line=10, category="bug", severity="major",
        confidence=0.82, title="Off-by-one", body="Loop runs one time too many.",
        evidence="range(len(x)+1)",
    )
    base.update(kw)
    return Finding(**base)


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeGH:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_review(self, owner, repo, number, payload):
        self.calls.append(payload)
        return self.responses.pop(0)


def test_render_body_includes_suggestion_and_footer():
    body = render_body(_f(suggestion="for i in range(len(x)):"))
    assert "```suggestion" in body
    assert "PRLens" in body
    assert "**Off-by-one**" in body


def test_build_payload_uses_comment_event():
    payload = build_payload([_f()], "summary", "sha123")
    assert payload["event"] == "COMMENT"
    assert payload["comments"][0]["side"] == "RIGHT"
    assert payload["commit_id"] == "sha123"


def test_post_review_success():
    gh = FakeGH([FakeResp(200, {})])
    post_review(gh, "o", "r", 1, [_f()], "s", "sha")
    assert len(gh.calls) == 1


def test_post_review_422_retry_drops_bad_comment():
    # First call 422 naming the offending line, second succeeds.
    err = {"message": "validation failed", "errors": [{"path": "src/x.py", "line": 10}]}
    gh = FakeGH([FakeResp(422, err), FakeResp(200, {})])
    post_review(gh, "o", "r", 1, [_f(line=10), _f(line=11, title="Other")], "s", "sha")
    assert len(gh.calls) == 2
    # The retry payload should have dropped the line-10 comment.
    retry_lines = [c["line"] for c in gh.calls[1]["comments"]]
    assert 10 not in retry_lines and 11 in retry_lines
    assert "could not be anchored" in gh.calls[1]["body"]
