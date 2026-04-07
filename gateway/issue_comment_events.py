from __future__ import annotations

from typing import Any

from gateway.commands import parse_operator_command
from gateway.dispatch import dispatch_with_retry
from gateway.github_api import GitHubApiError
from gateway.policy import check_project_item_eligibility, log_fields, resolve_actor_decision
from gateway.results import GatewayResult
from gateway.stage_map import DISPATCH_EVENT_TYPE, DISPATCH_RETRY_BACKOFFS


def handle_issue_comment_event(
    service: Any,
    *,
    delivery_id: str,
    payload: dict[str, Any],
    actor: str,
    now_ms: int,
) -> GatewayResult:
    if payload.get("action") != "created":
        return GatewayResult(202, {"outcome": "skipped", "reason": "Only created issue comments are supported"})

    issue = payload.get("issue") or {}
    if issue.get("pull_request") is not None:
        return GatewayResult(202, {"outcome": "skipped", "reason": "Pull request comments do not trigger operator orchestration"})

    sender = payload.get("sender") or {}
    if sender.get("type") == "Bot":
        return GatewayResult(202, {"outcome": "skipped", "reason": "Bot comments do not trigger operator orchestration"})

    comment = payload.get("comment") or {}
    command = parse_operator_command(comment.get("body") or "")
    if command is None:
        return GatewayResult(202, {"outcome": "skipped", "reason": "Comment is not a GPA operator command"})

    requested_stage, feedback_body = command
    if requested_stage == "execution" and comment.get("body", "").lstrip().lower().startswith("gpa:feedback") and not feedback_body:
        return GatewayResult(422, {"outcome": "rejected", "reason": "gpa:feedback requires non-empty instructions"})

    repo_full_name = ((payload.get("repository") or {}).get("full_name") or issue.get("repository_url", "").removeprefix("https://api.github.com/repos/"))
    issue_number = issue.get("number")
    if not repo_full_name or issue_number is None:
        return GatewayResult(400, {"outcome": "rejected", "reason": "issue_comment payload is missing repository or issue context"})

    run_key = f"{repo_full_name}/{issue_number}/{requested_stage}/{now_ms}"
    decision = resolve_actor_decision(
        payload=payload,
        actor_login=actor,
        repo_full_name=repo_full_name,
        trust_policy=service.trust_policy,
        github_client=service.github_client,
    )
    if decision.outcome == "denied":
        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=issue_number,
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="dropped",
                reason=decision.reason,
            )
        )
        return GatewayResult(202, {"outcome": "dropped", "reason": decision.reason, "run_key": run_key})

    try:
        context = service.github_client.get_issue_project_item_context(repo_full_name, int(issue_number))
    except GitHubApiError as exc:
        return GatewayResult(502, {"outcome": "error", "reason": f"Failed to resolve issue project context: {exc}"})

    eligibility_error = check_project_item_eligibility(context=context, requested_stage=requested_stage, repo_config=service.repo_config)
    if eligibility_error:
        service.logger(
            {
                "delivery_id": delivery_id,
                "event": "issue_comment",
                "actor": actor,
                "repo": repo_full_name,
                "issue": context.issue_number,
                "requested_stage": requested_stage,
                "outcome": "rejected",
                "reason": eligibility_error,
            }
        )
        return GatewayResult(422, {"outcome": "rejected", "reason": eligibility_error})

    client_payload = {
        "issue_number": int(context.issue_number or issue_number),
        "issue_title": context.issue_title,
        "requested_stage": requested_stage,
        "run_key": run_key,
        "actor": actor,
        "timestamp": str(now_ms),
        "project_item_id": context.project_item_id,
    }
    if requested_stage == "execution" and feedback_body:
        client_payload["feedback_source"] = "operator"
        client_payload["feedback_body"] = feedback_body

    try:
        if decision.outcome == "record-only":
            service.github_client.ensure_issue_label(repo_full_name, int(issue_number), "pending-review")
            service.logger(
                log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=int(issue_number),
                    requested_stage=requested_stage,
                    run_key=run_key,
                    outcome="pending-review",
                    reason=decision.reason,
                )
            )
            return GatewayResult(202, {"outcome": "pending-review", "reason": decision.reason, "run_key": run_key})

        if requested_stage == "execution" and feedback_body:
            service.github_client.update_project_item_status(context.project_item_id, "In Progress")

        last_error = dispatch_with_retry(
            github_client=service.github_client,
            repo_full_name=repo_full_name,
            event_type=DISPATCH_EVENT_TYPE,
            client_payload=client_payload,
            delivery_id=delivery_id,
            actor=actor,
            issue_number=int(issue_number),
            run_key=run_key,
            retry_backoffs=DISPATCH_RETRY_BACKOFFS,
            logger=service.logger,
            sleep=service.sleep,
        )
        if last_error is not None:
            service.logger(
                log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=int(issue_number),
                    requested_stage=requested_stage,
                    run_key=run_key,
                    outcome="dispatch-failed",
                    reason=str(last_error),
                )
            )
            return GatewayResult(502, {"outcome": "dispatch-failed", "reason": str(last_error), "run_key": run_key})

        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=int(issue_number),
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="dispatched",
            )
        )
        return GatewayResult(200, {"outcome": "dispatched", "run_key": run_key, "payload": client_payload})
    except GitHubApiError as exc:
        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=int(issue_number),
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="error",
                reason=str(exc),
            )
        )
        return GatewayResult(502, {"outcome": "error", "reason": str(exc), "run_key": run_key})
