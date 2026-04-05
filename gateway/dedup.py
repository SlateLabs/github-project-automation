"""In-memory deduplication helpers for the webhook gateway."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class ActiveRun:
    run_key: str
    started_at_ms: int


@dataclass
class CompletedRun:
    run_key: str
    completed_at_ms: int


class InMemoryDedupStore:
    """Process-local dedup store with TTL-style pruning."""

    def __init__(self, dedup_window_ms: int = 60_000) -> None:
        self.dedup_window_ms = dedup_window_ms
        self._delivery_ids: dict[str, int] = {}
        self._active_runs: dict[str, ActiveRun] = {}
        self._completed_runs: dict[str, CompletedRun] = {}
        self._operator_comment_ids: dict[str, int] = {}
        self._lock = Lock()

    def _prune(self, now_ms: int) -> None:
        cutoff = now_ms - self.dedup_window_ms
        self._delivery_ids = {
            delivery_id: seen_at
            for delivery_id, seen_at in self._delivery_ids.items()
            if seen_at >= cutoff
        }
        self._completed_runs = {
            prefix: run
            for prefix, run in self._completed_runs.items()
            if run.completed_at_ms >= cutoff
        }
        self._operator_comment_ids = {
            comment_key: seen_at
            for comment_key, seen_at in self._operator_comment_ids.items()
            if seen_at >= cutoff
        }

    def seen_delivery(self, delivery_id: str, now_ms: int) -> bool:
        with self._lock:
            self._prune(now_ms)
            seen = delivery_id in self._delivery_ids
            if not seen:
                self._delivery_ids[delivery_id] = now_ms
            return seen

    def has_active_run(self, prefix: str, now_ms: int) -> bool:
        with self._lock:
            self._prune(now_ms)
            return prefix in self._active_runs

    def has_recent_completion(self, prefix: str, now_ms: int) -> bool:
        with self._lock:
            self._prune(now_ms)
            completed = self._completed_runs.get(prefix)
            return completed is not None

    def mark_active(self, prefix: str, run_key: str, now_ms: int) -> None:
        with self._lock:
            self._prune(now_ms)
            self._active_runs[prefix] = ActiveRun(run_key=run_key, started_at_ms=now_ms)

    def mark_completed(self, prefix: str, run_key: str, now_ms: int) -> None:
        with self._lock:
            self._prune(now_ms)
            self._active_runs.pop(prefix, None)
            self._completed_runs[prefix] = CompletedRun(
                run_key=run_key,
                completed_at_ms=now_ms,
            )

    def clear_active(self, prefix: str) -> None:
        with self._lock:
            self._active_runs.pop(prefix, None)

    def seen_operator_comment(self, comment_key: str, now_ms: int) -> bool:
        with self._lock:
            self._prune(now_ms)
            seen = comment_key in self._operator_comment_ids
            if not seen:
                self._operator_comment_ids[comment_key] = now_ms
            return seen
