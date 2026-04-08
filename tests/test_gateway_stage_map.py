"""Tests for gateway.stage_map — stage resolution and progression."""

from __future__ import annotations

import pytest

from gateway.stage_map import (
    DISPATCH_EVENT_TYPE,
    DISPATCH_RETRY_BACKOFFS,
    MANUAL_STAGES,
    OPERATOR_COMMANDS,
    REQUESTED_STAGE,
    default_reason_codes,
    resolve_next_stage,
)


class TestStageMapConstants:

    def test_requested_stage_is_kickoff(self):
        assert REQUESTED_STAGE == "kickoff"

    def test_dispatch_event_type(self):
        assert DISPATCH_EVENT_TYPE == "orchestration-start"

    def test_retry_backoffs_are_increasing(self):
        for i in range(1, len(DISPATCH_RETRY_BACKOFFS)):
            assert DISPATCH_RETRY_BACKOFFS[i] > DISPATCH_RETRY_BACKOFFS[i - 1]

    def test_operator_commands_include_feedback_and_approve(self):
        assert "gpa:feedback" in OPERATOR_COMMANDS
        assert "gpa:approve" in OPERATOR_COMMANDS

    def test_manual_stages_is_nonempty(self):
        assert len(MANUAL_STAGES) > 0
        assert "kickoff" in MANUAL_STAGES


class TestResolveNextStage:

    @pytest.mark.parametrize(
        "stage, expected_next",
        [
            ("kickoff", "clarification"),
            ("clarification", "design"),
            ("design", "plan"),
            ("plan", "execution"),
            ("merge", "follow-up-capture"),
            ("follow-up-capture", "closeout"),
        ],
    )
    def test_linear_progression(self, stage, expected_next):
        result = resolve_next_stage(requested_stage=stage)
        assert result["next_stage"] == expected_next

    def test_closeout_has_no_next_stage(self):
        result = resolve_next_stage(requested_stage="closeout")
        assert result["next_stage"] == ""
        assert result["target_status"] == "Done"

    def test_execution_default_goes_to_agent_review(self):
        result = resolve_next_stage(requested_stage="execution")
        assert result["next_stage"] == "agent-review"

    def test_execution_operator_no_progress(self):
        result = resolve_next_stage(
            requested_stage="execution",
            feedback_source="operator",
            feedback_no_progress=True,
        )
        assert result["next_stage"] == ""
        assert result["target_status"] == "In Review"

    def test_agent_review_auto_approve(self):
        result = resolve_next_stage(
            requested_stage="agent-review",
            review_disposition="auto-approve",
        )
        assert result["next_stage"] == "merge"

    def test_agent_review_rework_required(self):
        result = resolve_next_stage(
            requested_stage="agent-review",
            review_disposition="rework-required",
        )
        assert result["next_stage"] == "execution"

    def test_agent_review_operator_review(self):
        result = resolve_next_stage(
            requested_stage="agent-review",
            review_disposition="operator-review-required",
        )
        assert result["next_stage"] == ""

    def test_agent_review_explicit_next_stage(self):
        result = resolve_next_stage(
            requested_stage="agent-review",
            review_next_stage="merge",
        )
        assert result["next_stage"] == "merge"

    def test_agent_review_invalid_next_stage_raises(self):
        with pytest.raises(ValueError, match="Unknown review_next_stage"):
            resolve_next_stage(
                requested_stage="agent-review",
                review_next_stage="closeout",
            )

    def test_agent_review_invalid_disposition_raises(self):
        with pytest.raises(ValueError, match="Unknown or missing review disposition"):
            resolve_next_stage(
                requested_stage="agent-review",
                review_disposition="invalid",
            )

    def test_unknown_stage_raises(self):
        with pytest.raises(ValueError, match="Unknown requested_stage"):
            resolve_next_stage(requested_stage="nonexistent")


class TestDefaultReasonCodes:

    def test_with_next_stage(self):
        codes = default_reason_codes("clarification")
        assert "stage_gate_passed" in codes
        assert "stage_handoff_queued" in codes

    def test_without_next_stage(self):
        codes = default_reason_codes("")
        assert "stage_gate_passed" in codes
        assert "stage_handoff_queued" not in codes
