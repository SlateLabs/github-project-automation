#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def gh_graphql(*args: str) -> dict:
    result = subprocess.run(
        ["gh", "api", "graphql", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--target-status", required=True)
    args = parser.parse_args()

    metadata_query = """
    query($itemId: ID!) {
      node(id: $itemId) {
        ... on ProjectV2Item {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
            }
          }
          project {
            ... on ProjectV2 {
              id
              fields(first: 20) {
                nodes {
                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    options {
                      id
                      name
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    metadata = gh_graphql("-f", f"query={metadata_query}", "-F", f"itemId={args.item_id}")
    node = metadata.get("data", {}).get("node") or {}
    project = node.get("project") or {}
    fields = project.get("fields", {}).get("nodes", [])
    field_values = node.get("fieldValues", {}).get("nodes", [])

    status_field = next((field for field in fields if field.get("name") == "Status"), None)
    current_status = next(
        (value.get("name", "") for value in field_values if (value.get("field") or {}).get("name") == "Status"),
        "",
    )
    option = next(
        (option for option in (status_field or {}).get("options", []) if option.get("name") == args.target_status),
        None,
    )

    if not project.get("id") or not status_field or not option:
        raise SystemExit("Could not resolve project metadata for Status synchronization")

    updated = False
    if current_status != args.target_status:
        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
          updateProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
              value: { singleSelectOptionId: $optionId }
            }
          ) {
            projectV2Item {
              id
            }
          }
        }
        """
        gh_graphql(
            "-f",
            f"query={mutation}",
            "-F",
            f"projectId={project['id']}",
            "-F",
            f"itemId={args.item_id}",
            "-F",
            f"fieldId={status_field['id']}",
            "-f",
            f"optionId={option['id']}",
        )
        updated = True

    print(
        json.dumps(
            {
                "updated": updated,
                "current_status": current_status,
                "target_status": args.target_status,
            }
        )
    )


if __name__ == "__main__":
    main()
