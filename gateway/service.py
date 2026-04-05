"""Core webhook gateway logic for kickoff-trigger dispatch."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from gateway.dedup import InMemoryDedupStore
from gateway.github_api import (
    ActorContext,
    ConfiguredRepo,
    GitHubApiError,
    ProjectItemContext,
    TrustPolicy,
)
from gateway.orchestration_contract import OperatorCommandType, parse_operator_command
from gateway.orchestration_contract import find_latest_review_ready_marker_ms, select_latest_operator_command


REQUESTED_STAGE = "kickoff"
DISPATCH_EVENT_TYPE = "orchestration-start"
DISPATCH_RETRY_BACKOFFS = (1.0, 4.0, 16.0)
OPERATOR_COMMAND_STAGE = {
    OperatorCommandType.FEEDBACK: "execution",
    OperatorCommandType.APPROVE: "merge",
}


@dataclass(frozen=True)
class GatewayResult:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ActorDecision:
    outcome: str
    reason: str


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

        if event_name != "projects_v2_item":
            if event_name == "issue_comment":
                return self._handle_operator_command(payload, delivery_id, actor)
            self.logger(
                {
                    "delivery_id": delivery_id,
                    "event": event_name,
                    "actor": actor,
                    "outcome": "skipped",
                    "reason": "unsupported event",
                }
            )
            return GatewayResult(202, {"outcome": "skipped", "reason": "Only projects_v2_item events are supported"})

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

        eligibility_error = self._check_eligibility(context)
        if eligibility_error:
            self.logger(
                {
                    "delivery_id": delivery_id,
                    "event": event_name,
                    "actor": actor,
                    "repo": context.repository_field_repo,
                    "issue": context.issue_number,
                    "requested_stage": REQUESTED_STAGE,
                    "outcome": "rejected",
                    "reason": eligibility_error,
                }
            )
            return GatewayResult(422, {"outcome": "rejected", "reason": eligibility_error})

        repo_full_name = context.repository_field_repo or ""
        issue_number = int(context.issue_number or 0)
        run_key = f"{repo_full_name}/{issue_number}/{REQUESTED_STAGE}/{now_ms}"
        prefix = f"{repo_full_name}/{issue_number}/{REQUESTED_STAGE}"

        decision = self._resolve_actor_decision(payload, actor, repo_full_name)
        if decision.outcome == "denied":
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    run_key=run_key,
                    outcome="dropped",
                    reason=decision.reason,
                )
            )
            return GatewayResult(202, {"outcome": "dropped", "reason": decision.reason, "run_key": run_key})

        if self.dedup_store.has_active_run(prefix, now_ms):
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    run_key=run_key,
                    outcome="deduplicated",
                    reason="active run already exists",
                )
            )
            return GatewayResult(202, {"outcome": "deduplicated", "reason": "An active kickoff run already exists", "run_key": run_key})

        if self.dedup_store.has_recent_completion(prefix, now_ms):
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
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
            "requested_stage": REQUESTED_STAGE,
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
                    self._log_fields(
                        delivery_id=delivery_id,
                        actor=actor,
                        repo=repo_full_name,
                        issue=issue_number,
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

            last_error = self._dispatch_with_retry(repo_full_name, client_payload, delivery_id, actor, issue_number, run_key)
            if last_error is not None:
                self.dedup_store.clear_active(prefix)
                self.logger(
                    self._log_fields(
                        delivery_id=delivery_id,
                        actor=actor,
                        repo=repo_full_name,
                        issue=issue_number,
                        run_key=run_key,
                        outcome="dispatch-failed",
                        reason=str(last_error),
                    )
                )
                return GatewayResult(502, {"outcome": "dispatch-failed", "reason": str(last_error), "run_key": run_key})

            self.dedup_store.mark_completed(prefix, run_key, now_ms)
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    run_key=run_key,
                    outcome="dispatched",
                )
            )
            return GatewayResult(200, {"outcome": "dispatched", "run_key": run_key, "payload": client_payload})
        except GitHubApiError as exc:
            self.dedup_store.clear_active(prefix)
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    run_key=run_key,
                    outcome="error",
                    reason=str(exc),
                )
            )
            return GatewayResult(502, {"outcome": "error", "reason": str(exc), "run_key": run_key})

    def _handle_operator_command(self, payload: dict[str, Any], delivery_id: str, actor: str) -> GatewayResult:
        action = str(payload.get("action") or "")
        if action not in {"created", "edited"}:
            return GatewayResult(202, {"outcome": "skipped", "reason": "Only created/edited issue comments are supported"})

        issue = payload.get("issue") or {}
        if issue.get("pull_request"):
            return GatewayResult(202, {"outcome": "skipped", "reason": "PR review loop commands must be posted on the source issue"})

        repo_full_name = str((payload.get("repository") or {}).get("full_name") or "")
        issue_number = int(issue.get("number") or 0)
        comment = payload.get("comment") or {}
        comment_id = int(comment.get("id") or 0)
        body = str(comment.get("body") or "")

        parsed = parse_operator_command(body)
        if parsed is None:
            return GatewayResult(202, {"outcome": "skipped", "reason": "No structured operator command found"})
        hinted_command_type, _ = parsed
        requested_stage = OPERATOR_COMMAND_STAGE[hinted_command_type]
        if not repo_full_name or issue_number <= 0 or comment_id <= 0:
            return GatewayResult(400, {"outcome": "rejected", "reason": "issue_comment payload is missing repository, issue number, or comment id"})

        if repo_full_name not in self.repo_config:
            return GatewayResult(202, {"outcome": "skipped", "reason": f"Repository '{repo_full_name}' is not configured in config/repos.yml"})

        decision = self._resolve_actor_decision(payload, actor, repo_full_name)
        if decision.outcome != "trusted":
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    run_key=f"{repo_full_name}/{issue_number}/{requested_stage}/{self.clock()}",
                    outcome="dropped",
                    reason=decision.reason,
                    requested_stage=requested_stage,
                )
            )
            return GatewayResult(202, {"outcome": "dropped", "reason": decision.reason})

        try:
            comments = self.github_client.get_issue_comments(repo_full_name, issue_number)
        except GitHubApiError as exc:
            return GatewayResult(502, {"outcome": "error", "reason": f"Failed to query issue comments: {exc}"})

        latest_review_ready_ms = find_latest_review_ready_marker_ms(comments)
        if latest_review_ready_ms is None:
            return GatewayResult(
                422,
                {
                    "outcome": "rejected",
                    "reason": f"No 'gpa:review-ready' marker found on issue #{issue_number}",
                },
            )

        selected = select_latest_operator_command(
            comments=comments,
            trusted_users=set(self.trust_policy.trusted_users),
            review_ready_after_ms=latest_review_ready_ms,
        )
        if selected is None:
            return GatewayResult(
                202,
                {
                    "outcome": "skipped",
                    "reason": "No valid trusted operator command found after latest review-ready marker",
                },
            )
        if selected.comment_id != comment_id:
            return GatewayResult(
                202,
                {
                    "outcome": "skipped",
                    "reason": f"Command comment #{comment_id} is stale; latest valid command is comment #{selected.comment_id}",
                },
            )

        requested_stage = OPERATOR_COMMAND_STAGE[selected.command_type]
        configured_repo = self.repo_config[repo_full_name]
        if requested_stage not in configured_repo.enabled_stages:
            return GatewayResult(
                422,
                {
                    "outcome": "rejected",
                    "reason": f"Repository '{repo_full_name}' does not enable stage '{requested_stage}'",
                },
            )

        comment_key = f"{repo_full_name}/{issue_number}/{comment_id}"
        now_ms = self.clock()
        if self.dedup_store.seen_operator_comment(comment_key, now_ms):
            return GatewayResult(
                202,
                {
                    "outcome": "deduplicated",
                    "reason": f"Command comment #{comment_id} has already been processed",
                },
            )

        run_key = f"{repo_full_name}/{issue_number}/{requested_stage}/{now_ms}"
        client_payload: dict[str, object] = {
            "issue_number": issue_number,
            "requested_stage": requested_stage,
            "run_key": run_key,
            "actor": actor,
            "timestamp": str(now_ms),
            "source_comment_id": comment_id,
            "source_command": selected.command_type.value,
        }
        if selected.command_type == OperatorCommandType.FEEDBACK and selected.instructions:
            client_payload["feedback_instructions"] = selected.instructions

        last_error = self._dispatch_with_retry(repo_full_name, client_payload, delivery_id, actor, issue_number, run_key)
        if last_error is not None:
            self.logger(
                self._log_fields(
                    delivery_id=delivery_id,
                    actor=actor,
                    repo=repo_full_name,
                    issue=issue_number,
                    run_key=run_key,
                    outcome="dispatch-failed",
                    reason=str(last_error),
                    requested_stage=requested_stage,
                )
            )
            return GatewayResult(502, {"outcome": "dispatch-failed", "reason": str(last_error), "run_key": run_key})

        self.logger(
            self._log_fields(
                delivery_id=delivery_id,
                actor=actor,
                repo=repo_full_name,
                issue=issue_number,
                run_key=run_key,
                outcome="dispatched",
                requested_stage=requested_stage,
            )
        )
        return GatewayResult(
            200,
            {
                "outcome": "dispatched",
                "run_key": run_key,
                "payload": client_payload,
            },
        )

    def _dispatch_with_retry(
        self,
        repo_full_name: str,
        client_payload: dict[str, Any],
        delivery_id: str,
        actor: str,
        issue_number: int,
        run_key: str,
    ) -> GitHubApiError | None:
        """Attempt repository_dispatch with exponential backoff.

        Returns None on success, or the last GitHubApiError after all
        retries are exhausted.
        """
        last_error: GitHubApiError | None = None
        for attempt, backoff in enumerate(DISPATCH_RETRY_BACKOFFS):
            try:
                self.github_client.dispatch_repository_event(
                    repo_full_name,
                    DISPATCH_EVENT_TYPE,
                    client_payload,
                )
                return None
            except GitHubApiError as exc:
                last_error = exc
                self.logger(
                    {
                        "delivery_id": delivery_id,
                        "actor": actor,
                        "repo": repo_full_name,
                        "issue": issue_number,
                        "run_key": run_key,
                        "outcome": "dispatch-retry",
                        "attempt": attempt + 1,
                        "backoff_s": backoff,
                        "reason": str(exc),
                    }
                )
                self.sleep(backoff)
        return last_error

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

    def _check_eligibility(self, context: ProjectItemContext) -> str | None:
        if context.item_type != "Issue":
            return f"Project item must resolve to an Issue, found '{context.item_type}'"
        if context.issue_number is None or not context.issue_repo:
            return "Project item does not link to a canonical source issue"
        if context.issue_state != "OPEN":
            return f"Source issue #{context.issue_number} is not open"
        if "do-not-automate" in context.issue_labels:
            return f"Source issue #{context.issue_number} has do-not-automate label"
        if not context.repository_field_repo:
            return "Repository field is unset on the project item"
        if context.repository_field_archived:
            return f"Repository field points to archived repo '{context.repository_field_repo}'"
        if context.issue_repo != context.repository_field_repo:
            return (
                f"Repository field points to '{context.repository_field_repo}', "
                f"but the linked issue belongs to '{context.issue_repo}'"
            )

        configured_repo = self.repo_config.get(context.repository_field_repo)
        if configured_repo is None:
            return f"Repository '{context.repository_field_repo}' is not configured in config/repos.yml"
        if REQUESTED_STAGE not in configured_repo.enabled_stages:
            return f"Repository '{context.repository_field_repo}' does not enable stage '{REQUESTED_STAGE}'"
        if context.status != "Ready":
            return f"Project Status must be 'Ready' for kickoff automation, found '{context.status or 'unset'}'"
        return None

    def _resolve_actor_decision(
        self,
        payload: dict[str, Any],
        actor_login: str,
        repo_full_name: str,
    ) -> ActorDecision:
        installation = payload.get("installation") or {}
        app_id = installation.get("app_id")
        sender_type = (payload.get("sender") or {}).get("type")

        if sender_type == "Bot" or app_id is not None:
            if str(app_id) in self.trust_policy.trusted_apps:
                return ActorDecision("trusted", f"GitHub App {app_id} is allowlisted")
            return ActorDecision("denied", f"GitHub App {app_id or 'unknown'} is not allowlisted")

        owner = repo_full_name.split("/", 1)[0]
        actor_context: ActorContext = self.github_client.get_actor_context(owner, repo_full_name, actor_login)

        if actor_login in self.trust_policy.trusted_users:
            return ActorDecision("trusted", f"Actor '{actor_login}' is listed in trusted_users")
        if actor_context.org_role in self.trust_policy.deny_roles:
            return ActorDecision("denied", f"Actor '{actor_login}' has denied org role '{actor_context.org_role}'")
        if not actor_context.is_org_member and "outside_collaborator" in self.trust_policy.deny_roles:
            return ActorDecision("denied", f"Actor '{actor_login}' is outside the SlateLabs org")
        if actor_context.org_role in self.trust_policy.record_only_roles:
            return ActorDecision(
                "record-only",
                f"Actor '{actor_login}' is org role '{actor_context.org_role}' and requires trusted review",
            )
        return ActorDecision(
            "denied",
            (
                f"Actor '{actor_login}' is not explicitly trusted for kickoff automation. "
                "trusted_teams resolution remains deferred to issue #5."
            ),
        )

    def _log_fields(
        self,
        *,
        delivery_id: str,
        actor: str,
        repo: str,
        issue: int,
        run_key: str,
        outcome: str,
        reason: str | None = None,
        requested_stage: str = REQUESTED_STAGE,
    ) -> dict[str, Any]:
        fields = {
            "delivery_id": delivery_id,
            "actor": actor,
            "repo": repo,
            "issue": issue,
            "requested_stage": requested_stage,
            "run_key": run_key,
            "outcome": outcome,
        }
        if reason:
            fields["reason"] = reason
        return fields
