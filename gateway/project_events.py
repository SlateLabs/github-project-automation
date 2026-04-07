from __future__ import annotations

from typing import Any

from gateway.dispatch import dispatch_with_retry
from gateway.github_api import GitHubApiError
from gateway.policy import check_project_item_eligibility, log_fields, resolve_actor_decision
from gateway.results import GatewayResult
from gateway.stage_map import DISPATCH_EVENT_TYPE, DISPATCH_RETRY_BACKOFFS, REQUESTED_STAGE


def handle_project_event(
    service: Any,
    *,
    delivery_id: str,
    payload: dict[str, Any],
    actor: str,
    now_ms: int,
) -> GatewayResult:
    event_name = "projects_v2_item"
    requested_stage = REQUESTED_STAGE
    transition = service._extract_status_transition(payload)
    if transition != ("Backlog", "Ready"):
        service.logger(
            {
                "delivery_id": delivery_id,
                "event": event_name,
                "actor": actor,
                "outcome": "skipped",
                "reason": "non-kickoff transition",
                "transition": transition,
            }
        )
        return GatewayResult(202, {"outcome": "skipped", "reason": "Only Status: Backlog -> Ready triggers kickoff automation"})

    item_node_id = service._extract_project_item_node_id(payload)
    if not item_node_id:
        return GatewayResult(400, {"outcome": "rejected", "reason": "projects_v2_item payload is missing a node id"})

    try:
        context = service.github_client.get_project_item_context(item_node_id)
    except GitHubApiError as exc:
        return GatewayResult(502, {"outcome": "error", "reason": f"Failed to resolve project item context: {exc}"})

    eligibility_error = check_project_item_eligibility(context=context, requested_stage=requested_stage, repo_config=service.repo_config)
    if eligibility_error:
        service.logger(
            {
                "delivery_id": delivery_id,
                "event": event_name,
                "actor": actor,
                "repo": context.repository_field_repo,
                "issue": context.issue_number,
                "requested_stage": requested_stage,
                "outcome": "rejected",
                "reason": eligibility_error,
            }
        )
        return GatewayResult(422, {"outcome": "rejected", "reason": eligibility_error})

    repo_full_name = context.repository_field_repo or ""
    issue_number = int(context.issue_number or 0)
    run_key = f"{repo_full_name}/{issue_number}/{requested_stage}/{now_ms}"
    prefix = f"{repo_full_name}/{issue_number}/{requested_stage}"

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

    if service.dedup_store.has_active_run(prefix, now_ms):
        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=issue_number,
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="deduplicated",
                reason="active run already exists",
            )
        )
        return GatewayResult(202, {"outcome": "deduplicated", "reason": "An active kickoff run already exists", "run_key": run_key})

    if service.dedup_store.has_recent_completion(prefix, now_ms):
        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=issue_number,
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="deduplicated",
                reason="recent run completed inside dedup window",
            )
        )
        return GatewayResult(202, {"outcome": "deduplicated", "reason": "A recent kickoff run already completed", "run_key": run_key})

    service.dedup_store.mark_active(prefix, run_key, now_ms)
    timestamp = str(now_ms)
    client_payload = {
        "issue_number": issue_number,
        "issue_title": context.issue_title,
        "requested_stage": requested_stage,
        "run_key": run_key,
        "actor": actor,
        "timestamp": timestamp,
        "project_item_id": context.project_item_id,
    }

    try:
        if decision.outcome == "record-only":
            service.github_client.ensure_issue_label(repo_full_name, issue_number, "pending-review")
            service.dedup_store.clear_active(prefix)
            service.logger(
                log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    requested_stage=requested_stage,
                    run_key=run_key,
                    outcome="pending-review",
                    reason=decision.reason,
                )
            )
            return GatewayResult(202, {"outcome": "pending-review", "reason": decision.reason, "run_key": run_key})

        last_error = dispatch_with_retry(
            github_client=service.github_client,
            repo_full_name=repo_full_name,
            event_type=DISPATCH_EVENT_TYPE,
            client_payload=client_payload,
            delivery_id=delivery_id,
            actor=actor,
            issue_number=issue_number,
            run_key=run_key,
            retry_backoffs=DISPATCH_RETRY_BACKOFFS,
            logger=service.logger,
            sleep=service.sleep,
        )
        if last_error is not None:
            service.dedup_store.clear_active(prefix)
            service.logger(
                log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    requested_stage=requested_stage,
                    run_key=run_key,
                    outcome="dispatch-failed",
                    reason=str(last_error),
                )
            )
            return GatewayResult(502, {"outcome": "dispatch-failed", "reason": str(last_error), "run_key": run_key})

        service.dedup_store.mark_completed(prefix, run_key, now_ms)
        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=issue_number,
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="dispatched",
            )
        )
        return GatewayResult(200, {"outcome": "dispatched", "run_key": run_key, "payload": client_payload})
    except GitHubApiError as exc:
        service.dedup_store.clear_active(prefix)
        service.logger(
            log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=issue_number,
                requested_stage=requested_stage,
                run_key=run_key,
                outcome="error",
                reason=str(exc),
            )
        )
        return GatewayResult(502, {"outcome": "error", "reason": str(exc), "run_key": run_key})
