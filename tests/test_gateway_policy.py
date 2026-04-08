"""Tests for gateway.policy — eligibility checks and actor decisions."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from gateway.github_api_models import ActorContext, ConfiguredRepo, ProjectItemContext, TrustPolicy
from gateway.policy import ActorDecision, check_project_item_eligibility, log_fields, resolve_actor_decision
from tests.conftest import DEFAULT_ENABLED_STAGES, ISSUE_NUMBER, REPO


# ---------------------------------------------------------------------------
# check_project_item_eligibility
# ---------------------------------------------------------------------------


class TestCheckProjectItemEligibility:
    """Validates every rejection branch in check_project_item_eligibility."""

    def test_eligible_item_returns_none(self, project_item_context, repo_config):
        assert check_project_item_eligibility(
            context=project_item_context,
            requested_stage="kickoff",
            repo_config=repo_config,
        ) is None

    def test_rejects_non_issue_item_type(self, project_item_context, repo_config):
        ctx = replace(project_item_context, item_type="PullRequest")
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "Issue" in result

    def test_rejects_missing_issue_number(self, project_item_context, repo_config):
        ctx = replace(project_item_context, issue_number=None)
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "canonical source issue" in result

    def test_rejects_missing_issue_repo(self, project_item_context, repo_config):
        ctx = replace(project_item_context, issue_repo="")
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "canonical source issue" in result

    def test_rejects_closed_issue(self, project_item_context, repo_config):
        ctx = replace(project_item_context, issue_state="CLOSED")
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "not open" in result

    def test_rejects_do_not_automate_label(self, project_item_context, repo_config):
        ctx = replace(project_item_context, issue_labels=("do-not-automate",))
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "do-not-automate" in result

    def test_rejects_missing_repository_field(self, project_item_context, repo_config):
        ctx = replace(project_item_context, repository_field_repo=None)
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "Repository field is unset" in result

    def test_rejects_archived_repository_field(self, project_item_context, repo_config):
        ctx = replace(project_item_context, repository_field_archived=True)
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "archived" in result

    def test_rejects_repo_mismatch(self, project_item_context, repo_config):
        ctx = replace(project_item_context, issue_repo="SlateLabs/other-repo")
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "other-repo" in result

    def test_rejects_unconfigured_repo(self, project_item_context):
        result = check_project_item_eligibility(
            context=project_item_context,
            requested_stage="kickoff",
            repo_config={},
        )
        assert "not configured" in result

    def test_rejects_disabled_stage(self, project_item_context):
        config = {
            REPO: ConfiguredRepo(
                repo=REPO,
                enabled_stages=("design",),
                shared_workflow_version="v1",
            )
        }
        result = check_project_item_eligibility(
            context=project_item_context,
            requested_stage="kickoff",
            repo_config=config,
        )
        assert "does not enable stage" in result

    def test_rejects_non_ready_status_for_kickoff(self, project_item_context, repo_config):
        ctx = replace(project_item_context, status="In Progress")
        result = check_project_item_eligibility(context=ctx, requested_stage="kickoff", repo_config=repo_config)
        assert "Ready" in result

    def test_non_kickoff_stage_allows_any_status(self, project_item_context, repo_config):
        ctx = replace(project_item_context, status="In Progress")
        assert check_project_item_eligibility(
            context=ctx,
            requested_stage="design",
            repo_config=repo_config,
        ) is None


# ---------------------------------------------------------------------------
# resolve_actor_decision
# ---------------------------------------------------------------------------


class TestResolveActorDecision:
    """Validates actor trust resolution paths."""

    def _make_payload(self, *, sender_type="User", app_id=None):
        payload: dict = {"sender": {"type": sender_type}}
        if app_id is not None:
            payload["installation"] = {"app_id": app_id}
        return payload

    def test_trusted_app_allowed(self, trust_policy):
        client = MagicMock()
        decision = resolve_actor_decision(
            payload=self._make_payload(sender_type="Bot", app_id=12345),
            actor_login="bot[bot]",
            repo_full_name=REPO,
            trust_policy=trust_policy,
            github_client=client,
        )
        assert decision.outcome == "trusted"

    def test_untrusted_app_denied(self, trust_policy):
        client = MagicMock()
        decision = resolve_actor_decision(
            payload=self._make_payload(sender_type="Bot", app_id=99999),
            actor_login="other-bot[bot]",
            repo_full_name=REPO,
            trust_policy=trust_policy,
            github_client=client,
        )
        assert decision.outcome == "denied"

    def test_trusted_user_allowed(self, trust_policy, actor_context_trusted):
        client = MagicMock()
        client.get_actor_context.return_value = actor_context_trusted
        decision = resolve_actor_decision(
            payload=self._make_payload(),
            actor_login="trusted-user",
            repo_full_name=REPO,
            trust_policy=trust_policy,
            github_client=client,
        )
        assert decision.outcome == "trusted"

    def test_member_gets_record_only(self, trust_policy, actor_context_member):
        client = MagicMock()
        client.get_actor_context.return_value = actor_context_member
        decision = resolve_actor_decision(
            payload=self._make_payload(),
            actor_login="member-user",
            repo_full_name=REPO,
            trust_policy=trust_policy,
            github_client=client,
        )
        assert decision.outcome == "record-only"

    def test_outsider_denied(self, trust_policy, actor_context_outsider):
        client = MagicMock()
        client.get_actor_context.return_value = actor_context_outsider
        decision = resolve_actor_decision(
            payload=self._make_payload(),
            actor_login="outsider",
            repo_full_name=REPO,
            trust_policy=trust_policy,
            github_client=client,
        )
        assert decision.outcome == "denied"

    def test_denied_org_role(self, trust_policy):
        policy = TrustPolicy(
            trusted_teams=(),
            trusted_users=(),
            trusted_apps=(),
            record_only_roles=(),
            deny_roles=("billing_manager",),
        )
        client = MagicMock()
        client.get_actor_context.return_value = ActorContext(
            login="billing-user",
            org_role="billing_manager",
            repo_permission="read",
            repo_role_name="read",
            is_org_member=True,
        )
        decision = resolve_actor_decision(
            payload=self._make_payload(),
            actor_login="billing-user",
            repo_full_name=REPO,
            trust_policy=policy,
            github_client=client,
        )
        assert decision.outcome == "denied"
        assert "billing_manager" in decision.reason

    def test_app_id_detected_via_installation_field(self, trust_policy):
        """A human sender with an installation block still routes through app logic."""
        client = MagicMock()
        decision = resolve_actor_decision(
            payload=self._make_payload(sender_type="User", app_id=12345),
            actor_login="some-user",
            repo_full_name=REPO,
            trust_policy=trust_policy,
            github_client=client,
        )
        assert decision.outcome == "trusted"


# ---------------------------------------------------------------------------
# log_fields
# ---------------------------------------------------------------------------


class TestLogFields:

    def test_includes_all_required_fields(self):
        fields = log_fields(
            delivery_id="d1",
            actor="alice",
            repo=REPO,
            issue=ISSUE_NUMBER,
            run_key="rk",
            outcome="dispatched",
        )
        assert fields["delivery_id"] == "d1"
        assert fields["actor"] == "alice"
        assert fields["issue"] == ISSUE_NUMBER
        assert "reason" not in fields

    def test_includes_reason_when_provided(self):
        fields = log_fields(
            delivery_id="d1",
            actor="alice",
            repo=REPO,
            issue=ISSUE_NUMBER,
            run_key="rk",
            outcome="rejected",
            reason="not eligible",
        )
        assert fields["reason"] == "not eligible"
