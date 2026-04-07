"""Core webhook gateway logic for orchestration dispatch."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from gateway.commands import parse_operator_command
from gateway.dedup import InMemoryDedupStore
from gateway.dispatch import dispatch_with_retry
from gateway.github_api import (
    ConfiguredRepo,
    GitHubApiError,
    ProjectItemContext,
    TrustPolicy,
)
from gateway.policy import ActorDecision, check_project_item_eligibility, log_fields, resolve_actor_decision
from gateway.stage_map import DISPATCH_EVENT_TYPE, DISPATCH_RETRY_BACKOFFS, REQUESTED_STAGE


@dataclass(frozen=True)
class GatewayResult:
    status_code: int
    body: dict[str, Any]


class GatewayService:
    """Admission, trust, dedup, and dispatch for org-project kickoff events."""

    def __init__(
        self,
        *,
        webhook_secret: str,
        github_client: Any,
        repo_config: dict[str, ConfiguredRepo],
        trust_policy: TrustPolicy,
        dedup_store: InMemoryDedupStore,
        logger: Callable[[dict[str, Any]], None],
        clock: Callable[[], int] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.webhook_secret = webhook_secret.encode("utf-8")
        self.github_client = github_client
        self.repo_config = repo_config
        self.trust_policy = trust_policy
        self.dedup_store = dedup_store
        self.logger = logger
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.sleep = sleep or time.sleep

    def handle_delivery(self, headers: dict[str, str], raw_body: bytes) -> GatewayResult:
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        delivery_id = normalized_headers.get("x-github-delivery", "")
        event_name = normalized_headers.get("x-github-event", "")
        signature = normalized_headers.get("x-hub-signature-256", "")
        now_ms = self.clock()

        if not delivery_id or not event_name:
            return GatewayResult(400, {"outcome": "rejected", "reason": "Missing required GitHub delivery headers"})
        if not self._valid_signature(signature, raw_body):
            return GatewayResult(401, {"outcome": "rejected", "reason": "Invalid webhook signature"})
        if self.dedup_store.seen_delivery(delivery_id, now_ms):
            self.logger({"delivery_id": delivery_id, "outcome": "deduplicated", "reason": "duplicate delivery id"})
            return GatewayResult(202, {"outcome": "deduplicated", "reason": "Delivery has already been processed"})

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            return GatewayResult(400, {"outcome": "rejected", "reason": "Request body is not valid JSON"})

        actor = (payload.get("sender") or {}).get("login", "unknown")

        if event_name == "ping":
            self.logger(
                {
                    "delivery_id": delivery_id,
                    "event": event_name,
                    "actor": actor,
                    "outcome": "accepted",
                    "reason": "webhook ping",
                }
            )
            return GatewayResult(200, {"outcome": "accepted", "event": "ping"})

        if event_name == "projects_v2_item":
            return self._handle_project_event(
                delivery_id=delivery_id,
                payload=payload,
                actor=actor,
                now_ms=now_ms,
            )

        if event_name == "issue_comment":
            return self._handle_issue_comment_event(
                delivery_id=delivery_id,
                payload=payload,
                actor=actor,
                now_ms=now_ms,
            )

        self.logger(
            {
                "delivery_id": delivery_id,
                "event": event_name,
                "actor": actor,
                "outcome": "skipped",
                "reason": "unsupported event",
            }
        )
        return GatewayResult(202, {"outcome": "skipped", "reason": "Only projects_v2_item and issue_comment events are supported"})

    def _handle_project_event(
        self,
        *,
        delivery_id: str,
        payload: dict[str, Any],
        actor: str,
        now_ms: int,
    ) -> GatewayResult:
        event_name = "projects_v2_item"
        requested_stage = REQUESTED_STAGE
        transition = self._extract_status_transition(payload)
        if transition != ("Backlog", "Ready"):
            self.logger(
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

        item_node_id = self._extract_project_item_node_id(payload)
        if not item_node_id:
            return GatewayResult(400, {"outcome": "rejected", "reason": "projects_v2_item payload is missing a node id"})

        try:
            context = self.github_client.get_project_item_context(item_node_id)
        except GitHubApiError as exc:
            return GatewayResult(502, {"outcome": "error", "reason": f"Failed to resolve project item context: {exc}"})

        eligibility_error = check_project_item_eligibility(context=context, requested_stage=requested_stage, repo_config=self.repo_config)
        if eligibility_error:
            self.logger(
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
            trust_policy=self.trust_policy,
            github_client=self.github_client,
        )
        if decision.outcome == "denied":
            self.logger(
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

        if self.dedup_store.has_active_run(prefix, now_ms):
            self.logger(
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

        if self.dedup_store.has_recent_completion(prefix, now_ms):
            self.logger(
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

        self.dedup_store.mark_active(prefix, run_key, now_ms)
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
                self.github_client.ensure_issue_label(repo_full_name, issue_number, "pending-review")
                self.dedup_store.clear_active(prefix)
                self.logger(
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
                return GatewayResult(
                    202,
                    {
                        "outcome": "pending-review",
                        "reason": decision.reason,
                        "run_key": run_key,
                    },
                )

            last_error = dispatch_with_retry(
                github_client=self.github_client,
                repo_full_name=repo_full_name,
                event_type=DISPATCH_EVENT_TYPE,
                client_payload=client_payload,
                delivery_id=delivery_id,
                actor=actor,
                issue_number=issue_number,
                run_key=run_key,
                retry_backoffs=DISPATCH_RETRY_BACKOFFS,
                logger=self.logger,
                sleep=self.sleep,
            )
            if last_error is not None:
                self.dedup_store.clear_active(prefix)
                self.logger(
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

            self.dedup_store.mark_completed(prefix, run_key, now_ms)
            self.logger(
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
            self.dedup_store.clear_active(prefix)
            self.logger(
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

    def _handle_issue_comment_event(
        self,
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
            trust_policy=self.trust_policy,
            github_client=self.github_client,
        )
        if decision.outcome == "denied":
            self.logger(
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
            context = self.github_client.get_issue_project_item_context(repo_full_name, int(issue_number))
        except GitHubApiError as exc:
            return GatewayResult(502, {"outcome": "error", "reason": f"Failed to resolve issue project context: {exc}"})

        eligibility_error = check_project_item_eligibility(context=context, requested_stage=requested_stage, repo_config=self.repo_config)
        if eligibility_error:
            self.logger(
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
                self.github_client.ensure_issue_label(repo_full_name, int(issue_number), "pending-review")
                self.logger(
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
                self.github_client.update_project_item_status(context.project_item_id, "In Progress")

            last_error = dispatch_with_retry(
                github_client=self.github_client,
                repo_full_name=repo_full_name,
                event_type=DISPATCH_EVENT_TYPE,
                client_payload=client_payload,
                delivery_id=delivery_id,
                actor=actor,
                issue_number=int(issue_number),
                run_key=run_key,
                retry_backoffs=DISPATCH_RETRY_BACKOFFS,
                logger=self.logger,
                sleep=self.sleep,
            )
            if last_error is not None:
                self.logger(
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

            self.logger(
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
            self.logger(
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

    def _valid_signature(self, signature: str, raw_body: bytes) -> bool:
        if not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(self.webhook_secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    def _extract_project_item_node_id(self, payload: dict[str, Any]) -> str | None:
        item = payload.get("projects_v2_item") or {}
        return item.get("node_id") or item.get("id")

    def _extract_status_transition(self, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        changes = payload.get("changes") or {}
        field_value = changes.get("field_value") or {}

        field_name = (
            field_value.get("field_name")
            or (field_value.get("field") or {}).get("name")
            or (field_value.get("project_field") or {}).get("name")
        )
        if field_name != "Status":
            return (None, None)

        before = self._extract_single_select_name(field_value.get("from"))
        after = (
            self._extract_single_select_name(field_value.get("to"))
            or self._extract_single_select_name((payload.get("projects_v2_item") or {}).get("field_value"))
        )
        return (before, after)

    def _extract_single_select_name(self, value: Any) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("name") or value.get("value") or value.get("label")
        return None
