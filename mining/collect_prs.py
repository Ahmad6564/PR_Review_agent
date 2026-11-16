"""Phase 7, Route A — collect merged PRs with review comments via the GitHub API.

Pick 15-30 active, well-reviewed open source repos across several languages, and pull
their merged PRs from the last year that have at least one review comment. A few
thousand PRs is plenty; we keep the interesting ones and hydrate them with the data
the benchmark needs.

This is the route that definitely works on a Tuesday night. Route B (GH Archive on
BigQuery) is documented in docs/design-decisions.md as the big-data enhancement.

Usage:
    python -m mining.collect_prs --repos org/a org/b --per-repo 100 --out mining/raw.jsonl
Requires GITHUB_TOKEN in the environment (5,000 req/hour authenticated).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from prlens.github.client import GitHub


def _search_merged_prs(gh: GitHub, repo: str, limit: int) -> list[dict]:
    """Use the search API to find merged PRs with review activity."""
    owner, name = repo.split("/", 1)
    out: list[dict] = []
    page = 1
    while len(out) < limit:
        q = f"repo:{repo} is:pr is:merged review:approved"
        resp = gh._get(
            "/search/issues",
            params={"q": q, "per_page": 50, "page": page, "sort": "updated"},
        ).json()
        items = resp.get("items", [])
        if not items:
            break
        out.extend(items)
        if len(items) < 50:
            break
        page += 1
        if page > 10:
            break
    return out[:limit]


def collect_repo(gh: GitHub, repo: str, per_repo: int) -> list[dict]:
    owner, name = repo.split("/", 1)
    records: list[dict] = []
    for item in _search_merged_prs(gh, repo, per_repo):
        number = item["number"]
        try:
            comments = gh.existing_comments(owner, name, number)
            if not comments:
                continue
            pr = gh.pr(owner, name, number)
            files = gh.pr_files(owner, name, number)
            commits = gh.pr_commits(owner, name, number)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {repo}#{number}: {e}", file=sys.stderr)
            continue

        records.append(
            {
                "repo": repo,
                "pr": number,
                "head_sha": pr.get("head", {}).get("sha", ""),
                "title": pr.get("title", ""),
                "body": pr.get("body", "") or "",
                "merged": pr.get("merged", False),
                "review_comments": [
                    {
                        "path": c.get("path"),
                        "line": c.get("line") or c.get("original_line"),
                        "body": c.get("body", ""),
                        "created_at": c.get("created_at"),
                        "user": (c.get("user") or {}).get("login"),
                    }
                    for c in comments
                ],
                "files": [
                    {
                        "filename": f["filename"],
                        "status": f.get("status"),
                        "patch": f.get("patch"),
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                    }
                    for f in files
                ],
                "commits": [
                    {
                        "sha": c.get("sha"),
                        "date": (c.get("commit", {}).get("author", {}) or {}).get("date"),
                    }
                    for c in commits
                ],
            }
        )
    return records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect merged PRs with review comments")
    ap.add_argument("--repos", nargs="+", required=True, help="owner/name repos to mine")
    ap.add_argument("--per-repo", type=int, default=100)
    ap.add_argument("--out", default="mining/raw.jsonl")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: set GITHUB_TOKEN", file=sys.stderr)
        return 2
    gh = GitHub(token)

    n = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        for repo in args.repos:
            print(f"Collecting {repo} ...", file=sys.stderr)
            for rec in collect_repo(gh, repo, args.per_repo):
                fh.write(json.dumps(rec) + "\n")
                n += 1
    print(f"Wrote {n} PR records to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
