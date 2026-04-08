"""Tests for scripts/check_gate/ bash gate fragments.

Each gate script is sourced inside a bash harness that sets up the
environment (env vars, mock commands, unmet/waived arrays, check_waiver).
We run the harness via subprocess and parse stdout lines as the unmet array.
"""

import json
import os
import subprocess
import tempfile
import textwrap

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_DIR = os.path.join(REPO_ROOT, "scripts", "check_gate")


def _run_gate(
    gate_script: str,
    issue_body: str = "",
    *,
    gh_mock: str = 'gh() { echo "{}"; }',
    python3_mock: str = 'python3() { echo "{}"; }',
    extra_env: dict | None = None,
    extra_setup: str = "",
    check_mode: str = "full",
) -> list[str]:
    """Run a gate script in a bash harness and return the list of unmet conditions."""
    gate_path = os.path.join(GATE_DIR, gate_script)

    # Write issue body to a temp file so heredoc indentation cannot corrupt it
    body_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".body", delete=False
    )
    body_file.write(issue_body)
    body_file.flush()
    body_file.close()

    harness = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        # Initialize arrays
        unmet=()
        waived=()

        # Mock check_waiver — always return false (no waivers)
        check_waiver() {{ return 1; }}

        # Mock external commands
        {gh_mock}
        {python3_mock}
        export -f gh python3

        # Env vars
        export ISSUE_NUMBER="42"
        export GITHUB_REPOSITORY="SlateLabs/test-repo"
        export GITHUB_REPOSITORY_OWNER="SlateLabs"
        export CHECK_MODE="{check_mode}"
        export trusted_users_list=""

        {extra_setup}

        # Issue body from file (avoids heredoc indentation issues)
        ISSUE_BODY=$(cat "{body_file.name}")
        export ISSUE_BODY

        # Source the gate script
        source "{gate_path}"

        # Output unmet conditions, one per line
        if [ ${{#unmet[@]}} -gt 0 ]; then
            printf '%s\\n' "${{unmet[@]}}"
        fi
    """)

    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    if extra_env:
        env.update(extra_env)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False
    ) as f:
        f.write(harness)
        f.flush()
        harness_path = f.name

    try:
        result = subprocess.run(
            ["bash", harness_path],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Gate harness failed (rc={result.returncode}):\n"
                f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
        lines = [
            l for l in result.stdout.strip().splitlines()
            if l and not l.startswith("::notice::")
        ]
        return lines
    finally:
        os.unlink(harness_path)
        os.unlink(body_file.name)


# ---------------------------------------------------------------------------
# kickoff.sh
# ---------------------------------------------------------------------------

class TestKickoff:
    @pytest.mark.parametrize(
        "body,expect_pass",
        [
            ("## Summary\nSome content here", True),
            ("# Summary\nSome content here", True),
            ("No summary heading at all", False),
            ("### Summary\nThree hashes", False),
        ],
        ids=["h2-summary", "h1-summary", "no-summary", "h3-not-matched"],
    )
    def test_summary_heading(self, body, expect_pass):
        unmet = _run_gate("kickoff.sh", body)
        if expect_pass:
            assert unmet == []
        else:
            assert any("Summary" in u for u in unmet)


# ---------------------------------------------------------------------------
# clarification.sh
# ---------------------------------------------------------------------------

class TestClarification:
    def test_pass_with_summary_and_scope(self):
        body = "## Summary\nFoo\n## Scope\nBar"
        # gh issue view is called for labels; mock returns no labels
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        assert unmet == []

    def test_fail_missing_summary(self):
        body = "## Scope\nBar"
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        assert any("Summary" in u for u in unmet)

    def test_fail_missing_scope(self):
        body = "## Summary\nFoo"
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        assert any("Scope" in u for u in unmet)

    def test_pass_with_open_questions_heading(self):
        body = "## Summary\nFoo\n## Open Questions\nBar"
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        # Open Questions satisfies the Scope/Open Questions check
        assert not any("Scope" in u for u in unmet)

    def test_open_questions_all_resolved(self):
        body = (
            "## Summary\nFoo\n"
            "## Open Questions\n"
            "- ~~resolved question~~\n"
            "- DEFERRED-TO-DESIGN: another\n"
        )
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        assert not any("open question" in u for u in unmet)

    def test_open_questions_unresolved(self):
        body = (
            "## Summary\nFoo\n"
            "## Open Questions\n"
            "- This is unresolved\n"
            "- ~~This is resolved~~\n"
        )
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        assert any("open question" in u for u in unmet)

    def test_blocked_label(self):
        body = "## Summary\nFoo\n## Scope\nBar"
        gh = textwrap.dedent("""\
            gh() {
                if [[ "$1" == "issue" && "$2" == "view" ]]; then
                    echo "blocked"
                else
                    echo ""
                fi
            }""")
        unmet = _run_gate("clarification.sh", body, gh_mock=gh)
        assert any("blocked" in u for u in unmet)


# ---------------------------------------------------------------------------
# execution.sh
# ---------------------------------------------------------------------------

class TestExecution:
    def test_fail_no_branch(self):
        gh = 'gh() { echo ""; }'
        py = 'python3() { echo "{}"; }'
        unmet = _run_gate("execution.sh", "", gh_mock=gh, python3_mock=py)
        assert any("branch" in u.lower() for u in unmet)

    def test_fail_no_pr(self):
        # Branch exists but no PR
        gh = textwrap.dedent("""\
            gh() {
                if [[ "$1" == "api" && "$2" == *"branches"* ]]; then
                    echo "42-feature"
                else
                    echo ""
                fi
            }""")
        py = 'python3() { echo "{}"; }'
        unmet = _run_gate("execution.sh", "", gh_mock=gh, python3_mock=py)
        assert any("pull request" in u.lower() for u in unmet)

    def test_pass_branch_and_pr(self):
        gh = textwrap.dedent("""\
            gh() {
                echo "42-feature"
            }""")
        pr_body = "## Summary\\nFoo\\n## Test plan\\nBar"
        pr_json = f'{{"number": 99, "isDraft": false, "body": "{pr_body}"}}'
        py = f'python3() {{ echo \'{pr_json}\'; }}'
        unmet = _run_gate("execution.sh", "", gh_mock=gh, python3_mock=py)
        assert unmet == []

    def test_fail_draft_pr(self):
        gh = 'gh() { echo "42-feature"; }'
        pr_body = "## Summary\\nFoo\\n## Test plan\\nBar"
        pr_json = f'{{"number": 99, "isDraft": true, "body": "{pr_body}"}}'
        py = f'python3() {{ echo \'{pr_json}\'; }}'
        unmet = _run_gate("execution.sh", "", gh_mock=gh, python3_mock=py)
        assert any("draft" in u.lower() for u in unmet)

    def test_fail_pr_missing_summary(self):
        gh = 'gh() { echo "42-feature"; }'
        pr_body = "## Test plan\\nBar"
        pr_json = f'{{"number": 99, "isDraft": false, "body": "{pr_body}"}}'
        py = f'python3() {{ echo \'{pr_json}\'; }}'
        unmet = _run_gate("execution.sh", "", gh_mock=gh, python3_mock=py)
        assert any("Summary" in u for u in unmet)

    def test_fail_pr_missing_test_plan(self):
        gh = 'gh() { echo "42-feature"; }'
        pr_body = "## Summary\\nFoo"
        pr_json = f'{{"number": 99, "isDraft": false, "body": "{pr_body}"}}'
        py = f'python3() {{ echo \'{pr_json}\'; }}'
        unmet = _run_gate("execution.sh", "", gh_mock=gh, python3_mock=py)
        assert any("Test plan" in u or "Test Plan" in u for u in unmet)


# ---------------------------------------------------------------------------
# plan.sh
# ---------------------------------------------------------------------------

class TestPlan:
    @staticmethod
    def _comments_json(comments: list[str]) -> str:
        """Build JSON matching github_orchestration_context issue-comments output."""
        obj = {"comments": [{"body": c} for c in comments]}
        return json.dumps(obj)

    def test_pass_full_plan(self):
        plan = textwrap.dedent("""\
            ## Implementation Plan
            Content here.
            ## Acceptance Criteria
            - [ ] First criterion
            ## Verification Plan
            - [ ] Verify something
            ## Review Expectations
            - accessibility: **required**
            - usability / content: **waived**
            - documentation: **N/A**
            - hygiene: **deferred**
            ## Slices
            1. First slice
            """)
        comments_json = self._comments_json([plan])
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("plan.sh", "", python3_mock=py)
        assert unmet == []

    def test_fail_no_plan_comment(self):
        comments_json = self._comments_json(["Just a random comment"])
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("plan.sh", "", python3_mock=py)
        assert any("Implementation Plan" in u for u in unmet)

    def test_fail_missing_acceptance_criteria(self):
        plan = textwrap.dedent("""\
            ## Implementation Plan
            Content here.
            ## Verification Plan
            - [ ] Verify something
            ## Review Expectations
            - accessibility: **required**
            - usability / content: **waived**
            - documentation: **N/A**
            - hygiene: **deferred**
            ## Slices
            1. First slice
            """)
        comments_json = self._comments_json([plan])
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("plan.sh", "", python3_mock=py)
        assert any("Acceptance Criteria" in u for u in unmet)

    def test_fail_missing_slices(self):
        plan = textwrap.dedent("""\
            ## Implementation Plan
            Content here.
            ## Acceptance Criteria
            - [ ] First criterion
            ## Verification Plan
            - [ ] Verify something
            ## Review Expectations
            - accessibility: **required**
            - usability / content: **waived**
            - documentation: **N/A**
            - hygiene: **deferred**
            """)
        comments_json = self._comments_json([plan])
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("plan.sh", "", python3_mock=py)
        assert any("Slices" in u for u in unmet)

    def test_fail_acceptance_criteria_no_checklist(self):
        plan = textwrap.dedent("""\
            ## Implementation Plan
            Content here.
            ## Acceptance Criteria
            Just some text, no checklist items.
            ## Verification Plan
            - [ ] Verify something
            ## Review Expectations
            - accessibility: **required**
            - usability / content: **waived**
            - documentation: **N/A**
            - hygiene: **deferred**
            ## Slices
            1. First slice
            """)
        comments_json = self._comments_json([plan])
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("plan.sh", "", python3_mock=py)
        assert any("checklist" in u.lower() for u in unmet)

    def test_fail_review_expectations_missing_dispositions(self):
        plan = textwrap.dedent("""\
            ## Implementation Plan
            Content here.
            ## Acceptance Criteria
            - [ ] First criterion
            ## Verification Plan
            - [ ] Verify something
            ## Review Expectations
            - accessibility: TBD
            - usability / content: TBD
            - documentation: TBD
            - hygiene: TBD
            ## Slices
            1. First slice
            """)
        comments_json = self._comments_json([plan])
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("plan.sh", "", python3_mock=py)
        assert any("Review Expectations" in u for u in unmet)


# ---------------------------------------------------------------------------
# design.sh
# ---------------------------------------------------------------------------

class TestDesign:
    def test_fail_no_discussion_url(self):
        body = "No discussion link here"
        comments_json = json.dumps({"comments": []})
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("design.sh", body, python3_mock=py)
        assert any("Discussion" in u for u in unmet)

    def test_url_detected_in_body(self):
        """When a discussion URL is found in the body, the 'no discussion' error should not appear.

        The script will then try to fetch discussion details via gh api graphql;
        our gh mock returns {}, so we expect downstream errors but NOT the
        'no discussion linked' error.
        """
        body = "See https://github.com/SlateLabs/test-repo/discussions/7 for design."
        comments_json = json.dumps({"comments": []})
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        # gh mock returns valid-ish graphql response
        gh = textwrap.dedent("""\
            gh() {
                echo '{"data":{"repository":{"discussion":{"body":"## Summary\\n## Problem\\n## Goals\\n## Non-goals\\n## Proposed Approach\\n## Open Questions\\n- ~~resolved~~","author":{"login":"alice"},"comments":{"nodes":[{"author":{"login":"bob"}}]}}}}}'
            }""")
        unmet = _run_gate("design.sh", body, gh_mock=gh, python3_mock=py)
        assert not any("must be linked" in u for u in unmet)

    def test_url_detected_in_comments(self):
        body = "No URL here"
        marker = "gpa:design-discussion:#42"
        comment_with_url = f"{marker}\nhttps://github.com/SlateLabs/test-repo/discussions/7"
        comments_json = json.dumps({"comments": [{"body": comment_with_url}]})
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        gh = textwrap.dedent("""\
            gh() {
                echo '{"data":{"repository":{"discussion":{"body":"## Summary\\n## Problem\\n## Goals\\n## Non-goals\\n## Proposed Approach\\n## Open Questions\\n- ~~done~~","author":{"login":"alice"},"comments":{"nodes":[{"author":{"login":"bob"}}]}}}}}'
            }""")
        unmet = _run_gate("design.sh", body, gh_mock=gh, python3_mock=py)
        assert not any("must be linked" in u for u in unmet)

    def test_fail_wrong_org_discussion(self):
        body = "See https://github.com/OtherOrg/other-repo/discussions/7"
        gh = textwrap.dedent("""\
            gh() {
                echo '{"data":{"repository":{"discussion":{"body":"## Summary\\n## Problem\\n## Goals\\n## Non-goals\\n## Proposed Approach\\n## Open Questions\\n- ~~done~~","author":{"login":"alice"},"comments":{"nodes":[{"author":{"login":"bob"}}]}}}}}'
            }""")
        comments_json = json.dumps({"comments": []})
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("design.sh", body, gh_mock=gh, python3_mock=py)
        assert any("same org" in u.lower() for u in unmet)

    def test_fail_missing_required_headings(self):
        body = "See https://github.com/SlateLabs/test-repo/discussions/7"
        # Discussion body is missing required headings
        gh = textwrap.dedent("""\
            gh() {
                echo '{"data":{"repository":{"discussion":{"body":"Just some text\\n## Open Questions\\n- ~~done~~","author":{"login":"alice"},"comments":{"nodes":[{"author":{"login":"bob"}}]}}}}}'
            }""")
        comments_json = json.dumps({"comments": []})
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("design.sh", body, gh_mock=gh, python3_mock=py)
        assert any("Summary" in u for u in unmet)
        assert any("Problem" in u for u in unmet)
        assert any("Goals" in u for u in unmet)

    def test_fail_no_review_comments(self):
        body = "See https://github.com/SlateLabs/test-repo/discussions/7"
        # No comments from anyone other than the author
        gh = textwrap.dedent("""\
            gh() {
                echo '{"data":{"repository":{"discussion":{"body":"## Summary\\n## Problem\\n## Goals\\n## Non-goals\\n## Proposed Approach\\n## Open Questions\\n- ~~done~~","author":{"login":"alice"},"comments":{"nodes":[{"author":{"login":"alice"}}]}}}}}'
            }""")
        comments_json = json.dumps({"comments": []})
        py = f'python3() {{ echo \'{comments_json}\'; }}'
        unmet = _run_gate("design.sh", body, gh_mock=gh, python3_mock=py)
        assert any("no comments from anyone other than" in u.lower() for u in unmet)


# ---------------------------------------------------------------------------
# merge.sh
# ---------------------------------------------------------------------------

class TestMerge:
    def test_fail_no_open_pr(self):
        py = 'python3() { echo "{}"; }'
        # gh for approval comments returns nothing
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("merge.sh", "", python3_mock=py, gh_mock=gh)
        assert any("No open PR" in u for u in unmet)

    def test_pass_with_open_pr_and_auto_approve(self):
        def _py_mock():
            # First call: latest-pr (open) → returns PR
            # Second call: gh issue view (approval) → handled by gh mock
            # Third call: latest-agent-review → returns auto-approve
            return textwrap.dedent("""\
                python3() {
                    if [[ "$*" == *"latest-pr"* ]]; then
                        echo '{"number": 99}'
                    elif [[ "$*" == *"latest-agent-review"* ]]; then
                        echo '{"disposition": "auto-approve"}'
                    else
                        echo '{}'
                    fi
                }""")

        gh = 'gh() { echo ""; }'
        unmet = _run_gate("merge.sh", "", python3_mock=_py_mock(), gh_mock=gh)
        assert unmet == []

    def test_fail_no_approval(self):
        py = textwrap.dedent("""\
            python3() {
                if [[ "$*" == *"latest-pr"* ]]; then
                    echo '{"number": 99}'
                elif [[ "$*" == *"latest-agent-review"* ]]; then
                    echo '{"disposition": "needs-changes"}'
                else
                    echo '{}'
                fi
            }""")
        gh = 'gh() { echo ""; }'
        unmet = _run_gate("merge.sh", "", python3_mock=py, gh_mock=gh)
        assert any("approval" in u.lower() for u in unmet)


# ---------------------------------------------------------------------------
# closeout.sh
# ---------------------------------------------------------------------------

class TestCloseout:
    def test_fail_no_merged_pr(self):
        py = textwrap.dedent("""\
            python3() {
                if [[ "$1" == "-c" ]]; then
                    cat >/dev/null
                    echo "0"
                elif [[ "$*" == *"latest-pr"* ]]; then
                    echo '{}'
                elif [[ "$*" == *"issue-comments"* ]]; then
                    echo '{"comments":[]}'
                else
                    echo '{}'
                fi
            }""")
        gh = 'gh() { return 1; }'
        unmet = _run_gate("closeout.sh", "", python3_mock=py, gh_mock=gh, check_mode="pre-scaffold")
        assert any("No merged PR" in u for u in unmet)

    def test_fail_branch_still_exists(self):
        py = textwrap.dedent("""\
            python3() {
                if [[ "$1" == "-c" ]]; then
                    cat >/dev/null
                    echo "0"
                elif [[ "$*" == *"latest-pr"* ]]; then
                    echo '{"number": 99, "headRefName": "42-feature"}'
                elif [[ "$*" == *"issue-comments"* ]]; then
                    echo '{"comments":[]}'
                else
                    echo '{}'
                fi
            }""")
        # gh api for branch check succeeds (branch exists)
        gh = textwrap.dedent("""\
            gh() {
                if [[ "$1" == "api" && "$2" == *"branches"* ]]; then
                    return 0
                fi
                return 1
            }""")
        unmet = _run_gate("closeout.sh", "", python3_mock=py, gh_mock=gh, check_mode="pre-scaffold")
        assert any("branch" in u.lower() and "still exists" in u.lower() for u in unmet)

    def test_fail_no_follow_up_evidence(self):
        """With a merged PR but no follow-up markers, the follow-up check should fail."""
        # The closeout script pipes comments JSON into `python3 -c "..."` for
        # follow-up counting.  Our mock must handle both the script invocations
        # and the inline `-c` call (which reads stdin).
        py = textwrap.dedent("""\
            python3() {
                if [[ "$1" == "-c" ]]; then
                    # Inline python call for follow-up counting — just echo 0
                    cat >/dev/null
                    echo "0"
                elif [[ "$*" == *"latest-pr"* ]]; then
                    echo '{"number": 99, "headRefName": "42-feature"}'
                elif [[ "$*" == *"issue-comments"* ]]; then
                    echo '{"comments":[]}'
                else
                    echo '{}'
                fi
            }""")
        # Branch already deleted
        gh = 'gh() { return 1; }'
        unmet = _run_gate("closeout.sh", "", python3_mock=py, gh_mock=gh, check_mode="pre-scaffold")
        assert any("follow-up" in u.lower() for u in unmet)

    def test_pre_scaffold_skips_scaffold_checks(self):
        """In pre-scaffold mode, closeout scaffold content checks (4-7) are skipped."""
        py = textwrap.dedent("""\
            python3() {
                if [[ "$1" == "-c" ]]; then
                    cat >/dev/null
                    echo "0"
                elif [[ "$*" == *"latest-pr"* ]]; then
                    echo '{"number": 99, "headRefName": "42-feature"}'
                elif [[ "$*" == *"issue-comments"* ]]; then
                    echo '{"comments":[{"body":"gpa:follow-up-status:#42"}]}'
                else
                    echo '{}'
                fi
            }""")
        gh = 'gh() { return 1; }'
        unmet = _run_gate("closeout.sh", "", python3_mock=py, gh_mock=gh, check_mode="pre-scaffold")
        # Should not contain scaffold-related errors
        assert not any("closeout scaffold" in u.lower() for u in unmet)
        assert not any("Closeout heading" in u for u in unmet)

    def test_full_mode_requires_scaffold_comment(self):
        """In full mode, missing scaffold comment is flagged."""
        py = textwrap.dedent("""\
            python3() {
                if [[ "$1" == "-c" ]]; then
                    cat >/dev/null
                    echo "0"
                elif [[ "$*" == *"latest-pr"* ]]; then
                    echo '{"number": 99, "headRefName": "42-feature"}'
                elif [[ "$*" == *"issue-comments"* ]]; then
                    echo '{"comments":[{"body":"gpa:follow-up-status:#42"}]}'
                else
                    echo '{}'
                fi
            }""")
        gh = 'gh() { return 1; }'
        unmet = _run_gate("closeout.sh", "", python3_mock=py, gh_mock=gh, check_mode="full")
        assert any("closeout scaffold" in u.lower() or "closeout retrospective" in u.lower() for u in unmet)
