#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any


def gh_text(args: list[str]) -> str:
    result = subprocess.run(["gh", *args], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"gh {' '.join(args)} failed")
    return result.stdout


def gh_json(args: list[str]) -> Any:
    return json.loads(gh_text(args) or "null")


def issue_metadata(repo: str, issue_number: int) -> dict[str, Any]:
    payload = gh_json(["issue", "view", str(issue_number), "--repo", repo, "--json", "title,body,comments,state,labels"])
    assert isinstance(payload, dict)
    return payload


def ensure_open(repo: str, issue_number: int) -> dict[str, Any]:
    payload = issue_metadata(repo, issue_number)
    state = payload.get("state") or ""
    labels = [label.get("name", "") for label in payload.get("labels", [])]
    if state != "OPEN":
        raise RuntimeError(f"Issue #{issue_number} is not open (state: {state})")
    if "do-not-automate" in labels:
        raise RuntimeError(f"Issue #{issue_number} has do-not-automate label")
    return payload


def issue_list(repo: str, state: str, limit: int, fields: str) -> Any:
    return gh_json(["issue", "list", "--repo", repo, "--state", state, "--limit", str(limit), "--json", fields])


def pr_list(repo: str, state: str, limit: int, fields: str, search: str = "", jq_expr: str = "") -> Any:
    cmd = ["pr", "list", "--repo", repo, "--state", state, "--limit", str(limit), "--json", fields]
    if search:
        cmd.extend(["--search", search])
    if jq_expr:
        cmd.extend(["--jq", jq_expr])
        return json.loads(gh_text(cmd) or "null")
    return gh_json(cmd)


def graphql(query: str, variables: dict[str, str]) -> Any:
    cmd = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd.extend(["-f", f"{key}={value}"])
    return gh_json(cmd)


def discover_design(repo: str, issue_number: int) -> dict[str, Any]:
    issue = issue_metadata(repo, issue_number)
    discussion_url_pattern = r"https://github\.com/[^/]+/[^/]+/discussions/[0-9]+"
    artifact_marker = f"gpa:design-discussion:#{issue_number}"
    existing_url = ""
    discovery_method = ""

    for comment in issue.get("comments", []):
        body = comment.get("body") or ""
        if artifact_marker in body:
            match = re.search(discussion_url_pattern, body)
            if match:
                existing_url = match.group(0)
                discovery_method = "scaffold-marker"
                break

    if not existing_url:
        body = issue.get("body") or ""
        match = re.search(discussion_url_pattern, body)
        if match:
            existing_url = match.group(0)
            discovery_method = "issue-body"

    if not existing_url:
        owned_artifact_marker = f"gpa:owned-artifact:design-discussion:{repo}#{issue_number}"
        search_query = f'repo:{repo} "{owned_artifact_marker}" in:body'
        payload = graphql(
            """
            query($q: String!) {
              search(query: $q, type: DISCUSSION, first: 5) {
                nodes {
                  ... on Discussion {
                    number
                    url
                    body
                  }
                }
              }
            }
            """,
            {"q": search_query},
        )
        for node in (((payload or {}).get("data") or {}).get("search") or {}).get("nodes", []):
            body = node.get("body") or ""
            if owned_artifact_marker in body and node.get("url"):
                existing_url = node["url"]
                discovery_method = "orphan-recovery"
                break

    return {
        "issue_title": issue.get("title") or "",
        "issue_body": issue.get("body") or "",
        "existing_url": existing_url,
        "existing_number": re.search(r"([0-9]+)$", existing_url).group(1) if existing_url and re.search(r"([0-9]+)$", existing_url) else "",
        "discovery_method": discovery_method,
        "artifact_marker": artifact_marker,
    }


