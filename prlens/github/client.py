"""Thin GitHub REST client with pagination and rate-limit backoff.

Rate limit is 5,000 requests/hour authenticated, but Actions tokens share a pool
per repository, so every method here is written to be frugal.
"""

from __future__ import annotations

import time

import requests

API = "https://api.github.com"


class GitHub:
    def __init__(self, token: str, session: requests.Session | None = None, api: str = API):
        self.api = api
        self.s = session or requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "prlens-review-agent",
            }
        )

    # --------------------------------------------------------------- internals
    def _get(self, path: str, **kw) -> requests.Response:
        r = self.s.get(f"{self.api}{path}", **kw)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            time.sleep(max(0, reset - time.time()) + 1)
            r = self.s.get(f"{self.api}{path}", **kw)
        r.raise_for_status()
        return r

    def _post(self, path: str, **kw) -> requests.Response:
        return self.s.post(f"{self.api}{path}", **kw)

    # ----------------------------------------------------------------- reads
    def pr(self, owner: str, repo: str, number: int) -> dict:
        return self._get(f"/repos/{owner}/{repo}/pulls/{number}").json()

    def pr_files(self, owner: str, repo: str, number: int) -> list[dict]:
        """Paginated. Caps at 300 files server-side; ``patch`` omitted for huge files."""
        out: list[dict] = []
        page = 1
        while True:
            batch = self._get(
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            ).json()
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1
            if page > 3:  # 300-file ceiling; stop paging past it.
                return out

    def pr_diff(self, owner: str, repo: str, number: int) -> str:
        r = self._get(
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        return r.text

    def pr_commits(self, owner: str, repo: str, number: int) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            batch = self._get(
                f"/repos/{owner}/{repo}/pulls/{number}/commits",
                params={"per_page": 100, "page": page},
            ).json()
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    def existing_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            batch = self._get(
                f"/repos/{owner}/{repo}/pulls/{number}/comments",
                params={"per_page": 100, "page": page},
            ).json()
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    def commit_files(self, owner: str, repo: str, sha: str) -> list[dict]:
        return self._get(f"/repos/{owner}/{repo}/commits/{sha}").json().get("files", [])

    # ----------------------------------------------------------------- writes
    def post_review(self, owner: str, repo: str, number: int, payload: dict) -> requests.Response:
        return self._post(f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload)
