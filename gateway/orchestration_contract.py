"""Canonical orchestration contract primitives for operator/agent workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Iterable, Mapping
from urllib.parse import urlparse


class CoarseStatus(str, Enum):
    BACKLOG = "Backlog"
    READY = "Ready"
    IN_PROGRESS = "In Progress"
    IN_REVIEW = "In Review"
    APPROVED = "Approved"
    DONE = "Done"
    BLOCKED = "Blocked"


class OrchestrationStage(str, Enum):
    KICKOFF = "kickoff"
    CLARIFICATION = "clarification"
    DESIGN = "design"
    PLAN = "plan"
    EXECUTION = "execution"
    DEPLOY_REVIEW = "deploy-review"
    REVIEW_INTAKE = "review-intake"
    FEEDBACK_IMPLEMENTATION = "feedback-implementation"
    REDEPLOY_REVIEW = "redeploy-review"
    MERGE = "merge"
    POST_MERGE_VERIFY = "post-merge-verify"
    FOLLOW_UP_CAPTURE = "follow-up-capture"
    CLOSEOUT = "closeout"


class StageOutcome(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    RETRYING = "retrying"
    NOOP = "noop"


class OperatorCommandType(str, Enum):
    FEEDBACK = "feedback"
    APPROVE = "approve"


REVIEW_READY_MARKER = "gpa:review-ready"
_REVIEW_READY_PR_LINE = re.compile(r"(?im)^\s*pr\s*:\s*(?P<value>.+?)\s*$")
_REVIEW_READY_PR_URL = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(?P<number>\d+)")
_REVIEW_READY_PR_NUMBER = re.compile(r"#(?P<number>\d+)\b|^(?P<bare>\d+)\b")
_REVIEW_READY_DEPLOYMENT_URL_LINE = re.compile(r"(?im)^\s*deployment\s+url\s*:\s*(?P<value>\S+)\s*$")
_REVIEW_READY_DEPLOYMENT_SOURCE_LINE = re.compile(r"(?im)^\s*deployment\s+source\s*:\s*(?P<value>.+?)\s*$")
_REVIEW_READY_DEPLOYMENT_STATUS_LINE = re.compile(r"(?im)^\s*deployment\s+status\s*:\s*(?P<value>.+?)\s*$")
_INVALID_DEPLOYMENT_STATUS_VALUES = {"pending", "unknown", "n/a", "na", "tbd", "todo", "unset"}
_ALLOWED_DEPLOYMENT_SOURCES = {
    "cloud-run",
    "vercel",
    "netlify",
    "render",
    "railway",
    "fly-io",
    "aws-amplify",
    "azure-static-web-apps",
    "github-pages",
    "kubernetes",
}


STAGE_TRANSITIONS: dict[OrchestrationStage, tuple[OrchestrationStage, ...]] = {
    OrchestrationStage.KICKOFF: (OrchestrationStage.CLARIFICATION,),
    OrchestrationStage.CLARIFICATION: (OrchestrationStage.DESIGN,),
    OrchestrationStage.DESIGN: (OrchestrationStage.PLAN,),
    OrchestrationStage.PLAN: (OrchestrationStage.EXECUTION,),
    OrchestrationStage.EXECUTION: (OrchestrationStage.DEPLOY_REVIEW,),
    OrchestrationStage.DEPLOY_REVIEW: (OrchestrationStage.REVIEW_INTAKE,),
    OrchestrationStage.REVIEW_INTAKE: (
        OrchestrationStage.FEEDBACK_IMPLEMENTATION,
        OrchestrationStage.MERGE,
    ),
    OrchestrationStage.FEEDBACK_IMPLEMENTATION: (OrchestrationStage.REDEPLOY_REVIEW,),
    OrchestrationStage.REDEPLOY_REVIEW: (OrchestrationStage.REVIEW_INTAKE,),
    OrchestrationStage.MERGE: (OrchestrationStage.POST_MERGE_VERIFY,),
    OrchestrationStage.POST_MERGE_VERIFY: (
        OrchestrationStage.FOLLOW_UP_CAPTURE,
        OrchestrationStage.POST_MERGE_VERIFY,
    ),
    OrchestrationStage.FOLLOW_UP_CAPTURE: (OrchestrationStage.CLOSEOUT,),
    OrchestrationStage.CLOSEOUT: (),
}


@dataclass(frozen=True)
class RetryMetadata:
    attempt: int = 1
    max_attempts: int = 1
    retriable: bool = False
    backoff_seconds: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        if any(seconds < 0 for seconds in self.backoff_seconds):
            raise ValueError("backoff_seconds values must be >= 0")


@dataclass(frozen=True)
class StageEvent:
    run_key: str
    issue_number: int
    stage: OrchestrationStage
    outcome: StageOutcome
    status: CoarseStatus
    idempotency_key: str
    actor: str
    timestamp_ms: int
    previous_stage: OrchestrationStage | None = None
    next_stage: OrchestrationStage | None = None
    retry: RetryMetadata = field(default_factory=RetryMetadata)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.run_key:
            raise ValueError("run_key must be non-empty")
        if self.issue_number <= 0:
            raise ValueError("issue_number must be > 0")
        if not self.idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        if not self.actor:
            raise ValueError("actor must be non-empty")
        if self.timestamp_ms <= 0:
            raise ValueError("timestamp_ms must be > 0")
        if self.next_stage and not is_transition_allowed(self.stage, self.next_stage):
            raise ValueError(f"invalid stage transition: {self.stage.value} -> {self.next_stage.value}")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "run_key": self.run_key,
            "issue_number": self.issue_number,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "actor": self.actor,
            "timestamp_ms": self.timestamp_ms,
            "retry": {
                "attempt": self.retry.attempt,
                "max_attempts": self.retry.max_attempts,
                "retriable": self.retry.retriable,
                "backoff_seconds": list(self.retry.backoff_seconds),
            },
        }
        if self.previous_stage is not None:
            payload["previous_stage"] = self.previous_stage.value
        if self.next_stage is not None:
            payload["next_stage"] = self.next_stage.value
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class ParsedOperatorCommand:
    comment_id: int
    created_at_ms: int
    author: str
    command_type: OperatorCommandType
    body: str
    instructions: str | None = None


@dataclass(frozen=True)
class ReviewReadyArtifact:
    comment_id: int
    created_at_ms: int
    pr_number: int
    deployment_url: str
    deployment_source: str
    deployment_status: str
    body: str


def is_transition_allowed(current: OrchestrationStage, candidate_next: OrchestrationStage) -> bool:
    return candidate_next in STAGE_TRANSITIONS.get(current, ())


def parse_operator_command(text: str) -> tuple[OperatorCommandType, str | None] | None:
    lines = [line.strip() for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    if not non_empty:
        return None

    first_line = non_empty[0]
    if first_line == "gpa:approve":
        return (OperatorCommandType.APPROVE, None)

    if first_line.startswith("gpa:feedback"):
        trailing = first_line[len("gpa:feedback") :].strip()
        if trailing:
            instructions = trailing
        else:
            remaining = "\n".join(non_empty[1:]).strip()
            instructions = remaining
        if instructions:
            return (OperatorCommandType.FEEDBACK, instructions)
    return None


def select_latest_operator_command(
    *,
    comments: Iterable[Mapping[str, object]],
    trusted_users: set[str],
    review_ready_after_ms: int,
    consumed_comment_ids: set[int] | None = None,
) -> ParsedOperatorCommand | None:
    consumed = consumed_comment_ids or set()
    candidates: list[ParsedOperatorCommand] = []

    for comment in comments:
        comment_id = int(comment.get("id") or 0)
        created_at_ms = int(comment.get("created_at_ms") or 0)
        author = str(comment.get("author") or "")
        body = str(comment.get("body") or "")

        if comment_id <= 0 or created_at_ms <= review_ready_after_ms:
            continue
        if comment_id in consumed or author not in trusted_users:
            continue

        parsed = parse_operator_command(body)
        if parsed is None:
            continue

        command_type, instructions = parsed
        candidates.append(
            ParsedOperatorCommand(
                comment_id=comment_id,
                created_at_ms=created_at_ms,
                author=author,
                command_type=command_type,
                body=body,
                instructions=instructions,
            )
        )

    if not candidates:
        return None

    # Latest valid command wins by created timestamp, then comment id.
    candidates.sort(key=lambda c: (c.created_at_ms, c.comment_id))
    return candidates[-1]


def find_latest_review_ready_marker_ms(comments: Iterable[Mapping[str, object]]) -> int | None:
    latest: int | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        if REVIEW_READY_MARKER not in body:
            continue
        created_at_ms = int(comment.get("created_at_ms") or 0)
        if created_at_ms <= 0:
            continue
        if latest is None or created_at_ms > latest:
            latest = created_at_ms
    return latest


def find_latest_review_ready_artifact(comments: Iterable[Mapping[str, object]]) -> ReviewReadyArtifact | None:
    latest: ReviewReadyArtifact | None = None
    for comment in comments:
        artifact = parse_review_ready_artifact(comment)
        if artifact is None:
            continue
        if latest is None or (artifact.created_at_ms, artifact.comment_id) > (latest.created_at_ms, latest.comment_id):
            latest = artifact
    return latest


def parse_review_ready_artifact(comment: Mapping[str, object]) -> ReviewReadyArtifact | None:
    comment_id = int(comment.get("id") or 0)
    created_at_ms = int(comment.get("created_at_ms") or 0)
    body = str(comment.get("body") or "")

    if comment_id <= 0 or created_at_ms <= 0 or REVIEW_READY_MARKER not in body:
        return None

    pr_number = _extract_pr_number(body)
    deployment_url = _extract_deployment_url(body)
    deployment_source = _extract_deployment_source(body)
    deployment_status = _extract_deployment_status(body)
    if pr_number is None or deployment_url is None or deployment_source is None or deployment_status is None:
        return None

    return ReviewReadyArtifact(
        comment_id=comment_id,
        created_at_ms=created_at_ms,
        pr_number=pr_number,
        deployment_url=deployment_url,
        deployment_source=deployment_source,
        deployment_status=deployment_status,
        body=body,
    )


def _extract_pr_number(body: str) -> int | None:
    line = _REVIEW_READY_PR_LINE.search(body)
    if line is None:
        return None

    value = line.group("value").strip()
    if not value:
        return None

    pr_url_match = _REVIEW_READY_PR_URL.search(value)
    if pr_url_match is not None:
        return int(pr_url_match.group("number"))

    pr_number_match = _REVIEW_READY_PR_NUMBER.search(value)
    if pr_number_match is None:
        return None

    number = pr_number_match.group("number") or pr_number_match.group("bare")
    return int(number) if number else None


def _extract_deployment_url(body: str) -> str | None:
    line = _REVIEW_READY_DEPLOYMENT_URL_LINE.search(body)
    if line is None:
        return None

    url = line.group("value").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1"}:
        return None
    return url


def _extract_deployment_status(body: str) -> str | None:
    line = _REVIEW_READY_DEPLOYMENT_STATUS_LINE.search(body)
    if line is None:
        return None

    value = line.group("value").strip()
    if not value:
        return None
    if value.lower() in _INVALID_DEPLOYMENT_STATUS_VALUES:
        return None
    return value


def _extract_deployment_source(body: str) -> str | None:
    line = _REVIEW_READY_DEPLOYMENT_SOURCE_LINE.search(body)
    if line is None:
        return None

    value = line.group("value").strip()
    normalized = value.lower().replace("_", "-")
    if not normalized:
        return None
    if normalized in {"unknown", "n/a", "na", "tbd", "todo", "unset"}:
        return None
    if normalized not in _ALLOWED_DEPLOYMENT_SOURCES:
        return None
    return normalized
