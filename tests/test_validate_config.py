"""Tests for scripts/validate-config.py."""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path

import pytest

# The module filename has a hyphen, so we import it dynamically.
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "validate-config.py"


def _import_validate_config():
    """Import the validate-config module despite the hyphenated filename."""
    spec = importlib.util.spec_from_file_location("validate_config", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vc = _import_validate_config()


@pytest.fixture(autouse=True)
def _reset_errors():
    """Clear the module-level errors list before each test."""
    vc.errors.clear()
    yield
    vc.errors.clear()


# ---------------------------------------------------------------------------
# validate_trust_policy
# ---------------------------------------------------------------------------


class TestValidateTrustPolicy:
    def test_valid_trust_policy(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "trust-policy.yml").write_text(textwrap.dedent("""\
            trusted_teams:
              - core-team
            trusted_users:
              - alice
            trusted_apps:
              - my-bot
            record_only_roles:
              - viewer
            deny_roles:
              - blocked
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_trust_policy()
        assert vc.errors == []

    def test_missing_file(self, tmp_path, monkeypatch):
        (tmp_path / "config").mkdir()
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_trust_policy()
        assert any("file not found" in e for e in vc.errors)

    def test_missing_keys(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "trust-policy.yml").write_text(textwrap.dedent("""\
            trusted_teams:
              - core-team
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_trust_policy()
        assert any("missing required keys" in e for e in vc.errors)

    def test_wrong_type(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "trust-policy.yml").write_text(textwrap.dedent("""\
            trusted_teams: not-a-list
            trusted_users: not-a-list
            trusted_apps: not-a-list
            record_only_roles: not-a-list
            deny_roles: not-a-list
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_trust_policy()
        assert any("must be a list" in e for e in vc.errors)

    def test_root_not_mapping(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "trust-policy.yml").write_text("- item\n")
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_trust_policy()
        assert any("root must be a mapping" in e for e in vc.errors)


# ---------------------------------------------------------------------------
# validate_repos_config
# ---------------------------------------------------------------------------


class TestValidateReposConfig:
    def test_valid_repos(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "repos.yml").write_text(textwrap.dedent("""\
            repos:
              - repo: org/my-repo
                enabled_stages:
                  - design
                  - plan
                shared_workflow_version: main
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_repos_config()
        assert vc.errors == []

    def test_missing_file(self, tmp_path, monkeypatch):
        (tmp_path / "config").mkdir()
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_repos_config()
        assert any("file not found" in e for e in vc.errors)

    def test_missing_repos_key(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "repos.yml").write_text("other_key: true\n")
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_repos_config()
        assert any("missing required key: repos" in e for e in vc.errors)

    def test_repos_not_list(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "repos.yml").write_text("repos: not-a-list\n")
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_repos_config()
        assert any("must be a non-empty list" in e for e in vc.errors)

    def test_entry_missing_required_key(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "repos.yml").write_text(textwrap.dedent("""\
            repos:
              - repo: org/my-repo
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_repos_config()
        assert any("missing required key" in e for e in vc.errors)

    def test_enabled_stages_wrong_type(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "repos.yml").write_text(textwrap.dedent("""\
            repos:
              - repo: org/my-repo
                enabled_stages: not-a-list
                shared_workflow_version: main
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_repos_config()
        assert any("enabled_stages" in e and "must be a list" in e for e in vc.errors)


# ---------------------------------------------------------------------------
# validate_templates
# ---------------------------------------------------------------------------


class TestValidateTemplates:
    def test_valid_template(self, tmp_path, monkeypatch):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "design-discussion.md").write_text(textwrap.dedent("""\
            ## Summary
            ## Problem
            ## Goals
            ## Non-goals
            ## Proposed Approach
            ## Open Questions
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_templates()
        assert vc.errors == []

    def test_missing_template_file(self, tmp_path, monkeypatch):
        (tmp_path / "templates").mkdir()
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_templates()
        assert any("file not found" in e for e in vc.errors)

    def test_missing_headings(self, tmp_path, monkeypatch):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "design-discussion.md").write_text("## Summary\n## Problem\n")
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_templates()
        assert any("missing required headings" in e for e in vc.errors)


# ---------------------------------------------------------------------------
# validate_plan_template
# ---------------------------------------------------------------------------


class TestValidatePlanTemplate:
    def test_valid_plan_template(self, tmp_path, monkeypatch):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "implementation-plan.md").write_text(textwrap.dedent("""\
            ## Implementation Plan
            ## Acceptance Criteria
            ## Verification Plan
            ## Review Expectations
            ## Slices
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_plan_template()
        assert vc.errors == []

    def test_missing_plan_file(self, tmp_path, monkeypatch):
        (tmp_path / "templates").mkdir()
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_plan_template()
        assert any("file not found" in e for e in vc.errors)

    def test_missing_plan_headings(self, tmp_path, monkeypatch):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "implementation-plan.md").write_text("## Implementation Plan\n")
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_plan_template()
        assert any("missing required headings" in e for e in vc.errors)


# ---------------------------------------------------------------------------
# validate_execution_template
# ---------------------------------------------------------------------------


class TestValidateExecutionTemplate:
    def test_valid_execution_template(self, tmp_path, monkeypatch):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "execution-bootstrap.md").write_text(textwrap.dedent("""\
            ## Summary
            ## Test plan
            ## Review Checklist
        """))
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_execution_template()
        assert vc.errors == []

    def test_missing_execution_file(self, tmp_path, monkeypatch):
        (tmp_path / "templates").mkdir()
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_execution_template()
        assert any("file not found" in e for e in vc.errors)

    def test_missing_execution_headings(self, tmp_path, monkeypatch):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "execution-bootstrap.md").write_text("## Summary\n")
        monkeypatch.setattr(vc, "REPO_ROOT", tmp_path)
        vc.validate_execution_template()
        assert any("missing required headings" in e for e in vc.errors)
