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
    issue_title: str | None
    issue_number: int | None
    issue_repo: str | None
    issue_state: str | None
    issue_labels: tuple[str, ...]
    repository_field_repo: str | None
    repository_field_archived: bool
    status: str | None


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

    def _project_item_context_from_node(self, node: dict[str, Any], content: dict[str, Any]) -> ProjectItemContext:
        item_type = content.get("__typename") or "Unknown"
        issue_labels = tuple(label["name"] for label in content.get("labels", {}).get("nodes", []))

        repository_field_repo = None
        repository_field_archived = False
        status = None

        for field_value in node.get("fieldValues", {}).get("nodes", []):
            typename = field_value.get("__typename")
            field_name = field_value.get("field", {}).get("name")
            if typename == "ProjectV2ItemFieldRepositoryValue" and field_name == "Repository":
                repo = field_value.get("repository") or {}
                repository_field_repo = repo.get("nameWithOwner")
                repository_field_archived = bool(repo.get("isArchived"))
            elif typename == "ProjectV2ItemFieldSingleSelectValue" and field_name == "Status":
                status = field_value.get("name")

        return ProjectItemContext(
            project_item_id=node["id"],
            item_type=item_type,
            issue_title=content.get("title"),
            issue_number=content.get("number"),
            issue_repo=(content.get("repository") or {}).get("nameWithOwner"),
            issue_state=content.get("state"),
            issue_labels=issue_labels,
            repository_field_repo=repository_field_repo,
            repository_field_archived=repository_field_archived,
            status=status,
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
        return self._project_item_context_from_node(node, content)

    def get_issue_project_item_context(self, repo_full_name: str, issue_number: int) -> ProjectItemContext:
        owner, repo = repo_full_name.split("/", 1)
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            issue(number: $number) {
              __typename
              title
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
              projectItems(first: 20) {
                nodes {
                  id
                  project {
                    ... on ProjectV2 {
                      title
                      closed
                    }
                  }
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
                }
              }
            }
          }
        }
        """
        payload = self.graphql(query, {"owner": owner, "repo": repo, "number": issue_number})
        issue = payload.get("data", {}).get("repository", {}).get("issue")
        if not issue:
            raise GitHubApiError(f"Issue '{repo_full_name}#{issue_number}' was not found")

        item_nodes = issue.get("projectItems", {}).get("nodes", [])
        open_items = [item for item in item_nodes if not (item.get("project") or {}).get("closed", False)]
        if not open_items:
            raise GitHubApiError(f"Issue '{repo_full_name}#{issue_number}' is not attached to an open project item")

        preferred = next(
            (item for item in open_items if (item.get("project") or {}).get("title") == "Workflow Orchestration"),
            open_items[0],
        )
        return self._project_item_context_from_node(preferred, issue)

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

    def update_project_item_status(self, project_item_id: str, status_name: str) -> None:
        metadata_query = """
        query($itemId: ID!) {
          node(id: $itemId) {
            ... on ProjectV2Item {
              id
              project {
                ... on ProjectV2 {
                  id
                  fields(first: 20) {
                    nodes {
                      ... on ProjectV2SingleSelectField {
                        id
                        name
                        options {
                          id
                          name
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        metadata = self.graphql(metadata_query, {"itemId": project_item_id})
        item = metadata.get("data", {}).get("node")
        if not item:
            raise GitHubApiError(f"Project item '{project_item_id}' was not found for status update")

        project = item.get("project") or {}
        project_id = project.get("id")
        status_field = next((field for field in project.get("fields", {}).get("nodes", []) if field.get("name") == "Status"), None)
        if not project_id or not status_field:
            raise GitHubApiError(f"Project item '{project_item_id}' is missing a Status field")

        option_id = next((option.get("id") for option in status_field.get("options", []) if option.get("name") == status_name), None)
        if not option_id:
            raise GitHubApiError(f"Project Status option '{status_name}' was not found")

        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
          updateProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
              value: { singleSelectOptionId: $optionId }
            }
          ) {
            projectV2Item {
              id
            }
          }
        }
        """
        self.graphql(
            mutation,
            {
                "projectId": project_id,
                "itemId": project_item_id,
                "fieldId": status_field["id"],
                "optionId": option_id,
            },
        )
