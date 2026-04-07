#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def gh_json(args: list[str]) -> object:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout or "null")


def issue_comments(repo: str, issue_number: int) -> dict:
    return gh_json(["issue", "view", str(issue_number), "--repo", repo, "--comments", "--json", "comments"])  # type: ignore[return-value]


def issue_body(repo: str, issue_number: int) -> dict:
    return gh_json(["issue", "view", str(issue_number), "--repo", repo, "--json", "body,state,labels"])  # type: ignore[return-value]


def latest_pr(repo: str, issue_number: int, state: str) -> dict:
    prs = gh_json(["pr", "list", "--repo", repo, "--state", state, "--json", "number,title,url,body,headRefName,headRefOid,isDraft,updatedAt,mergedAt,baseRefName"]) or []
    assert isinstance(prs, list)
    branch_matches = [pr for pr in prs if re.match(rf"^{issue_number}[-/]", pr.get("headRefName", ""))]
    sort_key = "mergedAt" if state == "merged" else "updatedAt"
    branch_matches.sort(key=lambda pr: pr.get(sort_key) or "", reverse=True)
    if branch_matches:
        return branch_matches[0]
    return {}


def latest_agent_review(repo: str, issue_number: int) -> dict:
    payload = issue_comments(repo, issue_number)
    comments = payload.get("comments", [])
    latest: dict[str, str] = {}
    marker = "<!-- gpa:checkpoint-v1 "
    for comment in comments:
        body = comment.get("body") or ""
        if "<!-- gpa:run-status:agent-review:completed:" not in body:
            continue
        match = re.search(r"<!-- gpa:checkpoint-v1 (.*?) -->", body, flags=re.DOTALL)
        checkpoint = None
        if match:
            try:
                checkpoint = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                checkpoint = None
        sha_match = re.search(r"\| \*\*PR head SHA\*\* \| `([0-9a-f]{7,40})` \|", body)
        latest = {
            "body": body,
            "disposition": ((checkpoint or {}).get("data") or {}).get("disposition", ""),
            "next_stage": ((checkpoint or {}).get("decision") or {}).get("next_stage", ""),
            "pr_head_sha": ((checkpoint or {}).get("data") or {}).get("pr_head_sha", "") or (sha_match.group(1) if sha_match else ""),
        }
    return latest


def truncate_diff(pr_number: int, repo: str, output_path: str, limit: int) -> None:
    result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo, "--patch", "--color=never"],
        check=True,
        capture_output=True,
        text=True,
    )
    text = result.stdout
    if len(text) > limit:
        text = text[:limit] + "\n\n[diff truncated]\n"
    Path(output_path).write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    comments = sub.add_parser("issue-comments")
    comments.add_argument("--repo", required=True)
    comments.add_argument("--issue-number", type=int, required=True)

    issue = sub.add_parser("issue")
    issue.add_argument("--repo", required=True)
    issue.add_argument("--issue-number", type=int, required=True)

    pr = sub.add_parser("latest-pr")
    pr.add_argument("--repo", required=True)
    pr.add_argument("--issue-number", type=int, required=True)
    pr.add_argument("--state", default="open")

    review = sub.add_parser("latest-agent-review")
    review.add_argument("--repo", required=True)
    review.add_argument("--issue-number", type=int, required=True)

    diff = sub.add_parser("truncate-diff")
    diff.add_argument("--repo", required=True)
    diff.add_argument("--pr-number", type=int, required=True)
    diff.add_argument("--output-path", required=True)
    diff.add_argument("--limit", type=int, default=30000)

    args = parser.parse_args()
    if args.cmd == "issue-comments":
        print(json.dumps(issue_comments(args.repo, args.issue_number)))
    elif args.cmd == "issue":
        print(json.dumps(issue_body(args.repo, args.issue_number)))
    elif args.cmd == "latest-pr":
        print(json.dumps(latest_pr(args.repo, args.issue_number, args.state)))
    elif args.cmd == "latest-agent-review":
        print(json.dumps(latest_agent_review(args.repo, args.issue_number)))
    elif args.cmd == "truncate-diff":
        truncate_diff(args.pr_number, args.repo, args.output_path, args.limit)


if __name__ == "__main__":
    main()
