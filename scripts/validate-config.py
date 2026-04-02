#!/usr/bin/env python3
"""Validate config/trust-policy.yml and config/repos.yml structure.

Requires PyYAML. On GitHub Actions runners, PyYAML is pre-installed.
For local use: pip install pyyaml (or run via the CI workflow).

Exit code 0 = valid, non-zero = invalid.
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    print("  (PyYAML is pre-installed on GitHub Actions runners)", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
errors = []


def validate_trust_policy():
    path = REPO_ROOT / "config" / "trust-policy.yml"
    if not path.exists():
        errors.append(f"trust-policy.yml: file not found at {path}")
        return

    with open(path) as f:
        doc = yaml.safe_load(f)

    if not isinstance(doc, dict):
        errors.append("trust-policy.yml: root must be a mapping")
        return

    required_keys = [
        "trusted_teams",
        "trusted_users",
        "trusted_apps",
        "record_only_roles",
        "deny_roles",
    ]
    missing = [k for k in required_keys if k not in doc]
    if missing:
        errors.append(f"trust-policy.yml: missing required keys: {missing}")
        return

    for key in required_keys:
        val = doc[key]
        if not isinstance(val, list):
            errors.append(
                f'trust-policy.yml: key "{key}" must be a list, got {type(val).__name__}'
            )

    if not errors:
        print("trust-policy.yml: OK")


def validate_repos_config():
    path = REPO_ROOT / "config" / "repos.yml"
    if not path.exists():
        errors.append(f"repos.yml: file not found at {path}")
        return

    with open(path) as f:
        doc = yaml.safe_load(f)

    if not isinstance(doc, dict):
        errors.append("repos.yml: root must be a mapping")
        return

    if "repos" not in doc:
        errors.append("repos.yml: missing required key: repos")
        return

    repos = doc["repos"]
    if not isinstance(repos, list) or len(repos) == 0:
        errors.append('repos.yml: "repos" must be a non-empty list')
        return

    for i, entry in enumerate(repos):
        if not isinstance(entry, dict):
            errors.append(f"repos.yml: entry {i} must be a mapping")
            continue
        for req in ["repo", "enabled_stages", "shared_workflow_version"]:
            if req not in entry:
                errors.append(f'repos.yml: entry {i} missing required key: "{req}"')
        if "enabled_stages" in entry and not isinstance(entry["enabled_stages"], list):
            errors.append(f'repos.yml: entry {i} "enabled_stages" must be a list')

    if not errors:
        print("repos.yml: OK")


def validate_templates():
    """Validate that required templates exist and contain expected headings."""
    design_template = REPO_ROOT / "templates" / "design-discussion.md"
    if not design_template.exists():
        errors.append(f"templates/design-discussion.md: file not found at {design_template}")
        return

    content = design_template.read_text()

    # Required headings per discussion #3 §4 (design gate)
    required_headings = [
        "## Summary",
        "## Problem",
        "## Goals",
        "## Non-goals",
        "## Proposed Approach",
        "## Open Questions",
    ]
    missing = [h for h in required_headings if h not in content]
    if missing:
        errors.append(
            f"templates/design-discussion.md: missing required headings: {missing}"
        )
        return

    print("templates/design-discussion.md: OK")


def main():
    print("Validating configuration files...\n")

    validate_trust_policy()
    validate_repos_config()
    validate_templates()

    print()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(f"\nFAILED: {len(errors)} error(s) found")
        return 1
    else:
        print("All config files valid.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
