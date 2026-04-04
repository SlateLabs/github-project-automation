from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from gateway.app import GatewayApplication
from gateway.dedup import InMemoryDedupStore
from gateway.github_api import ConfiguredRepo, GitHubApiError, ProjectItemContext, TrustPolicy
from gateway.service import GatewayService


class FakeGitHubClient:
    def __init__(self) -> None:
        self.context = ProjectItemContext(
            project_item_id="PVTI_123",
            item_type="Issue",
            issue_number=1,
            issue_repo="SlateLabs/github-project-automation",
            issue_state="OPEN",
            issue_labels=(),
            repository_field_repo="SlateLabs/github-project-automation",
            repository_field_archived=False,
            status="Ready",
        )
        self.actor_context = {
            "trusted-user": {
                "login": "trusted-user",
                "org_role": "admin",
                "repo_permission": "admin",
                "repo_role_name": "admin",
                "is_org_member": True,
            },
            "member-user": {
                "login": "member-user",
                "org_role": "member",
                "repo_permission": "read",
                "repo_role_name": "read",
                "is_org_member": True,
            },
            "outsider": {
                "login": "outsider",
                "org_role": None,
                "repo_permission": None,
                "repo_role_name": None,
                "is_org_member": False,
            },
        }
        self.labels_added: list[tuple[str, int, str]] = []
        self.dispatches: list[tuple[str, str, dict[str, object]]] = []
        self.dispatch_failures: int = 0

    def get_project_item_context(self, item_node_id: str) -> ProjectItemContext:
        assert item_node_id == "PVTI_123"
        return self.context

    def get_actor_context(self, organization: str, repo_full_name: str, actor_login: str):
        data = self.actor_context[actor_login]
        return type("ActorContext", (), data)()

    def ensure_issue_label(self, repo_full_name: str, issue_number: int, label: str) -> None:
        self.labels_added.append((repo_full_name, issue_number, label))

    def dispatch_repository_event(
        self,
        repo_full_name: str,
        event_type: str,
        client_payload: dict[str, object],
    ) -> None:
        if self.dispatch_failures > 0:
            self.dispatch_failures -= 1
            raise GitHubApiError("dispatch failed (simulated)")
        self.dispatches.append((repo_full_name, event_type, client_payload))


def signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class GatewayServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logs: list[dict[str, object]] = []
        self.secret = "top-secret"
        self.github = FakeGitHubClient()
        self.now_ms = 1_710_000_000_000
        self.slept: list[float] = []
        self.service = GatewayService(
            webhook_secret=self.secret,
            github_client=self.github,
            repo_config={
                "SlateLabs/github-project-automation": ConfiguredRepo(
                    repo="SlateLabs/github-project-automation",
                    enabled_stages=("kickoff", "plan"),
                    shared_workflow_version="deadbeef",
                )
            },
            trust_policy=TrustPolicy(
                trusted_teams=("slatelabs-admins",),
                trusted_users=("trusted-user",),
                trusted_apps=(),
                record_only_roles=("member",),
                deny_roles=("outside_collaborator",),
            ),
            dedup_store=InMemoryDedupStore(),
            logger=self.logs.append,
            clock=lambda: self.now_ms,
            sleep=self.slept.append,
        )
        self.app = GatewayApplication(self.service)

    def _payload(self, *, actor: str = "trusted-user", transition_to: str = "Ready") -> dict[str, object]:
        return {
            "action": "edited",
            "projects_v2_item": {
                "node_id": "PVTI_123",
                "field_value": {"name": transition_to},
            },
            "changes": {
                "field_value": {
                    "field_name": "Status",
                    "from": {"name": "Backlog"},
                    "to": {"name": transition_to},
                }
            },
            "sender": {"login": actor, "type": "User"},
        }

    def _request(self, payload: dict[str, object], delivery_id: str = "delivery-1") -> tuple[int, dict[str, object]]:
        raw_body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "projects_v2_item",
            "X-Hub-Signature-256": signature(self.secret, raw_body),
        }
        return self.app.handle("POST", "/github/webhook", headers, raw_body)

    def test_rejects_invalid_signature(self) -> None:
        payload = self._payload()
        raw_body = json.dumps(payload).encode("utf-8")
        status, body = self.app.handle(
            "POST",
            "/github/webhook",
            {
                "X-GitHub-Delivery": "delivery-1",
                "X-GitHub-Event": "projects_v2_item",
                "X-Hub-Signature-256": "sha256=bad",
            },
            raw_body,
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["outcome"], "rejected")

    def test_skips_unsupported_transition(self) -> None:
        status, body = self._request(self._payload(transition_to="In Progress"))
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "skipped")
        self.assertEqual(self.github.dispatches, [])

    def test_skips_workflow_status_field_transition(self) -> None:
        payload = {
            "action": "edited",
            "projects_v2_item": {
                "node_id": "PVTI_123",
                "field_value": {"name": "Ready"},
            },
            "changes": {
                "field_value": {
                    "field_name": "Workflow Status",
                    "from": {"name": "Backlog"},
                    "to": {"name": "Ready"},
                }
            },
            "sender": {"login": "trusted-user", "type": "User"},
        }
        status, body = self._request(payload)
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "skipped")

    def test_skips_unsupported_event_type(self) -> None:
        payload = self._payload()
        raw_body = json.dumps(payload).encode("utf-8")
        status, body = self.app.handle(
            "POST",
            "/github/webhook",
            {
                "X-GitHub-Delivery": "delivery-event",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": signature(self.secret, raw_body),
            },
            raw_body,
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "skipped")

    def test_rejects_missing_repository_field(self) -> None:
        self.github.context = ProjectItemContext(
            **{**self.github.context.__dict__, "repository_field_repo": None}
        )
        status, body = self._request(self._payload())
        self.assertEqual(status, 422)
        self.assertIn("Repository field is unset", body["reason"])

    def test_rejects_non_issue_project_items(self) -> None:
        self.github.context = ProjectItemContext(
            **{**self.github.context.__dict__, "item_type": "DraftIssue"}
        )
        status, body = self._request(self._payload())
        self.assertEqual(status, 422)
        self.assertIn("must resolve to an Issue", body["reason"])

    def test_rejects_missing_linked_issue(self) -> None:
        self.github.context = ProjectItemContext(
            **{**self.github.context.__dict__, "issue_number": None, "issue_repo": None}
        )
        status, body = self._request(self._payload())
        self.assertEqual(status, 422)
        self.assertIn("does not link to a canonical source issue", body["reason"])

    def test_dispatches_for_trusted_actor(self) -> None:
        status, body = self._request(self._payload())
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "dispatched")
        self.assertEqual(len(self.github.dispatches), 1)
        repo, event_type, client_payload = self.github.dispatches[0]
        self.assertEqual(repo, "SlateLabs/github-project-automation")
        self.assertEqual(event_type, "orchestration-start")
        self.assertEqual(
            client_payload,
            {
                "issue_number": 1,
                "requested_stage": "kickoff",
                "run_key": body["run_key"],
                "actor": "trusted-user",
                "timestamp": "1710000000000",
            },
        )

    def test_accepts_ping_event(self) -> None:
        payload = {"zen": "Practicality beats purity.", "sender": {"login": "trusted-user", "type": "User"}}
        raw_body = json.dumps(payload).encode("utf-8")
        status, body = self.app.handle(
            "POST",
            "/github/webhook",
            {
                "X-Github-Delivery": "delivery-ping",
                "X-Github-Event": "ping",
                "X-Hub-Signature-256": signature(self.secret, raw_body),
            },
            raw_body,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, {"outcome": "accepted", "event": "ping"})

    def test_headers_are_case_insensitive(self) -> None:
        payload = self._payload()
        raw_body = json.dumps(payload).encode("utf-8")
        status, body = self.app.handle(
            "POST",
            "/github/webhook",
            {
                "X-Github-Delivery": "delivery-mixed-case",
                "X-Github-Event": "projects_v2_item",
                "X-Hub-Signature-256": signature(self.secret, raw_body),
            },
            raw_body,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "dispatched")

    def test_record_only_actor_gets_pending_review(self) -> None:
        status, body = self._request(self._payload(actor="member-user"))
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "pending-review")
        self.assertEqual(self.github.dispatches, [])
        self.assertEqual(
            self.github.labels_added,
            [("SlateLabs/github-project-automation", 1, "pending-review")],
        )

    def test_denied_actor_is_dropped(self) -> None:
        status, body = self._request(self._payload(actor="outsider"))
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "dropped")
        self.assertEqual(self.github.dispatches, [])
        self.assertEqual(self.github.labels_added, [])

    def test_org_admin_without_explicit_allowlist_is_dropped(self) -> None:
        self.github.actor_context["org-admin"] = {
            "login": "org-admin",
            "org_role": "admin",
            "repo_permission": "admin",
            "repo_role_name": "admin",
            "is_org_member": True,
        }
        status, body = self._request(self._payload(actor="org-admin"))
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "dropped")
        self.assertIn("trusted_teams resolution remains deferred", body["reason"])
        self.assertEqual(self.github.dispatches, [])

    def test_duplicate_active_run_is_deduplicated(self) -> None:
        prefix = "SlateLabs/github-project-automation/1/kickoff"
        self.service.dedup_store.mark_active(prefix, "old-run", self.now_ms)
        status, body = self._request(self._payload())
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "deduplicated")
        self.assertEqual(self.github.dispatches, [])

    def test_recent_completion_is_deduplicated(self) -> None:
        prefix = "SlateLabs/github-project-automation/1/kickoff"
        self.service.dedup_store.mark_completed(prefix, "old-run", self.now_ms)
        status, body = self._request(self._payload())
        self.assertEqual(status, 202)
        self.assertEqual(body["outcome"], "deduplicated")
        self.assertEqual(self.github.dispatches, [])

    def test_duplicate_delivery_id_is_deduplicated(self) -> None:
        first = self._request(self._payload(), delivery_id="same-delivery")
        second = self._request(self._payload(), delivery_id="same-delivery")
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 202)
        self.assertEqual(second[1]["outcome"], "deduplicated")

    def test_health_endpoint(self) -> None:
        status, body = self.app.handle("GET", "/healthz", {}, b"")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})

    def test_health_endpoint_allows_trailing_slash(self) -> None:
        status, body = self.app.handle("GET", "/healthz/", {}, b"")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})

    # --- Blocker 1: record-only must not poison dedup window ---

    def test_record_only_does_not_block_subsequent_trusted_dispatch(self) -> None:
        """Approval flow: record-only actor triggers pending-review, then a
        trusted actor re-triggers the same prefix within the 60s dedup window
        and gets a successful dispatch (not deduplicated)."""
        # Step 1: member-user triggers record-only / pending-review
        status1, body1 = self._request(self._payload(actor="member-user"), delivery_id="d-member")
        self.assertEqual(status1, 202)
        self.assertEqual(body1["outcome"], "pending-review")

        # Step 2: trusted-user re-triggers the same prefix within the dedup window
        self.now_ms += 5_000  # 5 seconds later
        status2, body2 = self._request(self._payload(actor="trusted-user"), delivery_id="d-trusted")
        self.assertEqual(status2, 200)
        self.assertEqual(body2["outcome"], "dispatched")
        self.assertEqual(len(self.github.dispatches), 1)

    def test_record_only_clears_active_run(self) -> None:
        """record-only path must clear its active-run slot so it doesn't block
        subsequent dispatches via the active-run check either."""
        prefix = "SlateLabs/github-project-automation/1/kickoff"
        self._request(self._payload(actor="member-user"), delivery_id="d-ro")
        self.assertFalse(self.service.dedup_store.has_active_run(prefix, self.now_ms))
        self.assertFalse(self.service.dedup_store.has_recent_completion(prefix, self.now_ms))

    # --- Blocker 2: dispatch retry/backoff ---

    def test_dispatch_retries_on_transient_failure_then_succeeds(self) -> None:
        """If the first dispatch attempt fails, retry with backoff and succeed."""
        self.github.dispatch_failures = 2  # fail twice, succeed on 3rd
        status, body = self._request(self._payload())
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "dispatched")
        self.assertEqual(len(self.github.dispatches), 1)
        self.assertEqual(self.slept, [1.0, 4.0])

    def test_dispatch_terminal_failure_after_all_retries(self) -> None:
        """If all 3 retry attempts fail, return dispatch-failed."""
        self.github.dispatch_failures = 3  # fail all 3 attempts
        status, body = self._request(self._payload())
        self.assertEqual(status, 502)
        self.assertEqual(body["outcome"], "dispatch-failed")
        self.assertEqual(self.github.dispatches, [])
        self.assertEqual(self.slept, [1.0, 4.0, 16.0])

    def test_dispatch_retry_backoff_sequence(self) -> None:
        """Backoff durations must be exactly 1s, 4s, 16s."""
        self.github.dispatch_failures = 3
        self._request(self._payload())
        self.assertEqual(self.slept, [1.0, 4.0, 16.0])

    def test_dispatch_retry_logs_each_attempt(self) -> None:
        """Each retry attempt is logged with attempt number and backoff."""
        self.github.dispatch_failures = 2
        self._request(self._payload())
        retry_logs = [log for log in self.logs if log.get("outcome") == "dispatch-retry"]
        self.assertEqual(len(retry_logs), 2)
        self.assertEqual(retry_logs[0]["attempt"], 1)
        self.assertEqual(retry_logs[0]["backoff_s"], 1.0)
        self.assertEqual(retry_logs[1]["attempt"], 2)
        self.assertEqual(retry_logs[1]["backoff_s"], 4.0)

    def test_dispatch_terminal_failure_clears_active_run(self) -> None:
        """After terminal dispatch failure, the active run is cleared so the
        prefix is not permanently locked."""
        prefix = "SlateLabs/github-project-automation/1/kickoff"
        self.github.dispatch_failures = 3
        self._request(self._payload())
        self.assertFalse(self.service.dedup_store.has_active_run(prefix, self.now_ms))
        self.assertFalse(self.service.dedup_store.has_recent_completion(prefix, self.now_ms))


if __name__ == "__main__":
    unittest.main()
