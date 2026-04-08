"""Tests for scripts/build_orchestration_prompt.py."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_orchestration_prompt import (
    BUILDERS,
    build_agent_review,
    build_design_author,
    build_design_review,
    build_execution_author,
    build_merge_conflict,
    build_plan_author,
    build_plan_review,
    main,
)


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    """Set baseline env vars that most builders reference."""
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_TITLE", "Add widget support")
    monkeypatch.setenv("ISSUE_BODY", "We need widgets for the dashboard.")


# ---------------------------------------------------------------------------
# Individual builders
# ---------------------------------------------------------------------------


class TestBuildDesignAuthor:
    def test_contains_issue_number(self):
        result = build_design_author()
        assert "#42" in result

    def test_contains_issue_body(self):
        result = build_design_author()
        assert "We need widgets" in result

    def test_contains_issue_title(self):
        result = build_design_author()
        assert "Add widget support" in result

    def test_contains_required_structure_markers(self, monkeypatch):
        monkeypatch.setenv("DISCUSSION_BODY", "existing discussion content")
        result = build_design_author()
        assert "## Summary" in result
        assert "## Open Questions" in result
        assert "existing discussion content" in result


class TestBuildDesignReview:
    def test_contains_issue_number(self, tmp_path, monkeypatch):
        discussion_file = tmp_path / "discussion.md"
        discussion_file.write_text("Design content here")
        monkeypatch.setenv("DISCUSSION_FILE", str(discussion_file))
        result = build_design_review()
        assert "#42" in result
        assert "Design content here" in result


class TestBuildPlanAuthor:
    def test_contains_design_body(self, monkeypatch):
        monkeypatch.setenv("DESIGN_BODY", "The design proposes X approach")
        monkeypatch.setenv("PLAN_BODY", "existing plan")
        result = build_plan_author()
        assert "#42" in result
        assert "The design proposes X approach" in result

    def test_contains_required_headings(self, monkeypatch):
        monkeypatch.setenv("DESIGN_BODY", "")
        monkeypatch.setenv("PLAN_BODY", "")
        result = build_plan_author()
        assert "## Implementation Plan" in result
        assert "## Acceptance Criteria" in result
        assert "## Slices" in result


class TestBuildPlanReview:
    def test_reads_plan_file(self, tmp_path, monkeypatch):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("Plan slice 1: do the thing")
        monkeypatch.setenv("PLAN_FILE", str(plan_file))
        result = build_plan_review()
        assert "#42" in result
        assert "Plan slice 1: do the thing" in result


class TestBuildExecutionAuthor:
    def test_contains_branch_name(self, monkeypatch):
        monkeypatch.setenv("BRANCH_NAME", "42-add-widgets")
        monkeypatch.setenv("PLAN_BODY", "Plan details")
        monkeypatch.setenv("REQUESTED_STAGE", "execution")
        monkeypatch.setenv("FEEDBACK_BODY", "")
        monkeypatch.setenv("FEEDBACK_SOURCE", "")
        result = build_execution_author()
        assert "42-add-widgets" in result

    def test_contains_plan_body(self, monkeypatch):
        monkeypatch.setenv("BRANCH_NAME", "42-add-widgets")
        monkeypatch.setenv("PLAN_BODY", "Slice 1: create widget module")
        monkeypatch.setenv("REQUESTED_STAGE", "execution")
        monkeypatch.setenv("FEEDBACK_BODY", "")
        monkeypatch.setenv("FEEDBACK_SOURCE", "")
        result = build_execution_author()
        assert "Slice 1: create widget module" in result

    def test_contains_feedback(self, monkeypatch):
        monkeypatch.setenv("BRANCH_NAME", "42-add-widgets")
        monkeypatch.setenv("PLAN_BODY", "")
        monkeypatch.setenv("REQUESTED_STAGE", "execution")
        monkeypatch.setenv("FEEDBACK_BODY", "Please also update the tests")
        monkeypatch.setenv("FEEDBACK_SOURCE", "operator")
        result = build_execution_author()
        assert "Please also update the tests" in result


class TestBuildAgentReview:
    def test_reads_required_files(self, tmp_path, monkeypatch):
        review_file = tmp_path / "review.md"
        diff_file = tmp_path / "diff.txt"
        diff_file.write_text("+added line\n-removed line")
        monkeypatch.setenv("REVIEW_FILE", str(review_file))
        monkeypatch.setenv("DIFF_FILE", str(diff_file))
        monkeypatch.setenv("PR_TITLE", "feat: add widgets")
        monkeypatch.setenv("PR_URL", "https://github.com/org/repo/pull/10")
        monkeypatch.setenv("PR_BODY", "PR description")
        monkeypatch.setenv("FILES_SUMMARY", "scripts/widget.py")
        result = build_agent_review()
        assert "#42" in result
        assert "+added line" in result
        assert "feat: add widgets" in result

    def test_missing_diff_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVIEW_FILE", str(tmp_path / "review.md"))
        monkeypatch.setenv("DIFF_FILE", str(tmp_path / "nonexistent.txt"))
        monkeypatch.setenv("PR_TITLE", "")
        monkeypatch.setenv("PR_URL", "")
        monkeypatch.setenv("PR_BODY", "")
        monkeypatch.setenv("FILES_SUMMARY", "")
        with pytest.raises(FileNotFoundError):
            build_agent_review()


class TestBuildMergeConflict:
    def test_contains_branch_and_issue(self, monkeypatch):
        monkeypatch.setenv("BRANCH_NAME", "42-add-widgets")
        monkeypatch.setenv("PR_NUMBER", "10")
        monkeypatch.setenv("BASE_REF", "main")
        monkeypatch.setenv("CONFLICT_FILES", "scripts/widget.py\nscripts/other.py")
        result = build_merge_conflict()
        assert "42-add-widgets" in result
        assert "#42" in result
        assert "scripts/widget.py" in result


# ---------------------------------------------------------------------------
# BUILDERS dict completeness
# ---------------------------------------------------------------------------


class TestBuildersDict:
    def test_all_modes_present(self):
        expected = {
            "design-author",
            "design-review",
            "plan-author",
            "plan-review",
            "execution-author",
            "agent-review",
            "merge-conflict",
        }
        assert set(BUILDERS.keys()) == expected

    def test_all_builders_are_callable(self):
        for name, fn in BUILDERS.items():
            assert callable(fn), f"Builder {name} is not callable"


# ---------------------------------------------------------------------------
# main() with captured stdout
# ---------------------------------------------------------------------------


class TestMain:
    def test_design_author_to_stdout(self, monkeypatch):
        monkeypatch.setenv("DISCUSSION_BODY", "")
        captured = StringIO()
        with patch("sys.argv", ["prog", "design-author"]), patch("sys.stdout", captured):
            main()
        output = captured.getvalue()
        assert "#42" in output
        assert "Add widget support" in output

    def test_output_to_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISCUSSION_BODY", "")
        output_file = tmp_path / "prompt.txt"
        with patch("sys.argv", ["prog", "design-author", "--output", str(output_file)]):
            main()
        content = output_file.read_text()
        assert "#42" in content

    def test_invalid_mode_exits(self, monkeypatch):
        with patch("sys.argv", ["prog", "invalid-mode"]), pytest.raises(SystemExit):
            main()
