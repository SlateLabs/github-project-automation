from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gateway.github_api import ActorContext, ConfiguredRepo, ProjectItemContext, TrustPolicy
from gateway.stage_map import REQUESTED_STAGE


@dataclass(frozen=True)
class ActorDecision:
    outcome: str
    reason: str


def check_project_item_eligibility(
    *,
    context: ProjectItemContext,
    requested_stage: str,
    repo_config: dict[str, ConfiguredRepo],
) -> str | None:
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
    configured_repo = repo_config.get(context.repository_field_repo)
    if configured_repo is None:
        return f"Repository '{context.repository_field_repo}' is not configured in config/repos.yml"
    if requested_stage not in configured_repo.enabled_stages:
        return f"Repository '{context.repository_field_repo}' does not enable stage '{requested_stage}'"
    if requested_stage == REQUESTED_STAGE and context.status != "Ready":
        return f"Project Status must be 'Ready' for kickoff automation, found '{context.status or 'unset'}'"
    return None


def resolve_actor_decision(
    *,
    payload: dict[str, Any],
    actor_login: str,
    repo_full_name: str,
    trust_policy: TrustPolicy,
    github_client: Any,
) -> ActorDecision:
    installation = payload.get("installation") or {}
    app_id = installation.get("app_id")
    sender_type = (payload.get("sender") or {}).get("type")

    if sender_type == "Bot" or app_id is not None:
        if str(app_id) in trust_policy.trusted_apps:
            return ActorDecision("trusted", f"GitHub App {app_id} is allowlisted")
        return ActorDecision("denied", f"GitHub App {app_id or 'unknown'} is not allowlisted")

    owner = repo_full_name.split("/", 1)[0]
    actor_context: ActorContext = github_client.get_actor_context(owner, repo_full_name, actor_login)

    if actor_login in trust_policy.trusted_users:
        return ActorDecision("trusted", f"Actor '{actor_login}' is listed in trusted_users")
    if actor_context.org_role in trust_policy.deny_roles:
        return ActorDecision("denied", f"Actor '{actor_login}' has denied org role '{actor_context.org_role}'")
    if not actor_context.is_org_member and "outside_collaborator" in trust_policy.deny_roles:
        return ActorDecision("denied", f"Actor '{actor_login}' is outside the SlateLabs org")
    if actor_context.org_role in trust_policy.record_only_roles:
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


def log_fields(
    *,
    delivery_id: str,
    actor: str,
    repo: str,
    issue: int,
    run_key: str,
    outcome: str,
    requested_stage: str = REQUESTED_STAGE,
    reason: str | None = None,
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
