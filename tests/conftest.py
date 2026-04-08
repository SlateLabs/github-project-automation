"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from gateway.github_api_models import (
    ActorContext,
    ConfiguredRepo,
    ProjectItemContext,
    TrustPolicy,
)


# ---------------------------------------------------------------------------
# Reusable factory defaults
# ---------------------------------------------------------------------------

REPO = "SlateLabs/test-repo"
ISSUE_NUMBER = 42

DEFAULT_ENABLED_STAGES = (
    "kickoff",
    "clarification",
    "design",
    "plan",
    "execution",
    "agent-review",
    "follow-up-capture",
    "merge",
    "closeout",
)


@pytest.fixture()
def trust_policy() -> TrustPolicy:
    return TrustPolicy(
        trusted_teams=(),
        trusted_users=("trusted-user",),
        trusted_apps=("12345",),
        record_only_roles=("member",),
        deny_roles=("outside_collaborator",),
    )


@pytest.fixture()
def repo_config() -> dict[str, ConfiguredRepo]:
    return {
        REPO: ConfiguredRepo(
            repo=REPO,
            enabled_stages=DEFAULT_ENABLED_STAGES,
            shared_workflow_version="v1",
        ),
    }


@pytest.fixture()
def project_item_context() -> ProjectItemContext:
    """A valid, eligible project item context."""
    return ProjectItemContext(
        project_item_id="PVTI_abc",
        item_type="Issue",
        issue_title="Test issue",
        issue_number=ISSUE_NUMBER,
        issue_repo=REPO,
        issue_state="OPEN",
        issue_labels=(),
        repository_field_repo=REPO,
        repository_field_archived=False,
        status="Ready",
    )


@pytest.fixture()
def actor_context_trusted() -> ActorContext:
    return ActorContext(
        login="trusted-user",
        org_role="admin",
        repo_permission="admin",
        repo_role_name="admin",
        is_org_member=True,
    )


@pytest.fixture()
def actor_context_member() -> ActorContext:
    return ActorContext(
        login="member-user",
        org_role="member",
        repo_permission="write",
        repo_role_name="write",
        is_org_member=True,
    )


@pytest.fixture()
def actor_context_outsider() -> ActorContext:
    return ActorContext(
        login="outsider",
        org_role=None,
        repo_permission="read",
        repo_role_name="read",
        is_org_member=False,
    )
