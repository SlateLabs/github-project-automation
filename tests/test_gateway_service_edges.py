"""Edge-case tests for gateway webhook handling.

Covers paths in gateway/service.py, gateway/issue_comment_events.py, and
gateway/project_events.py that the main test_gateway_service.py does not exercise.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from gateway.app import GatewayApplication
from gateway.dedup import InMemoryDedupStore
from gateway.github_api import ConfiguredRepo, GitHubApiError, ProjectItemContext, TrustPolicy
from gateway.service import GatewayService
from gateway.stage_map import MANUAL_STAGES, REQUESTED_STAGE


# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------

class FakeGitHubClient:
    def __init__(self) -> None:
        self.context = ProjectItemContext(
            project_item_id="PVTI_123",
            item_type="Issue",
            issue_title="[TEST] Gateway dispatch",
            issue_number=1,
            issue_repo="SlateLabs/github-project-automation",
            issue_state="OPEN",
            issue_labels=(),
            repository_field_repo="SlateLabs/github-project-automation",
            repository_field_archived=False,
            status="Ready",
        )
        self.issue_context = ProjectItemContext(
            project_item_id="PVTI_123",
            item_type="Issue",
            issue_title="[TEST] Gateway dispatch",
            issue_number=1,
            issue_repo="SlateLabs/github-project-automation",
            issue_state="OPEN",
            issue_labels=(),
            repository_field_repo="SlateLabs/github-project-automation",
            repository_field_archived=False,
            status="In Review",
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
        self.status_updates: list[tuple[str, str]] = []
        self.dispatch_failures: int = 0
        self._context_error: GitHubApiError | None = None
        self._issue_context_error: GitHubApiError | None = None

    def get_project_item_context(self, item_node_id: str) -> ProjectItemContext:
        if self._context_error:
            raise self._context_error
        return self.context

    def get_issue_project_item_context(self, repo_full_name: str, issue_number: int) -> ProjectItemContext:
        if self._issue_context_error:
            raise self._issue_context_error
        return self.issue_context

    def get_actor_context(self, organization: str, repo_full_name: str, actor_login: str):
        data = self.actor_context[actor_login]
        return type("ActorContext", (), data)()

    def ensure_issue_label(self, repo_full_name: str, issue_number: int, label: str) -> None:
        self.labels_added.append((repo_full_name, issue_number, label))

    def update_project_item_status(self, project_item_id: str, status_name: str) -> None:
        self.status_updates.append((project_item_id, status_name))

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


SECRET = "test-secret"


@pytest.fixture()
def env():
    """Provides (github_client, service, app, logs, slept) tuple."""
    logs: list[dict[str, object]] = []
    slept: list[float] = []
    github = FakeGitHubClient()
    now_ms = 1_710_000_000_000
    service = GatewayService(
        webhook_secret=SECRET,
        github_client=github,
        repo_config={
            "SlateLabs/github-project-automation": ConfiguredRepo(
                repo="SlateLabs/github-project-automation",
                enabled_stages=(REQUESTED_STAGE, *MANUAL_STAGES),
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
        logger=logs.append,
        clock=lambda: now_ms,
        sleep=slept.append,
    )
    app = GatewayApplication(service)
    return github, service, app, logs, slept


def _send(app, event_name, payload, delivery_id="edge-delivery"):
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": event_name,
        "X-Hub-Signature-256": _signature(SECRET, raw_body),
    }
    return app.handle("POST", "/github/webhook", headers, raw_body)


def _send_raw(app, raw_body, event_name="issue_comment", delivery_id="edge-delivery"):
    """Send a raw (possibly non-JSON) body with valid signature."""
    headers = {
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": event_name,
        "X-Hub-Signature-256": _signature(SECRET, raw_body),
    }
    return app.handle("POST", "/github/webhook", headers, raw_body)


def _issue_comment_payload(
    *,
    action: str = "created",
    actor: str = "trusted-user",
    sender_type: str = "User",
    body: str = "gpa:feedback Tighten the merge gate",
    include_repo: bool = True,
    include_repo_url: bool = False,
) -> dict[str, object]:
    issue: dict[str, object] = {
        "number": 1,
        "title": "[TEST] Gateway dispatch",
    }
    if include_repo_url:
        issue["repository_url"] = "https://api.github.com/repos/SlateLabs/github-project-automation"
    payload: dict[str, object] = {
        "action": action,
        "issue": issue,
        "comment": {
            "body": body,
            "user": {"login": actor, "type": sender_type},
        },
        "sender": {"login": actor, "type": sender_type},
    }
    if include_repo:
        payload["repository"] = {"full_name": "SlateLabs/github-project-automation"}
    return payload


def _project_payload(*, node_id: str | None = "PVTI_123", actor: str = "trusted-user"):
    """Backlog -> Ready transition payload, optionally with no node_id."""
    item: dict[str, object] = {"field_value": {"name": "Ready"}}
    if node_id is not None:
        item["node_id"] = node_id
    return {
        "action": "edited",
        "projects_v2_item": item,
        "changes": {
            "field_value": {
                "field_name": "Status",
                "from": {"name": "Backlog"},
                "to": {"name": "Ready"},
            }
        },
        "sender": {"login": actor, "type": "User"},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_missing_delivery_header_returns_400(env):
    """Empty X-GitHub-Delivery must be rejected with 400."""
    github, service, app, logs, slept = env
    payload = _issue_comment_payload()
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-GitHub-Delivery": "",
        "X-GitHub-Event": "issue_comment",
        "X-Hub-Signature-256": _signature(SECRET, raw_body),
    }
    status, body = app.handle("POST", "/github/webhook", headers, raw_body)
    assert status == 400
    assert body["outcome"] == "rejected"
    assert "headers" in body["reason"].lower()


def test_invalid_json_body_returns_400(env):
    """Valid signature but non-JSON body must yield 400."""
    github, service, app, logs, slept = env
    raw_body = b"not json"
    status, body = _send_raw(app, raw_body)
    assert status == 400
    assert body["outcome"] == "rejected"
    assert "JSON" in body["reason"]


def test_issue_comment_action_edited_is_skipped(env):
    """issue_comment with action != 'created' must be skipped."""
    github, service, app, logs, slept = env
    payload = _issue_comment_payload(action="edited")
    status, body = _send(app, "issue_comment", payload)
    assert status == 202
    assert body["outcome"] == "skipped"
    assert github.dispatches == []


def test_issue_comment_missing_repo_context_returns_400(env):
    """Payload without repository.full_name and without issue.repository_url must return 400."""
    github, service, app, logs, slept = env
    payload = _issue_comment_payload(include_repo=False, include_repo_url=False)
    status, body = _send(app, "issue_comment", payload)
    assert status == 400
    assert body["outcome"] == "rejected"
    assert "missing" in body["reason"].lower()


def test_issue_comment_denied_actor_dropped(env):
    """An outsider sending gpa:feedback must be dropped (202)."""
    github, service, app, logs, slept = env
    payload = _issue_comment_payload(actor="outsider")
    status, body = _send(app, "issue_comment", payload, delivery_id="denied-actor")
    assert status == 202
    assert body["outcome"] == "dropped"
    assert github.dispatches == []


def test_issue_comment_api_error_on_project_context(env):
    """GitHubApiError from get_issue_project_item_context must yield 502."""
    github, service, app, logs, slept = env
    github._issue_context_error = GitHubApiError("GraphQL timeout")
    payload = _issue_comment_payload()
    status, body = _send(app, "issue_comment", payload, delivery_id="api-error-ctx")
    assert status == 502
    assert body["outcome"] == "error"
    assert "GraphQL timeout" in body["reason"]


def test_issue_comment_eligibility_rejection_do_not_automate(env):
    """Issue with do-not-automate label must be rejected with 422."""
    github, service, app, logs, slept = env
    github.issue_context = ProjectItemContext(
        **{**github.issue_context.__dict__, "issue_labels": ("do-not-automate",)}
    )
    payload = _issue_comment_payload()
    status, body = _send(app, "issue_comment", payload, delivery_id="no-automate")
    assert status == 422
    assert body["outcome"] == "rejected"
    assert "do-not-automate" in body["reason"]


def test_project_event_missing_node_id_returns_400(env):
    """projects_v2_item payload without node_id must yield 400."""
    github, service, app, logs, slept = env
    payload = _project_payload(node_id=None)
    status, body = _send(app, "projects_v2_item", payload, delivery_id="no-node-id")
    assert status == 400
    assert body["outcome"] == "rejected"
    assert "node id" in body["reason"].lower()


def test_project_event_api_error_on_context(env):
    """GitHubApiError from get_project_item_context must yield 502."""
    github, service, app, logs, slept = env
    github._context_error = GitHubApiError("API rate limit")
    payload = _project_payload()
    status, body = _send(app, "projects_v2_item", payload, delivery_id="api-error-proj")
    assert status == 502
    assert body["outcome"] == "error"
    assert "API rate limit" in body["reason"]


def test_project_event_dispatch_failure_clears_dedup(env):
    """All dispatch retries fail -> 502 and dedup prefix must be cleared."""
    github, service, app, logs, slept = env
    github.dispatch_failures = 3
    payload = _project_payload()
    status, body = _send(app, "projects_v2_item", payload, delivery_id="dispatch-fail-proj")
    assert status == 502
    assert body["outcome"] == "dispatch-failed"
    assert github.dispatches == []
    # Verify dedup was cleared so a future attempt is not blocked
    prefix = "SlateLabs/github-project-automation/1/kickoff"
    assert not service.dedup_store.has_active_run(prefix, 1_710_000_000_000)


def test_issue_comment_feedback_updates_project_status(env):
    """gpa:feedback dispatch must call update_project_item_status with 'In Progress'."""
    github, service, app, logs, slept = env
    payload = _issue_comment_payload(body="gpa:feedback Improve error handling")
    status, body = _send(app, "issue_comment", payload, delivery_id="feedback-status")
    assert status == 200
    assert body["outcome"] == "dispatched"
    assert github.status_updates == [("PVTI_123", "In Progress")]


def test_issue_comment_dispatch_failure_all_retries(env):
    """If dispatch fails all retries for issue_comment, expect 502."""
    github, service, app, logs, slept = env
    github.dispatch_failures = 3
    payload = _issue_comment_payload()
    status, body = _send(app, "issue_comment", payload, delivery_id="comment-dispatch-fail")
    assert status == 502
    assert body["outcome"] == "dispatch-failed"
    assert github.dispatches == []
    assert len(slept) == 3  # 3 backoff sleeps
