"""Tests for scripts/render_comments/ templates."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from render_comments.common import e, status_template
from render_comments.orchestration import (
    duplicate,
    gate_failed,
    next_stage_queued,
    stage_transition,
)
from render_comments.scaffolds import (
    closeout_scaffold_created,
    closeout_scaffold_exists,
    design_scaffold_created,
    design_scaffold_exists,
    execution_scaffold_created,
    plan_scaffold_created,
)
from render_comments import TEMPLATES


@pytest.fixture(autouse=True)
def _common_env(monkeypatch):
    """Set env vars referenced by most templates."""
    monkeypatch.setenv("RUN_KEY", "abc123")
    monkeypatch.setenv("REQUESTED_STAGE", "design")
    monkeypatch.setenv("ACTOR", "test-user")
    monkeypatch.setenv("RUN_ID", "9999")
    monkeypatch.setenv("RUN_URL", "https://github.com/org/repo/actions/runs/9999")
    monkeypatch.setenv("ISSUE_NUMBER", "42")


# ---------------------------------------------------------------------------
# status_template helper
# ---------------------------------------------------------------------------


class TestStatusTemplate:
    def test_renders_title(self):
        result = status_template("My Title", "<!-- marker -->", "| row |", "Body text")
        assert "### My Title" in result

    def test_renders_markers(self):
        result = status_template("T", "<!-- gpa:marker -->", "", "")
        assert "<!-- gpa:marker -->" in result

    def test_renders_body(self):
        result = status_template("T", "", "", "Important body content")
        assert "Important body content" in result

    def test_renders_payload_line(self):
        result = status_template("T", "", "", "", payload_line="<!-- payload:data -->")
        assert "<!-- payload:data -->" in result

    def test_omits_payload_when_empty(self):
        result = status_template("T", "", "", "body", payload_line="")
        # No extra blank line from payload
        assert "body" in result


# ---------------------------------------------------------------------------
# e() helper
# ---------------------------------------------------------------------------


class TestEHelper:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR_ABC", "hello")
        assert e("TEST_VAR_ABC") == "hello"

    def test_returns_default_when_missing(self):
        assert e("NONEXISTENT_VAR_XYZ", "fallback") == "fallback"

    def test_returns_empty_string_by_default(self):
        assert e("NONEXISTENT_VAR_XYZ") == ""


# ---------------------------------------------------------------------------
# Orchestration templates
# ---------------------------------------------------------------------------


class TestDuplicate:
    def test_contains_run_key(self, monkeypatch):
        monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "300")
        result = duplicate()
        assert "abc123" in result

    def test_contains_skipped_marker(self, monkeypatch):
        monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "300")
        result = duplicate()
        assert "skipped" in result
        assert "gpa:run-status" in result

    def test_contains_actor(self, monkeypatch):
        monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "300")
        result = duplicate()
        assert "@test-user" in result

    def test_contains_dedup_window(self, monkeypatch):
        monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "600")
        result = duplicate()
        assert "600" in result


class TestGateFailed:
    def test_contains_gate_marker(self, monkeypatch):
        monkeypatch.setenv("CHECKPOINT", "")
        monkeypatch.setenv("UNMET_LIST", "- condition A")
        monkeypatch.setenv("WAIVED_LIST", "- (none)")
        result = gate_failed()
        assert "gpa:run-status" in result
        assert "failed" in result

    def test_contains_unmet_conditions(self, monkeypatch):
        monkeypatch.setenv("CHECKPOINT", "")
        monkeypatch.setenv("UNMET_LIST", "- must have review")
        monkeypatch.setenv("WAIVED_LIST", "- (none)")
        result = gate_failed()
        assert "must have review" in result

    def test_renders_checkpoint_when_present(self, monkeypatch):
        monkeypatch.setenv("CHECKPOINT", "v1:design:42:abc")
        monkeypatch.setenv("UNMET_LIST", "- x")
        monkeypatch.setenv("WAIVED_LIST", "")
        result = gate_failed()
        assert "gpa:checkpoint v1:design:42:abc" in result

    def test_table_rows_present(self, monkeypatch):
        monkeypatch.setenv("CHECKPOINT", "")
        monkeypatch.setenv("UNMET_LIST", "")
        monkeypatch.setenv("WAIVED_LIST", "")
        result = gate_failed()
        assert "| **Run key**" in result
        assert "| **Actor**" in result


class TestStageTransition:
    def test_contains_completed_marker(self, monkeypatch):
        monkeypatch.setenv("CANONICAL_CHECKPOINT_LINE", "")
        monkeypatch.setenv("CHECKPOINT_LINE", "")
        monkeypatch.setenv("WAIVED_SECTION", "")
        result = stage_transition()
        assert "completed" in result
        assert "gpa:run-status" in result

    def test_contains_run_url(self, monkeypatch):
        monkeypatch.setenv("CANONICAL_CHECKPOINT_LINE", "")
        monkeypatch.setenv("CHECKPOINT_LINE", "")
        monkeypatch.setenv("WAIVED_SECTION", "")
        result = stage_transition()
        assert "https://github.com/org/repo/actions/runs/9999" in result


class TestNextStageQueued:
    def test_contains_next_stage(self, monkeypatch):
        monkeypatch.setenv("NEXT_STAGE", "plan")
        monkeypatch.setenv("NEXT_RUN_KEY", "def456")
        monkeypatch.setenv("CHECKPOINT", "v1:design:42:abc")
        result = next_stage_queued()
        assert "plan" in result
        assert "def456" in result
        assert "gpa:checkpoint" in result


# ---------------------------------------------------------------------------
# Scaffold templates
# ---------------------------------------------------------------------------


class TestDesignScaffoldCreated:
    def test_contains_design_marker(self, monkeypatch):
        monkeypatch.setenv("TABLE_ROWS", "| **Issue** | #42 |")
        result = design_scaffold_created()
        assert f"gpa:design-discussion:#42" in result

    def test_contains_table_rows(self, monkeypatch):
        monkeypatch.setenv("TABLE_ROWS", "| **Issue** | #42 |")
        result = design_scaffold_created()
        assert "| **Issue** | #42 |" in result


class TestDesignScaffoldExists:
    def test_contains_skipped_status(self, monkeypatch):
        monkeypatch.setenv("ARTIFACT_MARKER", "gpa:design-discussion:#42")
        monkeypatch.setenv("TABLE_ROWS", "")
        result = design_scaffold_exists()
        assert "skipped" in result
        assert "already exists" in result


class TestPlanScaffoldCreated:
    def test_contains_plan_status_marker(self, monkeypatch):
        monkeypatch.setenv("TABLE_ROWS", "| **Issue** | #42 |")
        result = plan_scaffold_created()
        assert "gpa:impl-plan-status:#42" in result
        assert "completed" in result


class TestExecutionScaffoldCreated:
    def test_contains_execution_status(self, monkeypatch):
        monkeypatch.setenv("STATUS_MARKER", "gpa:execution-status:#42")
        monkeypatch.setenv("TABLE_ROWS", "| **Branch** | 42-feature |")
        result = execution_scaffold_created()
        assert "gpa:execution-status:#42" in result
        assert "completed" in result


class TestCloseoutScaffoldCreated:
    def test_contains_payload_line(self, monkeypatch):
        monkeypatch.setenv("STATUS_MARKER", "gpa:closeout-status:#42")
        monkeypatch.setenv("TABLE_ROWS", "")
        monkeypatch.setenv("ARTIFACT_PAYLOAD", '{"kind":"test"}')
        result = closeout_scaffold_created()
        assert "gpa:artifact-payload:" in result
        assert "closeout" in result


class TestCloseoutScaffoldExists:
    def test_contains_skipped_status(self, monkeypatch):
        monkeypatch.setenv("STATUS_MARKER", "gpa:closeout-status:#42")
        monkeypatch.setenv("TABLE_ROWS", "")
        monkeypatch.setenv("ARTIFACT_PAYLOAD", '{"kind":"test"}')
        result = closeout_scaffold_exists()
        assert "skipped" in result
        assert "already exists" in result


# ---------------------------------------------------------------------------
# TEMPLATES dict completeness
# ---------------------------------------------------------------------------


class TestTemplatesDict:
    def test_orchestration_templates_present(self):
        for key in ("duplicate", "gate-failed", "stage-transition", "ineligible"):
            assert key in TEMPLATES

    def test_scaffold_templates_present(self):
        for key in ("design-scaffold-created", "plan-scaffold-created", "execution-scaffold-created", "closeout-scaffold-created"):
            assert key in TEMPLATES

    def test_all_values_callable(self):
        for name, fn in TEMPLATES.items():
            assert callable(fn), f"Template {name} is not callable"
