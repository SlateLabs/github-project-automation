"""Tests for gateway.dispatch — retry logic."""

from __future__ import annotations

from gateway.dispatch import dispatch_with_retry
from gateway.github_api_models import GitHubApiError


class TestDispatchWithRetry:

    def _make_client(self, *, fail_count=0):
        """Returns a mock client that fails the first `fail_count` calls."""
        calls = []
        failures = {"remaining": fail_count}

        class FakeClient:
            def dispatch_repository_event(self, repo, event_type, payload):
                calls.append((repo, event_type, payload))
                if failures["remaining"] > 0:
                    failures["remaining"] -= 1
                    raise GitHubApiError("transient")

        return FakeClient(), calls

    def _run(self, *, fail_count=0, backoffs=(1.0, 2.0, 4.0)):
        client, calls = self._make_client(fail_count=fail_count)
        logged = []
        slept = []
        error = dispatch_with_retry(
            github_client=client,
            repo_full_name="org/repo",
            event_type="test-event",
            client_payload={"key": "val"},
            delivery_id="d1",
            actor="alice",
            issue_number=1,
            run_key="rk",
            retry_backoffs=backoffs,
            logger=logged.append,
            sleep=slept.append,
        )
        return error, calls, logged, slept

    def test_success_on_first_attempt(self):
        error, calls, logged, slept = self._run(fail_count=0)
        assert error is None
        assert len(calls) == 1
        assert slept == []
        assert logged == []

    def test_retries_then_succeeds(self):
        error, calls, logged, slept = self._run(fail_count=2)
        assert error is None
        assert len(calls) == 3
        assert slept == [1.0, 2.0]
        assert len(logged) == 2

    def test_all_retries_exhausted(self):
        error, calls, logged, slept = self._run(fail_count=10, backoffs=(1.0, 2.0))
        assert error is not None
        assert isinstance(error, GitHubApiError)
        assert len(calls) == 2
        assert slept == [1.0, 2.0]

    def test_log_entries_contain_attempt_number(self):
        _, _, logged, _ = self._run(fail_count=2)
        assert logged[0]["attempt"] == 1
        assert logged[1]["attempt"] == 2

    def test_log_entries_contain_backoff(self):
        _, _, logged, _ = self._run(fail_count=1, backoffs=(3.5,))
        assert logged[0]["backoff_s"] == 3.5
