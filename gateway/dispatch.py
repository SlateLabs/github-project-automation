from __future__ import annotations

from typing import Any, Callable

from gateway.github_api import GitHubApiError


def dispatch_with_retry(
    *,
    github_client: Any,
    repo_full_name: str,
    event_type: str,
    client_payload: dict[str, Any],
    delivery_id: str,
    actor: str,
    issue_number: int,
    run_key: str,
    retry_backoffs: tuple[float, ...],
    logger: Callable[[dict[str, Any]], None],
    sleep: Callable[[float], None],
) -> GitHubApiError | None:
    last_error: GitHubApiError | None = None
    for attempt, backoff in enumerate(retry_backoffs):
        try:
            github_client.dispatch_repository_event(repo_full_name, event_type, client_payload)
            return None
        except GitHubApiError as exc:
            last_error = exc
            logger(
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
            sleep(backoff)
    return last_error