def discover_plan(repo: str, issue_number: int) -> dict[str, Any]:
    issue = issue_metadata(repo, issue_number)
    owned_artifact_marker = f"gpa:owned-artifact:impl-plan:{repo}#{issue_number}"
    for comment in issue.get("comments", []):
        body = comment.get("body") or ""
        if owned_artifact_marker in body:
            return {
                "issue_title": issue.get("title") or "",
                "existing_url": comment.get("url") or "",
                "existing_id": comment.get("id") or "",
                "discovery_method": "owned-artifact-marker",
                "status_marker": f"gpa:impl-plan-status:#{issue_number}",
            }
    for comment in issue.get("comments", []):
        body = comment.get("body") or ""
        if re.search(r"^#{1,2}\s+Implementation Plan", body, flags=re.MULTILINE):
            return {
                "issue_title": issue.get("title") or "",
                "existing_url": comment.get("url") or "",
                "existing_id": comment.get("id") or "",
                "discovery_method": "heading-match",
                "status_marker": f"gpa:impl-plan-status:#{issue_number}",
            }
    return {
        "issue_title": issue.get("title") or "",
        "existing_url": "",
        "existing_id": "",
        "discovery_method": "",
        "status_marker": f"gpa:impl-plan-status:#{issue_number}",
    }


def discover_closeout(repo: str, issue_number: int) -> dict[str, Any]:
    issue = issue_metadata(repo, issue_number)
    owned_artifact_marker = f"gpa:owned-artifact:closeout:{repo}#{issue_number}"
    for comment in issue.get("comments", []):
        body = comment.get("body") or ""
        if owned_artifact_marker in body:
            url = comment.get("url") or ""
            comment_id_match = re.search(r"issuecomment-([0-9]+)$", url)
            comment_id = comment_id_match.group(1) if comment_id_match else ""
            return {
                "issue_title": issue.get("title") or "",
                "existing_comment_body": body,
                "existing_comment_id": comment_id,
                "existing_comment_url": url,
                "status_marker": f"gpa:closeout-status:#{issue_number}",
            }
    return {
        "issue_title": issue.get("title") or "",
        "existing_comment_body": "",
        "existing_comment_id": "",
        "existing_comment_url": "",
        "status_marker": f"gpa:closeout-status:#{issue_number}",
    }


