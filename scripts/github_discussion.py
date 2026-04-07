#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_gh(args: list[str]) -> dict:
    result = subprocess.run(
        ["gh", "api", "graphql", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def get_discussion(repo: str, number: int, with_comments: bool) -> None:
    owner, name = repo.split("/", 1)
    comments_fragment = ""
    if with_comments:
        comments_fragment = """
            comments(first: 20) {
              nodes {
                body
              }
            }
        """

    query = f"""
    query($owner: String!, $name: String!, $number: Int!) {{
      repository(owner: $owner, name: $name) {{
        discussion(number: $number) {{
          id
          body
          {comments_fragment}
        }}
      }}
    }}
    """
    payload = run_gh(
        [
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
    )
    discussion = payload.get("data", {}).get("repository", {}).get("discussion") or {}
    print(json.dumps(discussion))


def update_body(discussion_id: str, body_file: str) -> None:
    mutation = """
    mutation($discussionId: ID!, $body: String!) {
      updateDiscussion(input: {discussionId: $discussionId, body: $body}) {
        discussion {
          id
        }
      }
    }
    """
    run_gh(
        [
            "-f",
            f"query={mutation}",
            "-F",
            f"discussionId={discussion_id}",
            "-f",
            f"body={Path(body_file).read_text()}",
        ]
    )


def add_comment(discussion_id: str, body_file: str) -> None:
    mutation = """
    mutation($discussionId: ID!, $body: String!) {
      addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
        comment {
          id
        }
      }
    }
    """
    run_gh(
        [
            "-f",
            f"query={mutation}",
            "-F",
            f"discussionId={discussion_id}",
            "-f",
            f"body={Path(body_file).read_text()}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--repo", required=True)
    get_parser.add_argument("--number", type=int, required=True)
    get_parser.add_argument("--with-comments", action="store_true")

    update_parser = subparsers.add_parser("update-body")
    update_parser.add_argument("--discussion-id", required=True)
    update_parser.add_argument("--body-file", required=True)

    comment_parser = subparsers.add_parser("add-comment")
    comment_parser.add_argument("--discussion-id", required=True)
    comment_parser.add_argument("--body-file", required=True)

    args = parser.parse_args()
    if args.cmd == "get":
        get_discussion(args.repo, args.number, args.with_comments)
    elif args.cmd == "update-body":
        update_body(args.discussion_id, args.body_file)
    elif args.cmd == "add-comment":
        add_comment(args.discussion_id, args.body_file)
    else:
        raise SystemExit(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
