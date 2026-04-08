"""Subprocess-boundary tests for thin gh CLI wrapper scripts.

Each module under test forwards arguments to subprocess.run(["gh", ...]).
We mock subprocess.run to verify argument construction without calling gh.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_completed_process(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ===========================================================================
# scripts/github_mutations.py
# ===========================================================================


class TestGithubMutationsRun:
    """Tests for the low-level run() helper in github_mutations."""

    @patch("scripts.github_mutations.subprocess.run")
    def test_run_returns_stdout_on_success(self, mock_run):
        from scripts.github_mutations import run

        mock_run.return_value = make_completed_process(stdout="ok\n")
        assert run(["gh", "issue", "list"]) == "ok"

    @patch("scripts.github_mutations.subprocess.run")
    def test_run_raises_on_nonzero_exit(self, mock_run):
        from scripts.github_mutations import run

        mock_run.return_value = make_completed_process(stderr="not found", returncode=1)
        with pytest.raises(RuntimeError, match="not found"):
            run(["gh", "issue", "view", "999"])

    @patch("scripts.github_mutations.subprocess.run")
    def test_run_raises_with_stdout_when_stderr_empty(self, mock_run):
        from scripts.github_mutations import run

        mock_run.return_value = make_completed_process(stdout="bad request", stderr="", returncode=1)
        with pytest.raises(RuntimeError, match="bad request"):
            run(["gh", "api", "graphql"])

    @patch("scripts.github_mutations.subprocess.run")
    def test_run_raises_generic_message_when_no_output(self, mock_run):
        from scripts.github_mutations import run

        mock_run.return_value = make_completed_process(stdout="", stderr="", returncode=2)
        with pytest.raises(RuntimeError, match="exit code 2"):
            run(["gh", "version"])


class TestIssueComment:

    @patch("scripts.github_mutations.subprocess.run")
    def test_issue_comment_builds_correct_args(self, mock_run):
        from scripts.github_mutations import issue_comment

        mock_run.return_value = make_completed_process(stdout="https://github.com/org/repo/issues/42#comment")
        result = issue_comment("org/repo", "42", "hello")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["gh", "issue", "comment", "42", "--repo", "org/repo", "--body", "hello"]
        assert result == "https://github.com/org/repo/issues/42#comment"


class TestIssueCreate:

    @patch("scripts.github_mutations.subprocess.run")
    def test_issue_create_includes_label_flags(self, mock_run):
        from scripts.github_mutations import issue_create

        mock_run.return_value = make_completed_process(stdout="https://github.com/org/repo/issues/99")
        result = issue_create("org/repo", "title", "body", ["bug", "p1"])

        cmd = mock_run.call_args[0][0]
        assert cmd == [
            "gh", "issue", "create",
            "--repo", "org/repo",
            "--title", "title",
            "--body", "body",
            "--label", "bug",
            "--label", "p1",
        ]
        assert result == "https://github.com/org/repo/issues/99"

    @patch("scripts.github_mutations.subprocess.run")
    def test_issue_create_no_labels(self, mock_run):
        from scripts.github_mutations import issue_create

        mock_run.return_value = make_completed_process(stdout="url")
        issue_create("org/repo", "t", "b", [])

        cmd = mock_run.call_args[0][0]
        assert "--label" not in cmd


class TestPrMerge:

    @patch("scripts.github_mutations.subprocess.run")
    def test_pr_merge_uses_squash_and_delete_branch(self, mock_run):
        from scripts.github_mutations import pr_merge

        mock_run.return_value = make_completed_process()
        pr_merge("org/repo", "10")

        cmd = mock_run.call_args[0][0]
        assert cmd == ["gh", "pr", "merge", "10", "--repo", "org/repo", "--squash", "--delete-branch"]


class TestIssueCommentFile:

    @patch("scripts.github_mutations.subprocess.run")
    def test_issue_comment_file_passes_body_file(self, mock_run):
        from scripts.github_mutations import issue_comment_file

        mock_run.return_value = make_completed_process(stdout="url")
        issue_comment_file("org/repo", "5", "/tmp/body.md")

        cmd = mock_run.call_args[0][0]
        assert "--body-file" in cmd
        assert "/tmp/body.md" in cmd


class TestIssueEditBody:

    @patch("scripts.github_mutations.subprocess.run")
    def test_issue_edit_body_args(self, mock_run):
        from scripts.github_mutations import issue_edit_body

        mock_run.return_value = make_completed_process()
        issue_edit_body("org/repo", "7", "/tmp/body.md")

        cmd = mock_run.call_args[0][0]
        assert cmd[:4] == ["gh", "issue", "edit", "7"]
        assert "--body-file" in cmd


class TestIssueCommentEdit:

    @patch("scripts.github_mutations.subprocess.run")
    def test_issue_comment_edit_uses_api_patch(self, mock_run):
        from scripts.github_mutations import issue_comment_edit

        mock_run.return_value = make_completed_process(stdout="{}")
        issue_comment_edit("org/repo", "123456", "new body")

        cmd = mock_run.call_args[0][0]
        assert "repos/org/repo/issues/comments/123456" in cmd
        assert "--method" in cmd
        assert "PATCH" in cmd


class TestCreateDraftPr:

    @patch("scripts.github_mutations.subprocess.run")
    def test_create_draft_pr_passes_draft_flag(self, mock_run):
        from scripts.github_mutations import create_draft_pr

        mock_run.return_value = make_completed_process(stdout='{"number":1}')
        create_draft_pr("org/repo", "my pr", "feature", "main", "description")

        cmd = mock_run.call_args[0][0]
        assert "repos/org/repo/pulls" in cmd
        assert "draft=true" in cmd


class TestDiscussionCreate:

    @patch("scripts.github_mutations.subprocess.run")
    def test_discussion_create_sends_graphql_mutation(self, mock_run):
        from scripts.github_mutations import discussion_create

        mock_run.return_value = make_completed_process(stdout='{"data":{}}')
        discussion_create("R_123", "C_456", "Discussion Title", "body text")

        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["gh", "api", "graphql"]
        # Verify variable args are present
        assert "repoId=R_123" in " ".join(cmd)
        assert "categoryId=C_456" in " ".join(cmd)
        assert "title=Discussion Title" in " ".join(cmd)


# ===========================================================================
# scripts/github_discussion.py
# ===========================================================================


class TestGithubDiscussionRunGh:
    """Tests for run_gh in github_discussion."""

    @patch("scripts.github_discussion.subprocess.run")
    def test_run_gh_raises_on_nonzero_exit(self, mock_run):
        from scripts.github_discussion import run_gh

        mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="graphql error")
        with pytest.raises(subprocess.CalledProcessError):
            run_gh(["-f", "query={}"])

    @patch("scripts.github_discussion.subprocess.run")
    def test_run_gh_returns_parsed_json(self, mock_run):
        from scripts.github_discussion import run_gh

        mock_run.return_value = make_completed_process(stdout='{"data": {"ok": true}}')
        result = run_gh(["-f", "query={}"])
        assert result == {"data": {"ok": True}}


class TestGetDiscussion:

    @patch("scripts.github_discussion.subprocess.run")
    def test_get_discussion_builds_graphql_query(self, mock_run, capsys):
        from scripts.github_discussion import get_discussion

        mock_run.return_value = make_completed_process(
            stdout=json.dumps({
                "data": {
                    "repository": {
                        "discussion": {"id": "D_123", "body": "hello"}
                    }
                }
            })
        )
        get_discussion("org/repo", 5, with_comments=False)

        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["gh", "api", "graphql"]
        # Verify owner/name splitting
        joined = " ".join(cmd)
        assert "owner=org" in joined
        assert "name=repo" in joined

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["id"] == "D_123"

    @patch("scripts.github_discussion.subprocess.run")
    def test_get_discussion_with_comments_includes_fragment(self, mock_run, capsys):
        from scripts.github_discussion import get_discussion

        mock_run.return_value = make_completed_process(
            stdout=json.dumps({
                "data": {
                    "repository": {
                        "discussion": {
                            "id": "D_1",
                            "body": "b",
                            "comments": {"nodes": [{"body": "c1"}]},
                        }
                    }
                }
            })
        )
        get_discussion("org/repo", 1, with_comments=True)

        # The query arg should contain "comments"
        cmd = mock_run.call_args[0][0]
        query_arg = next(arg for i, arg in enumerate(cmd) if arg.startswith("query="))
        assert "comments" in query_arg


class TestUpdateBody:

    @patch("scripts.github_discussion.subprocess.run")
    def test_update_body_reads_file_and_sends_mutation(self, mock_run, tmp_path):
        from scripts.github_discussion import update_body

        body_file = tmp_path / "body.md"
        body_file.write_text("# Updated content")

        mock_run.return_value = make_completed_process(stdout='{"data":{}}')
        update_body("D_abc", str(body_file))

        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["gh", "api", "graphql"]
        joined = " ".join(cmd)
        assert "discussionId=D_abc" in joined
        assert "# Updated content" in joined


class TestAddComment:

    @patch("scripts.github_discussion.subprocess.run")
    def test_add_comment_reads_file(self, mock_run, tmp_path):
        from scripts.github_discussion import add_comment

        body_file = tmp_path / "comment.md"
        body_file.write_text("Nice work")

        mock_run.return_value = make_completed_process(stdout='{"data":{}}')
        add_comment("D_xyz", str(body_file))

        cmd = mock_run.call_args[0][0]
        joined = " ".join(cmd)
        assert "addDiscussionComment" in joined
        assert "Nice work" in joined


# ===========================================================================
# scripts/sync_project_status.py
# ===========================================================================


class TestSyncProjectStatus:
    """Tests for sync_project_status.main() via CLI args."""

    def _build_metadata_response(self, current_status, target_status):
        """Build a realistic gh_graphql metadata response."""
        return {
            "data": {
                "node": {
                    "id": "PVTI_item1",
                    "fieldValues": {
                        "nodes": [
                            {
                                "name": current_status,
                                "field": {"name": "Status"},
                            }
                        ]
                    },
                    "project": {
                        "id": "PVT_proj1",
                        "fields": {
                            "nodes": [
                                {
                                    "id": "PVTSSF_field1",
                                    "name": "Status",
                                    "options": [
                                        {"id": "opt_todo", "name": "Todo"},
                                        {"id": "opt_progress", "name": "In Progress"},
                                        {"id": "opt_done", "name": "Done"},
                                    ],
                                }
                            ]
                        },
                    },
                }
            }
        }

    @patch("scripts.sync_project_status.gh_graphql")
    def test_no_mutation_when_status_matches(self, mock_gh, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["sync_project_status", "--item-id", "PVTI_item1", "--target-status", "In Progress"])

        mock_gh.return_value = self._build_metadata_response("In Progress", "In Progress")

        from scripts.sync_project_status import main
        main()

        # Only the metadata query should be called, no mutation
        assert mock_gh.call_count == 1
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["updated"] is False
        assert result["current_status"] == "In Progress"
        assert result["target_status"] == "In Progress"

    @patch("scripts.sync_project_status.gh_graphql")
    def test_mutation_called_when_status_differs(self, mock_gh, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["sync_project_status", "--item-id", "PVTI_item1", "--target-status", "Done"])

        mock_gh.return_value = self._build_metadata_response("In Progress", "Done")

        from scripts.sync_project_status import main
        main()

        # metadata query + mutation = 2 calls
        assert mock_gh.call_count == 2

        # Verify the mutation call includes the expected args
        mutation_call = mock_gh.call_args_list[1]
        mutation_args = mutation_call[0]  # positional args
        joined = " ".join(mutation_args)
        assert "updateProjectV2ItemFieldValue" in joined
        assert "projectId=PVT_proj1" in joined
        assert "optionId=opt_done" in joined

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["updated"] is True
        assert result["target_status"] == "Done"


# ===========================================================================
# scripts/recover_project_item.py
# ===========================================================================


class TestRecoverProjectItem:

    def _build_project_items_response(self, nodes):
        return json.dumps({
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": nodes,
                        }
                    }
                }
            }
        })

    @patch("scripts.recover_project_item.subprocess.run")
    def test_preferred_project_selected(self, mock_run, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["recover_project_item", "--repo", "org/repo", "--issue-number", "42"])

        nodes = [
            {"id": "PVTI_other", "project": {"id": "P1", "title": "Some Other Board", "closed": False}},
            {"id": "PVTI_preferred", "project": {"id": "P2", "title": "Workflow Orchestration", "closed": False}},
        ]
        mock_run.return_value = make_completed_process(stdout=self._build_project_items_response(nodes))

        from scripts.recover_project_item import main
        main()

        captured = capsys.readouterr()
        assert captured.out.strip() == "PVTI_preferred"

    @patch("scripts.recover_project_item.subprocess.run")
    def test_falls_back_to_first_open_project(self, mock_run, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["recover_project_item", "--repo", "org/repo", "--issue-number", "42"])

        nodes = [
            {"id": "PVTI_first", "project": {"id": "P1", "title": "Other Board", "closed": False}},
        ]
        mock_run.return_value = make_completed_process(stdout=self._build_project_items_response(nodes))

        from scripts.recover_project_item import main
        main()

        captured = capsys.readouterr()
        assert captured.out.strip() == "PVTI_first"

    @patch("scripts.recover_project_item.subprocess.run")
    def test_no_items_prints_empty_string(self, mock_run, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["recover_project_item", "--repo", "org/repo", "--issue-number", "42"])

        mock_run.return_value = make_completed_process(stdout=self._build_project_items_response([]))

        from scripts.recover_project_item import main
        main()

        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    @patch("scripts.recover_project_item.subprocess.run")
    def test_closed_projects_excluded(self, mock_run, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["recover_project_item", "--repo", "org/repo", "--issue-number", "42"])

        nodes = [
            {"id": "PVTI_closed", "project": {"id": "P1", "title": "Workflow Orchestration", "closed": True}},
            {"id": "PVTI_open", "project": {"id": "P2", "title": "Other", "closed": False}},
        ]
        mock_run.return_value = make_completed_process(stdout=self._build_project_items_response(nodes))

        from scripts.recover_project_item import main
        main()

        captured = capsys.readouterr()
        assert captured.out.strip() == "PVTI_open"

    @patch("scripts.recover_project_item.subprocess.run")
    def test_graphql_args_include_owner_and_repo(self, mock_run, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["recover_project_item", "--repo", "myorg/myrepo", "--issue-number", "7"])

        mock_run.return_value = make_completed_process(stdout=self._build_project_items_response([]))

        from scripts.recover_project_item import main
        main()

        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["gh", "api", "graphql"]
        joined = " ".join(cmd)
        assert "owner=myorg" in joined
        assert "repo=myrepo" in joined
