"""Tests for gateway.dedup — in-memory deduplication store."""

from __future__ import annotations

from gateway.dedup import InMemoryDedupStore


class TestInMemoryDedupStore:

    def test_first_delivery_is_not_seen(self):
        store = InMemoryDedupStore()
        assert store.seen_delivery("d1", now_ms=1000) is False

    def test_repeated_delivery_is_seen(self):
        store = InMemoryDedupStore()
        store.seen_delivery("d1", now_ms=1000)
        assert store.seen_delivery("d1", now_ms=1001) is True

    def test_delivery_pruned_after_window(self):
        store = InMemoryDedupStore(dedup_window_ms=100)
        store.seen_delivery("d1", now_ms=1000)
        assert store.seen_delivery("d1", now_ms=1200) is False

    def test_active_run_lifecycle(self):
        store = InMemoryDedupStore()
        prefix = "repo/42/kickoff"
        assert store.has_active_run(prefix, now_ms=1000) is False
        store.mark_active(prefix, "rk1", now_ms=1000)
        assert store.has_active_run(prefix, now_ms=1001) is True

    def test_clear_active_removes_run(self):
        store = InMemoryDedupStore()
        prefix = "repo/42/kickoff"
        store.mark_active(prefix, "rk1", now_ms=1000)
        store.clear_active(prefix)
        assert store.has_active_run(prefix, now_ms=1001) is False

    def test_completed_run_lifecycle(self):
        store = InMemoryDedupStore()
        prefix = "repo/42/kickoff"
        assert store.has_recent_completion(prefix, now_ms=1000) is False
        store.mark_completed(prefix, "rk1", now_ms=1000)
        assert store.has_recent_completion(prefix, now_ms=1001) is True

    def test_mark_completed_clears_active(self):
        store = InMemoryDedupStore()
        prefix = "repo/42/kickoff"
        store.mark_active(prefix, "rk1", now_ms=1000)
        store.mark_completed(prefix, "rk1", now_ms=1001)
        assert store.has_active_run(prefix, now_ms=1002) is False

    def test_completed_run_pruned_after_window(self):
        store = InMemoryDedupStore(dedup_window_ms=100)
        prefix = "repo/42/kickoff"
        store.mark_completed(prefix, "rk1", now_ms=1000)
        assert store.has_recent_completion(prefix, now_ms=1200) is False

    def test_clear_active_is_idempotent(self):
        store = InMemoryDedupStore()
        store.clear_active("nonexistent")  # should not raise
