#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          projectItems(first: 20) {
            nodes {
              id
              project {
                ... on ProjectV2 {
                  id
                  title
                  closed
                }
              }
            }
          }
        }
      }
    }
    """

    result = subprocess.run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo}",
            "-F",
            f"number={args.issue_number}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    nodes = (
        payload.get("data", {})
        .get("repository", {})
        .get("issue", {})
        .get("projectItems", {})
        .get("nodes", [])
    )
    open_nodes = [node for node in nodes if not ((node.get("project") or {}).get("closed"))]
    preferred = [node for node in open_nodes if ((node.get("project") or {}).get("title")) == "Workflow Orchestration"]
    resolved = (preferred or open_nodes or [{}])[0].get("id", "")
    print(resolved)


if __name__ == "__main__":
    main()
