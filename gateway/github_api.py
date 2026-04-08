"""Compatibility exports for the gateway GitHub API surface."""

from gateway.github_api_client import GitHubApiClient
from gateway.github_api_config import load_repo_config, load_trust_policy
from gateway.github_api_models import (
    ActorContext,
    ConfiguredRepo,
    GitHubApiError,
    GitHubAppCredentials,
    ProjectItemContext,
    TrustPolicy,
)

__all__ = [
    "ActorContext",
    "ConfiguredRepo",
    "GitHubApiClient",
    "GitHubApiError",
    "GitHubAppCredentials",
    "ProjectItemContext",
    "TrustPolicy",
    "load_repo_config",
    "load_trust_policy",
]
