#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"command failed with exit code {result.returncode}"
        raise RuntimeError(detail)
    return stdout


def issue_comment(repo: str, issue_number: str, body: str) -> str:
    return run(["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body])


def issue_comment_file(repo: str, issue_number: str, body_file: str) -> str:
    return run(["gh", "issue", "comment", issue_number, "--repo", repo, "--body-file", body_file])


def issue_edit_body(repo: str, issue_number: str, body_file: str) -> None:
    run(["gh", "issue", "edit", issue_number, "--repo", repo, "--body-file", body_file])


def issue_create(repo: str, title: str, body: str, labels: list[str]) -> str:
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    return run(cmd)


def pr_merge(repo: str, pr_number: str) -> None:
    run(["gh", "pr", "merge", pr_number, "--repo", repo, "--squash", "--delete-branch"])


def pr_reopen(repo: str, pr_number: str) -> str:
    return run(["gh", "api", f"repos/{repo}/pulls/{pr_number}", "--method", "PATCH", "-f", "state=open"])


def create_ref(repo: str, ref: str, sha: str) -> str:
    return run(["gh", "api", f"repos/{repo}/git/refs", "-f", f"ref={ref}", "-f", f"sha={sha}"])


def create_draft_pr(repo: str, title: str, head: str, base: str, body: str) -> str:
    return run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls",
            "-f",
            f"title={title}",
            "-f",
            f"head={head}",
            "-f",
            f"base={base}",
            "-f",
            f"body={body}",
            "-F",
            "draft=true",
        ]
    )


def discussion_create(repo_id: str, category_id: str, title: str, body: str) -> str:
    return run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            (
                "query=\n"
                "mutation($repoId: ID!, $categoryId: ID!, $title: String!, $body: String!) {\n"
                "  createDiscussion(input: {\n"
                "    repositoryId: $repoId,\n"
                "    categoryId: $categoryId,\n"
                "    title: $title,\n"
                "    body: $body\n"
                "  }) {\n"
                "    discussion {\n"
                "      id\n"
                "      number\n"
                "      url\n"
                "    }\n"
                "  }\n"
                "}\n"
            ),
            "-f",
            f"repoId={repo_id}",
            "-f",
            f"categoryId={category_id}",
            "-f",
            f"title={title}",
            "-f",
            f"body={body}",
        ]
    )


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

    issue_create_parser = sub.add_parser("issue-create")
    issue_create_parser.add_argument("--repo", required=True)
    issue_create_parser.add_argument("--title", required=True)
    issue_create_parser.add_argument("--body", required=True)
    issue_create_parser.add_argument("--label", action="append", default=[])

    merge = sub.add_parser("pr-merge")
    merge.add_argument("--repo", required=True)
    merge.add_argument("--pr-number", required=True)

    reopen = sub.add_parser("pr-reopen")
    reopen.add_argument("--repo", required=True)
    reopen.add_argument("--pr-number", required=True)

    ref_parser = sub.add_parser("create-ref")
    ref_parser.add_argument("--repo", required=True)
    ref_parser.add_argument("--ref", required=True)
    ref_parser.add_argument("--sha", required=True)

    draft_pr = sub.add_parser("create-draft-pr")
    draft_pr.add_argument("--repo", required=True)
    draft_pr.add_argument("--title", required=True)
    draft_pr.add_argument("--head", required=True)
    draft_pr.add_argument("--base", required=True)
    draft_pr.add_argument("--body", required=True)

    discussion = sub.add_parser("discussion-create")
    discussion.add_argument("--repo-id", required=True)
    discussion.add_argument("--category-id", required=True)
    discussion.add_argument("--title", required=True)
    discussion.add_argument("--body", required=True)

    args = parser.parse_args()

    try:
        if args.cmd == "issue-comment":
            print(issue_comment(args.repo, args.issue_number, args.body))
        elif args.cmd == "issue-comment-file":
            print(issue_comment_file(args.repo, args.issue_number, args.body_file))
        elif args.cmd == "issue-edit-body":
            issue_edit_body(args.repo, args.issue_number, args.body_file)
        elif args.cmd == "issue-create":
            print(issue_create(args.repo, args.title, args.body, args.label))
        elif args.cmd == "pr-merge":
            pr_merge(args.repo, args.pr_number)
        elif args.cmd == "pr-reopen":
            print(pr_reopen(args.repo, args.pr_number))
        elif args.cmd == "create-ref":
            print(create_ref(args.repo, args.ref, args.sha))
        elif args.cmd == "create-draft-pr":
            print(create_draft_pr(args.repo, args.title, args.head, args.base, args.body))
        elif args.cmd == "discussion-create":
            print(discussion_create(args.repo_id, args.category_id, args.title, args.body))
        else:
            raise SystemExit(1)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