def discover_execution(repo: str, issue_number: int) -> dict[str, Any]:
    issue = issue_metadata(repo, issue_number)
    owned_artifact_marker = f"gpa:owned-artifact:execution-bootstrap:{repo}#{issue_number}"
    open_prs = pr_list(repo, "open", 50, "number,body,headRefName") or []
    for pr in open_prs:
        body = pr.get("body") or ""
        if owned_artifact_marker in body:
            return {
                "issue_title": issue.get("title") or "",
                "status_marker": f"gpa:execution-status:#{issue_number}",
                "existing_pr_number": str(pr.get("number") or ""),
                "existing_branch": pr.get("headRefName") or "",
                "existing_pr_url": f"https://github.com/{repo}/pull/{pr.get('number')}",
                "discovery_method": "owned-artifact-marker",
                "reopen_candidate_number": "",
                "reopen_candidate_branch": "",
            }

    merged_prs = pr_list(repo, "merged", 50, "number,body,headRefName") or []
    for pr in merged_prs:
        body = pr.get("body") or ""
        if owned_artifact_marker in body:
            return {
                "issue_title": issue.get("title") or "",
                "status_marker": f"gpa:execution-status:#{issue_number}",
                "existing_pr_number": str(pr.get("number") or ""),
                "existing_branch": pr.get("headRefName") or "",
                "existing_pr_url": f"https://github.com/{repo}/pull/{pr.get('number')}",
                "discovery_method": "owned-artifact-marker",
                "reopen_candidate_number": "",
                "reopen_candidate_branch": "",
            }

    closed_prs = pr_list(repo, "closed", 50, "number,body,headRefName,mergedAt") or []
    for pr in closed_prs:
        body = pr.get("body") or ""
        merged_at = pr.get("mergedAt") or ""
        if merged_at:
            continue
        if owned_artifact_marker in body:
            return {
                "issue_title": issue.get("title") or "",
                "status_marker": f"gpa:execution-status:#{issue_number}",
                "existing_pr_number": "",
                "existing_branch": "",
                "existing_pr_url": "",
                "discovery_method": "",
                "reopen_candidate_number": str(pr.get("number") or ""),
                "reopen_candidate_branch": pr.get("headRefName") or "",
            }

    for pr in open_prs:
        branch = pr.get("headRefName") or ""
        if re.match(rf"^{issue_number}-", branch):
            return {
                "issue_title": issue.get("title") or "",
                "status_marker": f"gpa:execution-status:#{issue_number}",
                "existing_pr_number": str(pr.get("number") or ""),
                "existing_branch": branch,
                "existing_pr_url": f"https://github.com/{repo}/pull/{pr.get('number')}",
                "discovery_method": "branch-pattern-match",
                "reopen_candidate_number": "",
                "reopen_candidate_branch": "",
            }

    return {
        "issue_title": issue.get("title") or "",
        "status_marker": f"gpa:execution-status:#{issue_number}",
        "existing_pr_number": "",
        "existing_branch": "",
        "existing_pr_url": "",
        "discovery_method": "",
        "reopen_candidate_number": "",
        "reopen_candidate_branch": "",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    issue_parser = sub.add_parser("issue-metadata")
    issue_parser.add_argument("--repo", required=True)
    issue_parser.add_argument("--issue-number", type=int, required=True)

    ensure_parser = sub.add_parser("ensure-open")
    ensure_parser.add_argument("--repo", required=True)
    ensure_parser.add_argument("--issue-number", type=int, required=True)

    issue_list_parser = sub.add_parser("issue-list")
    issue_list_parser.add_argument("--repo", required=True)
    issue_list_parser.add_argument("--state", required=True)
    issue_list_parser.add_argument("--limit", type=int, default=200)
    issue_list_parser.add_argument("--json", required=True)

    pr_list_parser = sub.add_parser("pr-list")
    pr_list_parser.add_argument("--repo", required=True)
    pr_list_parser.add_argument("--state", required=True)
    pr_list_parser.add_argument("--limit", type=int, default=50)
    pr_list_parser.add_argument("--json", required=True)
    pr_list_parser.add_argument("--search", default="")
    pr_list_parser.add_argument("--jq", default="")

    design_parser = sub.add_parser("discover-design")
    design_parser.add_argument("--repo", required=True)
    design_parser.add_argument("--issue-number", type=int, required=True)

    plan_parser = sub.add_parser("discover-plan")
    plan_parser.add_argument("--repo", required=True)
    plan_parser.add_argument("--issue-number", type=int, required=True)

    execution_parser = sub.add_parser("discover-execution")
    execution_parser.add_argument("--repo", required=True)
    execution_parser.add_argument("--issue-number", type=int, required=True)

    closeout_parser = sub.add_parser("discover-closeout")
    closeout_parser.add_argument("--repo", required=True)
    closeout_parser.add_argument("--issue-number", type=int, required=True)

    args = parser.parse_args()
    try:
        if args.cmd == "issue-metadata":
            print(json.dumps(issue_metadata(args.repo, args.issue_number)))
        elif args.cmd == "ensure-open":
            print(json.dumps(ensure_open(args.repo, args.issue_number)))
        elif args.cmd == "issue-list":
            print(json.dumps(issue_list(args.repo, args.state, args.limit, args.json)))
        elif args.cmd == "pr-list":
            print(json.dumps(pr_list(args.repo, args.state, args.limit, args.json, args.search, args.jq)))
        elif args.cmd == "discover-design":
            print(json.dumps(discover_design(args.repo, args.issue_number)))
        elif args.cmd == "discover-plan":
            print(json.dumps(discover_plan(args.repo, args.issue_number)))
        elif args.cmd == "discover-execution":
            print(json.dumps(discover_execution(args.repo, args.issue_number)))
        elif args.cmd == "discover-closeout":
            print(json.dumps(discover_closeout(args.repo, args.issue_number)))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
