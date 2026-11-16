"""Posting the review.

Post ONE review containing all inline comments, never individual comments —
individual comments each generate a separate notification, which is how a reviewer
bot gets uninstalled.

Always use ``event: "COMMENT"``, never ``REQUEST_CHANGES``. A bot that blocks merges
is removed from the repo within a day. That is a product judgment, not a limitation.
"""

from __future__ import annotations

from ..agent.schema import Finding


def render_body(f: Finding) -> str:
    """Render one finding, using a GitHub suggestion block when a concrete fix exists."""
    out = [f"**{f.title}**", "", f.body]
    if f.suggestion:
        out += ["", "```suggestion", f.suggestion.rstrip("\n"), "```"]
    out += [
        "",
        f"<sub>{f.category} · {f.severity} · confidence {f.confidence:.2f} · PRLens</sub>",
    ]
    return "\n".join(out)


def build_payload(findings: list[Finding], summary: str, commit_sha: str) -> dict:
    comments = [
        {"path": f.path, "line": f.line, "side": "RIGHT", "body": render_body(f)}
        for f in findings
    ]
    return {
        "commit_id": commit_sha,
        "body": summary,
        "event": "COMMENT",  # never REQUEST_CHANGES — a blocking bot gets uninstalled
        "comments": comments,
    }


def _identify_invalid(error_json: dict, comments: list[dict]) -> list[dict]:
    """Best-effort extraction of which comments the API rejected as out-of-diff.

    GitHub's 422 body varies; when it names offending fields we drop those, otherwise
    we conservatively drop nothing here and let the caller retry without comments.
    """
    msg = (error_json or {}).get("message", "").lower()
    errors = (error_json or {}).get("errors", []) or []
    bad: list[dict] = []
    # Some responses enumerate errors with an index or path/line; match what we can.
    for err in errors:
        path = err.get("path") if isinstance(err, dict) else None
        line = err.get("line") if isinstance(err, dict) else None
        for c in comments:
            if path and c["path"] == path and (line is None or c["line"] == line):
                bad.append(c)
    if not bad and "line must be part of the diff" in msg:
        # We cannot tell which one; signal caller to retry comment-free.
        return list(comments)
    return bad


def post_review(gh, owner, repo, number, findings, summary, commit_sha) -> dict:
    """Post a single review; on a 422 drop the un-anchorable comments and retry once."""
    payload = build_payload(findings, summary, commit_sha)
    r = gh.post_review(owner, repo, number, payload)

    if r.status_code == 422:
        try:
            err = r.json()
        except ValueError:
            err = {}
        bad = _identify_invalid(err, payload["comments"])
        kept = [c for c in payload["comments"] if c not in bad]
        payload["comments"] = kept
        note = f"\n\n_{len(bad)} finding(s) could not be anchored to the diff._"
        payload["body"] = (payload["body"] or "") + note
        r = gh.post_review(owner, repo, number, payload)

    r.raise_for_status()
    return r.json() if r.content else {}
