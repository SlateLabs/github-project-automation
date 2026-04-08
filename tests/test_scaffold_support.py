"""Tests for scripts/scaffold_support.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaffold_support


REPO = "org/my-repo"


def _make_issue_payload(
    *,
    title: str = "Test Issue",
    body: str = "Issue body",
    state: str = "OPEN",
    labels: list[dict] | None = None,
    comments: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "body": body,
        "state": state,
        "labels": labels or [],
        "comments": comments or [],
    }


# ---------------------------------------------------------------------------
# issue_metadata
# ---------------------------------------------------------------------------


class TestIssueMetadata:
    def test_returns_parsed_json(self):
        payload = _make_issue_payload()
        with patch.object(scaffold_support, "gh_json", return_value=payload):
            result = scaffold_support.issue_metadata(REPO, 1)
        assert result["title"] == "Test Issue"
        assert result["state"] == "OPEN"


# ---------------------------------------------------------------------------
# ensure_open
# ---------------------------------------------------------------------------


class TestEnsureOpen:
    def test_open_issue_passes(self):
        payload = _make_issue_payload(state="OPEN")
        with patch.object(scaffold_support, "gh_json", return_value=payload):
            result = scaffold_support.ensure_open(REPO, 1)
        assert result["state"] == "OPEN"

    def test_closed_issue_raises(self):
        payload = _make_issue_payload(state="CLOSED")
        with patch.object(scaffold_support, "gh_json", return_value=payload):
            with pytest.raises(RuntimeError, match="not open"):
                scaffold_support.ensure_open(REPO, 1)

    def test_do_not_automate_label_raises(self):
        payload = _make_issue_payload(
            state="OPEN",
            labels=[{"name": "do-not-automate"}],
        )
        with patch.object(scaffold_support, "gh_json", return_value=payload):
            with pytest.raises(RuntimeError, match="do-not-automate"):
                scaffold_support.ensure_open(REPO, 1)


# ---------------------------------------------------------------------------
# discover_design
# ---------------------------------------------------------------------------


class TestDiscoverDesign:
    def test_finds_via_scaffold_marker(self):
        issue = _make_issue_payload(
            comments=[{
                "body": "<!-- gpa:design-discussion:#7 -->\nhttps://github.com/org/my-repo/discussions/99",
            }],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "graphql", return_value=None):
            result = scaffold_support.discover_design(REPO, 7)
        assert result["existing_url"] == "https://github.com/org/my-repo/discussions/99"
        assert result["discovery_method"] == "scaffold-marker"

    def test_finds_via_issue_body(self):
        issue = _make_issue_payload(
            body="See discussion: https://github.com/org/my-repo/discussions/55",
            comments=[],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "graphql", return_value=None):
            result = scaffold_support.discover_design(REPO, 7)
        assert result["existing_url"] == "https://github.com/org/my-repo/discussions/55"
        assert result["discovery_method"] == "issue-body"

    def test_returns_empty_when_no_discussion(self):
        issue = _make_issue_payload(body="No links here", comments=[])
        graphql_response = {"data": {"search": {"nodes": []}}}
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "graphql", return_value=graphql_response):
            result = scaffold_support.discover_design(REPO, 7)
        assert result["existing_url"] == ""
        assert result["discovery_method"] == ""

    def test_extracts_discussion_number(self):
        issue = _make_issue_payload(
            body="https://github.com/org/my-repo/discussions/123",
            comments=[],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "graphql", return_value=None):
            result = scaffold_support.discover_design(REPO, 7)
        assert result["existing_number"] == "123"


# ---------------------------------------------------------------------------
# discover_plan
# ---------------------------------------------------------------------------


class TestDiscoverPlan:
    def test_finds_via_owned_artifact_marker(self):
        marker = f"gpa:owned-artifact:impl-plan:{REPO}#5"
        issue = _make_issue_payload(
            comments=[{
                "body": f"<!-- {marker} -->\n## Implementation Plan\nSlice 1...",
                "url": "https://github.com/org/my-repo/issues/5#issuecomment-100",
                "id": "IC_100",
            }],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_plan(REPO, 5)
        assert result["discovery_method"] == "owned-artifact-marker"
        assert result["existing_id"] == "IC_100"

    def test_finds_via_heading_match(self):
        issue = _make_issue_payload(
            comments=[{
                "body": "## Implementation Plan\nSlice 1: do a thing",
                "url": "https://github.com/org/my-repo/issues/5#issuecomment-200",
                "id": "IC_200",
            }],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_plan(REPO, 5)
        assert result["discovery_method"] == "heading-match"
        assert result["existing_id"] == "IC_200"

    def test_returns_empty_when_no_plan(self):
        issue = _make_issue_payload(comments=[{"body": "Just a regular comment", "url": "", "id": ""}])
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_plan(REPO, 5)
        assert result["existing_url"] == ""
        assert result["discovery_method"] == ""

    def test_includes_status_marker(self):
        issue = _make_issue_payload(comments=[])
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_plan(REPO, 5)
        assert result["status_marker"] == "gpa:impl-plan-status:#5"


# ---------------------------------------------------------------------------
# discover_execution
# ---------------------------------------------------------------------------


class TestDiscoverExecution:
    def test_finds_open_pr_via_owned_artifact_marker(self):
        marker = f"gpa:owned-artifact:execution-bootstrap:{REPO}#10"
        issue = _make_issue_payload()
        open_prs = [{"number": 20, "body": f"<!-- {marker} -->", "headRefName": "10-feature"}]
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "pr_list", side_effect=[open_prs, [], []]):
            result = scaffold_support.discover_execution(REPO, 10)
        assert result["discovery_method"] == "owned-artifact-marker"
        assert result["existing_pr_number"] == "20"
        assert result["existing_branch"] == "10-feature"

    def test_finds_via_branch_pattern_match(self):
        issue = _make_issue_payload()
        open_prs = [{"number": 30, "body": "Some PR body", "headRefName": "10-my-feature"}]
        merged_prs = []
        closed_prs = []
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "pr_list", side_effect=[open_prs, merged_prs, closed_prs]):
            result = scaffold_support.discover_execution(REPO, 10)
        assert result["discovery_method"] == "branch-pattern-match"
        assert result["existing_pr_number"] == "30"

    def test_returns_empty_when_no_pr(self):
        issue = _make_issue_payload()
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "pr_list", return_value=[]):
            result = scaffold_support.discover_execution(REPO, 10)
        assert result["existing_pr_number"] == ""
        assert result["discovery_method"] == ""

    def test_includes_pr_url(self):
        marker = f"gpa:owned-artifact:execution-bootstrap:{REPO}#10"
        issue = _make_issue_payload()
        open_prs = [{"number": 20, "body": f"<!-- {marker} -->", "headRefName": "10-feature"}]
        with patch.object(scaffold_support, "issue_metadata", return_value=issue), \
             patch.object(scaffold_support, "pr_list", side_effect=[open_prs, [], []]):
            result = scaffold_support.discover_execution(REPO, 10)
        assert result["existing_pr_url"] == f"https://github.com/{REPO}/pull/20"


# ---------------------------------------------------------------------------
# discover_closeout
# ---------------------------------------------------------------------------


class TestDiscoverCloseout:
    def test_finds_closeout_comment(self):
        marker = f"gpa:owned-artifact:closeout:{REPO}#3"
        issue = _make_issue_payload(
            comments=[{
                "body": f"<!-- {marker} -->\n## Retrospective\nLessons learned...",
                "url": "https://github.com/org/my-repo/issues/3#issuecomment-500",
            }],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_closeout(REPO, 3)
        assert result["existing_comment_id"] == "500"
        assert "Retrospective" in result["existing_comment_body"]

    def test_returns_empty_when_no_closeout(self):
        issue = _make_issue_payload(
            comments=[{"body": "unrelated comment", "url": ""}],
        )
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_closeout(REPO, 3)
        assert result["existing_comment_id"] == ""
        assert result["existing_comment_body"] == ""

    def test_includes_status_marker(self):
        issue = _make_issue_payload(comments=[])
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_closeout(REPO, 3)
        assert result["status_marker"] == "gpa:closeout-status:#3"

    def test_includes_issue_title(self):
        issue = _make_issue_payload(title="My closeout issue", comments=[])
        with patch.object(scaffold_support, "issue_metadata", return_value=issue):
            result = scaffold_support.discover_closeout(REPO, 3)
        assert result["issue_title"] == "My closeout issue"


# ---------------------------------------------------------------------------
# gh_text / gh_json error handling
# ---------------------------------------------------------------------------


class TestGhHelpers:
    def test_gh_text_raises_on_failure(self):
        import subprocess
        mock_result = subprocess.CompletedProcess(
            args=["gh", "issue", "view"],
            returncode=1,
            stdout="",
            stderr="Not found",
        )
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Not found"):
                scaffold_support.gh_text(["issue", "view"])

    def test_gh_json_parses_output(self):
        import subprocess
        mock_result = subprocess.CompletedProcess(
            args=["gh", "issue", "view"],
            returncode=0,
            stdout='{"title": "test"}',
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            result = scaffold_support.gh_json(["issue", "view"])
        assert result == {"title": "test"}
