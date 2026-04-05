from __future__ import annotations

import unittest

from gateway.orchestration_contract import (
    CoarseStatus,
    REVIEW_READY_MARKER,
    OperatorCommandType,
    OrchestrationStage,
    RetryMetadata,
    StageEvent,
    StageOutcome,
    find_latest_review_ready_marker_ms,
    is_transition_allowed,
    parse_operator_command,
    select_latest_operator_command,
)


class OrchestrationContractTests(unittest.TestCase):
    def test_transition_map_allows_review_loop_and_finalize(self) -> None:
        self.assertTrue(
            is_transition_allowed(OrchestrationStage.REVIEW_INTAKE, OrchestrationStage.FEEDBACK_IMPLEMENTATION)
        )
        self.assertTrue(
            is_transition_allowed(OrchestrationStage.REVIEW_INTAKE, OrchestrationStage.MERGE)
        )
        self.assertTrue(
            is_transition_allowed(OrchestrationStage.REDEPLOY_REVIEW, OrchestrationStage.REVIEW_INTAKE)
        )
        self.assertTrue(
            is_transition_allowed(OrchestrationStage.POST_MERGE_VERIFY, OrchestrationStage.FOLLOW_UP_CAPTURE)
        )

    def test_stage_event_validation_rejects_invalid_transition(self) -> None:
        with self.assertRaises(ValueError):
            StageEvent(
                run_key="SlateLabs/repo/33/review-intake/1710000000000",
                issue_number=33,
                stage=OrchestrationStage.REVIEW_INTAKE,
                outcome=StageOutcome.COMPLETED,
                status=CoarseStatus.IN_REVIEW,
                idempotency_key="33/review-intake/1",
                actor="bot",
                timestamp_ms=1710000000000,
                next_stage=OrchestrationStage.CLOSEOUT,
            )

    def test_stage_event_serialization_includes_retry_metadata(self) -> None:
        event = StageEvent(
            run_key="SlateLabs/repo/33/post-merge-verify/1710000000000",
            issue_number=33,
            stage=OrchestrationStage.POST_MERGE_VERIFY,
            outcome=StageOutcome.RETRYING,
            status=CoarseStatus.IN_PROGRESS,
            idempotency_key="33/post-merge-verify/2",
            actor="bot",
            timestamp_ms=1710000000000,
            next_stage=OrchestrationStage.POST_MERGE_VERIFY,
            retry=RetryMetadata(attempt=2, max_attempts=3, retriable=True, backoff_seconds=(10, 30, 60)),
            error="verification failed",
        )

        payload = event.to_dict()
        self.assertEqual(payload["stage"], "post-merge-verify")
        self.assertEqual(payload["next_stage"], "post-merge-verify")
        self.assertEqual(payload["retry"]["attempt"], 2)
        self.assertEqual(payload["retry"]["max_attempts"], 3)
        self.assertEqual(payload["retry"]["backoff_seconds"], [10, 30, 60])
        self.assertEqual(payload["error"], "verification failed")

    def test_retry_metadata_validation(self) -> None:
        with self.assertRaises(ValueError):
            RetryMetadata(attempt=0)
        with self.assertRaises(ValueError):
            RetryMetadata(attempt=2, max_attempts=1)

    def test_parse_operator_command(self) -> None:
        self.assertEqual(parse_operator_command("gpa:approve"), (OperatorCommandType.APPROVE, None))
        self.assertEqual(
            parse_operator_command("gpa:feedback tighten retry guardrails"),
            (OperatorCommandType.FEEDBACK, "tighten retry guardrails"),
        )
        self.assertEqual(
            parse_operator_command("gpa:feedback\nPlease fix flaky deploy check\nand retry."),
            (OperatorCommandType.FEEDBACK, "Please fix flaky deploy check\nand retry."),
        )
        self.assertIsNone(parse_operator_command("gpa:feedback"))
        self.assertIsNone(parse_operator_command("looks good"))

    def test_select_latest_valid_operator_command(self) -> None:
        comments = [
            {
                "id": 100,
                "created_at_ms": 1000,
                "author": "trusted-1",
                "body": "gpa:feedback first attempt",
            },
            {
                "id": 101,
                "created_at_ms": 1100,
                "author": "outsider",
                "body": "gpa:approve",
            },
            {
                "id": 102,
                "created_at_ms": 1200,
                "author": "trusted-1",
                "body": "gpa:approve",
            },
            {
                "id": 103,
                "created_at_ms": 1300,
                "author": "trusted-2",
                "body": "gpa:feedback fix deployment healthcheck",
            },
        ]

        selected = select_latest_operator_command(
            comments=comments,
            trusted_users={"trusted-1", "trusted-2"},
            review_ready_after_ms=1050,
            consumed_comment_ids={102},
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.comment_id, 103)
        self.assertEqual(selected.command_type, OperatorCommandType.FEEDBACK)
        self.assertEqual(selected.instructions, "fix deployment healthcheck")

    def test_select_operator_command_returns_none_when_all_stale(self) -> None:
        comments = [
            {
                "id": 200,
                "created_at_ms": 900,
                "author": "trusted-1",
                "body": "gpa:approve",
            }
        ]

        selected = select_latest_operator_command(
            comments=comments,
            trusted_users={"trusted-1"},
            review_ready_after_ms=1000,
        )
        self.assertIsNone(selected)

    def test_find_latest_review_ready_marker(self) -> None:
        comments = [
            {"id": 1, "created_at_ms": 1000, "author": "bot", "body": f"<!-- {REVIEW_READY_MARKER} -->"},
            {"id": 2, "created_at_ms": 1200, "author": "bot", "body": "normal comment"},
            {"id": 3, "created_at_ms": 1300, "author": "bot", "body": f"{REVIEW_READY_MARKER} deployment: https://example"},
        ]
        self.assertEqual(find_latest_review_ready_marker_ms(comments), 1300)
        self.assertIsNone(find_latest_review_ready_marker_ms([{"id": 9, "created_at_ms": 1400, "body": "none"}]))


if __name__ == "__main__":
    unittest.main()
