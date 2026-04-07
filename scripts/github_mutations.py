#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def issue_comment(repo: str, issue_number: str, body: str) -> None:
    run(["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body])


def issue_comment_file(repo: str, issue_number: str, body_file: str) -> None:
    run(["gh", "issue", "comment", issue_number, "--repo", repo, "--body-file", body_file])


def issue_edit_body(repo: str, issue_number: str, body_file: str) -> None:
    run(["gh", "issue", "edit", issue_number, "--repo", repo, "--body-file", body_file])


def pr_merge(repo: str, pr_number: str) -> None:
    run(["gh", "pr", "merge", pr_number, "--repo", repo, "--squash", "--delete-branch"])


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    comment = sub.add_parser("issue-comment")
    comment.add_argument("--repo", required=True)
    comment.add_argument("--issue-number", required=True)
    comment.add_argument("--body", required=True)

    comment_file = sub.add_parser("issue-comment-file")
    comment_file.add_argument("--repo", required=True)
    comment_file.add_argument("--issue-number", required=True)
    comment_file.add_argument("--body-file", required=True)

    edit = sub.add_parser("issue-edit-body")
    edit.add_argument("--repo", required=True)
    edit.add_argument("--issue-number", required=True)
    edit.add_argument("--body-file", required=True)

    merge = sub.add_parser("pr-merge")
    merge.add_argument("--repo", required=True)
    merge.add_argument("--pr-number", required=True)

    args = parser.parse_args()
    if args.cmd == "issue-comment":
        issue_comment(args.repo, args.issue_number, args.body)
    elif args.cmd == "issue-comment-file":
        issue_comment_file(args.repo, args.issue_number, args.body_file)
    elif args.cmd == "issue-edit-body":
        issue_edit_body(args.repo, args.issue_number, args.body_file)
    elif args.cmd == "pr-merge":
        pr_merge(args.repo, args.pr_number)
    else:
        raise SystemExit(1)
