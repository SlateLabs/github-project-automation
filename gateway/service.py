"""Core webhook gateway logic for orchestration dispatch."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Callable

from gateway.dedup import InMemoryDedupStore
from gateway.github_api import (
    ConfiguredRepo,
    TrustPolicy,
)
from gateway.issue_comment_events import handle_issue_comment_event
from gateway.project_events import handle_project_event
from gateway.results import GatewayResult


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
            return handle_project_event(
                self,
                delivery_id=delivery_id,
                payload=payload,
                actor=actor,
                now_ms=now_ms,
            )

        if event_name == "issue_comment":
            return handle_issue_comment_event(
                self,
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
