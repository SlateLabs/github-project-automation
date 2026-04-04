"""GitHub API adapter used by the webhook gateway."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import error, request

import jwt
import yaml


class GitHubApiError(RuntimeError):
    """Raised when a GitHub API call fails."""


@dataclass(frozen=True)
class ConfiguredRepo:
    repo: str
    enabled_stages: tuple[str, ...]
    shared_workflow_version: str


@dataclass(frozen=True)
class TrustPolicy:
    trusted_teams: tuple[str, ...]
    trusted_users: tuple[str, ...]
    trusted_apps: tuple[str, ...]
    record_only_roles: tuple[str, ...]
    deny_roles: tuple[str, ...]


@dataclass(frozen=True)
class GitHubAppCredentials:
    app_id: str
    installation_id: str
    private_key_pem: str


@dataclass(frozen=True)
class ProjectItemContext:
    project_item_id: str
    item_type: str
    issue_number: int | None
    issue_repo: str | None
    issue_state: str | None
    issue_labels: tuple[str, ...]
    repository_field_repo: str | None
    repository_field_archived: bool
    workflow_status: str | None


@dataclass(frozen=True)
class ActorContext:
    login: str
    org_role: str | None
    repo_permission: str | None
    repo_role_name: str | None
    is_org_member: bool


def load_repo_config(path: str) -> dict[str, ConfiguredRepo]:
    with open(path, "r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}

    repos = {}
    for entry in doc.get("repos", []):
        repo = entry["repo"]
        repos[repo] = ConfiguredRepo(
            repo=repo,
            enabled_stages=tuple(entry.get("enabled_stages", [])),
            shared_workflow_version=entry["shared_workflow_version"],
        )
    return repos


def load_trust_policy(path: str) -> TrustPolicy:
    with open(path, "r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}

    return TrustPolicy(
        trusted_teams=tuple(str(value) for value in doc.get("trusted_teams", [])),
        trusted_users=tuple(str(value) for value in doc.get("trusted_users", [])),
        trusted_apps=tuple(str(value) for value in doc.get("trusted_apps", [])),
        record_only_roles=tuple(str(value) for value in doc.get("record_only_roles", [])),
        deny_roles=tuple(str(value) for value in doc.get("deny_roles", [])),
    )


class GitHubApiClient:
    """Thin REST/GraphQL client for the gateway listener."""

    def __init__(
        self,
        token: str | None = None,
        *,
        app_credentials: GitHubAppCredentials | None = None,
        api_url: str = "https://api.github.com",
        clock: Callable[[], float] | None = None,
    ) -> None:
        if bool(token) == bool(app_credentials):
            raise ValueError("Provide exactly one of token or app_credentials")
        self.token = token
        self.app_credentials = app_credentials
        self.api_url = api_url.rstrip("/")
        self.clock = clock or time.time
        self._installation_token: str | None = None
        self._installation_token_expires_at: float = 0.0

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        expected_statuses: tuple[int, ...] = (200,),
        auth_mode: str = "installation",
    ) -> Any:
        url = path if path.startswith("http") else f"{self.api_url}{path}"
        data = None
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "slatelabs-github-project-automation-gateway",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if auth_mode == "app":
            headers["Authorization"] = f"Bearer {self._build_app_jwt()}"
        else:
            headers["Authorization"] = f"Bearer {self._get_installation_token()}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        req = request.Request(url, data=data, method=method, headers=headers)
        try:
            with request.urlopen(req) as response:
                status = response.getcode()
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise GitHubApiError(f"{method} {path} failed with {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise GitHubApiError(f"{method} {path} failed: {exc.reason}") from exc

        if status not in expected_statuses:
            raise GitHubApiError(f"{method} {path} returned {status}: {body}")

        if not body:
            return {}
        return json.loads(body)

    def _build_app_jwt(self) -> str:
        if self.app_credentials is None:
            raise ValueError("GitHub App JWT requested without app credentials")

        now = int(self.clock())
        return jwt.encode(
            {
                "iat": now - 60,
                "exp": now + (9 * 60),
                "iss": self.app_credentials.app_id,
            },
            self.app_credentials.private_key_pem,
            algorithm="RS256",
        )

    def _get_installation_token(self) -> str:
        if self.token:
            return self.token
        if self._installation_token and self.clock() < self._installation_token_expires_at - 60:
            return self._installation_token

        token, expires_at = self._mint_installation_token()
        self._installation_token = token
        self._installation_token_expires_at = expires_at
        return token

    def _mint_installation_token(self) -> tuple[str, float]:
        if self.app_credentials is None:
            raise ValueError("Installation token requested without app credentials")

        payload = self._request(
            "POST",
            f"/app/installations/{self.app_credentials.installation_id}/access_tokens",
            payload={},
            expected_statuses=(201,),
            auth_mode="app",
        )
        expires_at = payload.get("expires_at")
        if not payload.get("token") or not expires_at:
            raise GitHubApiError("GitHub App installation token response was missing token metadata")

        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
        return payload["token"], expiry

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        return self._request(
            "POST",
            "/graphql",
            payload={"query": query, "variables": variables},
            expected_statuses=(200,),
        )

    def get_project_item_context(self, item_node_id: str) -> ProjectItemContext:
        query = """
        query($itemId: ID!) {
          node(id: $itemId) {
            __typename
            ... on ProjectV2Item {
              id
              fieldValues(first: 20) {
                nodes {
                  __typename
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                  ... on ProjectV2ItemFieldRepositoryValue {
                    repository {
                      nameWithOwner
                      isArchived
                    }
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                }
              }
              content {
                __typename
                ... on Issue {
                  number
                  state
                  labels(first: 20) {
                    nodes {
                      name
                    }
                  }
                  repository {
                    nameWithOwner
                  }
                }
                ... on PullRequest {
                  number
                  repository {
                    nameWithOwner
                  }
                }
                ... on DraftIssue {
                  title
                }
              }
            }
          }
        }
        """
        payload = self.graphql(query, {"itemId": item_node_id})
        node = payload.get("data", {}).get("node")
        if not node or node.get("__typename") != "ProjectV2Item":
            raise GitHubApiError(f"Project item '{item_node_id}' was not found")

        content = node.get("content") or {}
        item_type = content.get("__typename") or "Unknown"
        issue_labels = tuple(label["name"] for label in content.get("labels", {}).get("nodes", []))

        repository_field_repo = None
        repository_field_archived = False
        workflow_status = None

        for field_value in node.get("fieldValues", {}).get("nodes", []):
            typename = field_value.get("__typename")
            field_name = field_value.get("field", {}).get("name")
            if typename == "ProjectV2ItemFieldRepositoryValue" and field_name == "Repository":
                repo = field_value.get("repository") or {}
                repository_field_repo = repo.get("nameWithOwner")
                repository_field_archived = bool(repo.get("isArchived"))
            elif typename == "ProjectV2ItemFieldSingleSelectValue" and field_name == "Workflow Status":
                workflow_status = field_value.get("name")

        return ProjectItemContext(
            project_item_id=node["id"],
            item_type=item_type,
            issue_number=content.get("number"),
            issue_repo=(content.get("repository") or {}).get("nameWithOwner"),
            issue_state=content.get("state"),
            issue_labels=issue_labels,
            repository_field_repo=repository_field_repo,
            repository_field_archived=repository_field_archived,
            workflow_status=workflow_status,
        )

    def get_actor_context(self, organization: str, repo_full_name: str, actor_login: str) -> ActorContext:
        org_role = None
        is_org_member = False
        try:
            membership = self._request(
                "GET",
                f"/orgs/{organization}/memberships/{actor_login}",
                expected_statuses=(200,),
            )
            org_role = membership.get("role")
            is_org_member = membership.get("state") == "active"
        except GitHubApiError as exc:
            if "404" not in str(exc):
                raise

        repo_permission = None
        repo_role_name = None
        try:
            permission = self._request(
                "GET",
                f"/repos/{repo_full_name}/collaborators/{actor_login}/permission",
                expected_statuses=(200,),
            )
            repo_permission = permission.get("permission")
            repo_role_name = permission.get("role_name")
        except GitHubApiError as exc:
            if "404" not in str(exc):
                raise

        return ActorContext(
            login=actor_login,
            org_role=org_role,
            repo_permission=repo_permission,
            repo_role_name=repo_role_name,
            is_org_member=is_org_member,
        )

    def ensure_issue_label(self, repo_full_name: str, issue_number: int, label: str) -> None:
        owner, repo = repo_full_name.split("/", 1)
        try:
            self._request(
                "POST",
                f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
                payload={"labels": [label]},
                expected_statuses=(200,),
            )
            return
        except GitHubApiError as exc:
            if "Validation Failed" not in str(exc):
                raise

        try:
            self._request(
                "POST",
                f"/repos/{owner}/{repo}/labels",
                payload={
                    "name": label,
                    "color": "fbca04",
                    "description": "Gateway marked this item as pending trusted review",
                },
                expected_statuses=(201, 422),
            )
        except GitHubApiError as exc:
            if "422" not in str(exc):
                raise

        self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            payload={"labels": [label]},
            expected_statuses=(200,),
        )

    def dispatch_repository_event(
        self,
        repo_full_name: str,
        event_type: str,
        client_payload: dict[str, Any],
    ) -> None:
        owner, repo = repo_full_name.split("/", 1)
        self._request(
            "POST",
            f"/repos/{owner}/{repo}/dispatches",
            payload={"event_type": event_type, "client_payload": client_payload},
            expected_statuses=(204,),
        )
