#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os


def e(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def duplicate() -> str:
    return f"""### Orchestration run — skipped (duplicate)
<!-- gpa:run-status:{e("REQUESTED_STAGE")}:skipped:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Requested stage** | `{e("REQUESTED_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :fast_forward: Skipped — recent run detected |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

A successful run for this issue/stage completed within the last {e("DEDUP_WINDOW_SECONDS")}s.
Re-trigger after the dedup window expires, or post `GATE-WAIVER: dedup — <reason>` to force.
"""


def ineligible() -> str:
    return f"""### Orchestration run — ineligible
<!-- gpa:run-status:{e("REQUESTED_STAGE")}:failed:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Requested stage** | `{e("REQUESTED_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :x: Ineligible |
| **Reason** | {e("REASON")} |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |
"""


def gate_failed() -> str:
    unmet = e("UNMET_LIST", "- (none)")
    waived = e("WAIVED_LIST", "- (none)")
    checkpoint_line = f"<!-- gpa:checkpoint {e('CHECKPOINT')} -->" if e("CHECKPOINT") else ""
    return f"""### Orchestration run — gate not satisfied
<!-- gpa:run-status:{e("REQUESTED_STAGE")}:failed:{e("RUN_KEY")} -->
{checkpoint_line}

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Requested stage** | `{e("REQUESTED_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :warning: Gate conditions not met |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

**Unmet conditions:**
{unmet}

**Waived conditions:**
{waived}

To override, post a comment: `GATE-WAIVER: <condition> — <reason>` and re-trigger.
"""


def state_mismatch() -> str:
    return f"""### Orchestration run — superseded (state mismatch)
<!-- gpa:run-status:{e("REQUESTED_STAGE")}:failed:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Requested stage** | `{e("REQUESTED_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :stop_sign: Superseded — state changed during run |
| **Reason** | {e("REASON")} |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |
"""


def operator_review_ready() -> str:
    return f"""### Review-ready implementation
<!-- gpa:run-status:agent-review:waiting:{e("RUN_KEY")} -->
<!-- gpa:checkpoint {e("CHECKPOINT")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Actor** | @{e("ACTOR")} |
| **PR** | {e("PR_URL")} |
| **Branch** | `{e("BRANCH_NAME")}` |
| **Deployment URL** | {e("DEPLOYMENT_URL")} |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

The implementation is ready for operator review.

To request changes, comment on this issue with:
`gpa:feedback <what should change>`

To approve and continue to merge/finalize, comment on this issue with:
`gpa:approve`
"""


def merge_remediation() -> str:
    return f"""### Merge requires conflict resolution
<!-- gpa:run-status:merge:failed:{e("RUN_KEY")} -->
<!-- gpa:checkpoint {e("CHECKPOINT")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :warning: Automatic sync with `main` hit merge conflicts |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

The merge lane attempted to sync the feature branch with `main` before final merge, then attempted an automated conflict-resolution pass, but the branch still requires manual reconciliation.

Next step:
- re-run `execution` to reconcile the branch against the latest `main`
"""


def stage_transition() -> str:
    waived_section = ""
    if e("WAIVED_SECTION"):
        waived_section = e("WAIVED_SECTION")
    return f"""### Orchestration run — stage transition accepted
<!-- gpa:run-status:{e("REQUESTED_STAGE")}:completed:{e("RUN_KEY")} -->
{e("CANONICAL_CHECKPOINT_LINE")}
{e("CHECKPOINT_LINE")}

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Requested stage** | `{e("REQUESTED_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :white_check_mark: Eligible and gate passed |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |
{waived_section}
"""


def next_stage_queued() -> str:
    return f"""### Orchestration run — next stage queued
<!-- gpa:run-status:{e("NEXT_STAGE")}:started:{e("NEXT_RUN_KEY")} -->
<!-- gpa:checkpoint {e("CHECKPOINT")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("NEXT_RUN_KEY")}` |
| **Requested stage** | `{e("NEXT_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :rocket: Next stage queued automatically |
| **Parent run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

The next stage was dispatched automatically after the current stage passed.
"""


def retry_ineligible() -> str:
    return f"""### Retry stage — ineligible
<!-- gpa:run-status:{e("TARGET_STAGE")}:failed:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Target stage** | `{e("TARGET_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :x: Ineligible for retry |
| **Reason** | {e("REASON")} |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |
"""


def retry_dispatch_failed() -> str:
    return f"""### Retry stage — dispatch failed
<!-- gpa:run-status:{e("TARGET_STAGE")}:failed:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Target stage** | `{e("TARGET_STAGE")}` |
| **Workflow** | `orchestration-dispatch.yml` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :x: Failed to dispatch orchestrator |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |
"""


def retry_dispatched() -> str:
    return f"""### Retry stage — dispatched
<!-- gpa:run-status:{e("TARGET_STAGE")}:started:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Target stage** | `{e("TARGET_STAGE")}` |
| **Workflow** | `orchestration-dispatch.yml` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :arrows_counterclockwise: Retry dispatched |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

The canonical orchestrator has been dispatched for issue #{e("ISSUE_NUMBER")} with `requested_stage: {e("REQUESTED_STAGE")}`.
Check the Actions tab for the dispatched run status.
"""


def agent_review_summary() -> str:
    return f"""### Agent review
<!-- gpa:run-status:agent-review:completed:{e("RUN_KEY")} -->
<!-- gpa:checkpoint-v1 {e("CANONICAL_CHECKPOINT")} -->
<!-- gpa:checkpoint {e("CHECKPOINT")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **PR** | {e("PR_URL")} |
| **PR head SHA** | `{e("PR_HEAD_SHA")}` |
| **Disposition** | `{e("DISPOSITION")}` |

{e("SUMMARY")}

{e("FEEDBACK_BODY")}
"""


def _status_template(title: str, markers: str, table_rows: str, body: str, payload_line: str = "") -> str:
    payload = f"{payload_line}\n" if payload_line else ""
    return f"""### {title}
{markers}
{payload}
{table_rows}

{body}
"""


def design_scaffold_exists() -> str:
    return _status_template(
        "Design discussion scaffold — already exists",
        f"<!-- {e('ARTIFACT_MARKER')} -->\n<!-- gpa:run-status:design:skipped:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A design discussion is already linked to this issue. No new discussion was created.",
    )


def design_scaffold_created() -> str:
    return _status_template(
        "Design discussion scaffold — created",
        f"<!-- gpa:design-discussion:#{e('ISSUE_NUMBER')} -->\n<!-- gpa:run-status:design:completed:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A design discussion has been created with all required gate headings.\nFill in each section, resolve open questions, and get at least one review comment to pass the design gate.",
    )


def execution_scaffold_exists() -> str:
    return _status_template(
        "Execution bootstrap scaffold — already exists",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:execution:skipped:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A PR for this issue already exists. No new branch or PR was created.",
    )


def execution_branch_prepared() -> str:
    return _status_template(
        "Execution bootstrap scaffold — branch prepared",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:execution:prepared:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A feature branch has been prepared for agent implementation. PR creation will occur after code changes are pushed.",
    )


def execution_scaffold_created() -> str:
    return _status_template(
        "Execution bootstrap scaffold — created",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:execution:completed:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A feature branch and draft PR have been created for this issue.\nFill in the PR body sections and mark the PR ready for review when implementation is complete.",
    )


def plan_scaffold_exists() -> str:
    return _status_template(
        "Implementation plan scaffold — already exists",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:plan:skipped:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "An implementation plan comment already exists on this issue. No new comment was created.",
    )


def plan_scaffold_created() -> str:
    return _status_template(
        "Implementation plan scaffold — created",
        f"<!-- gpa:impl-plan-status:#{e('ISSUE_NUMBER')} -->\n<!-- gpa:run-status:plan:completed:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "An implementation plan comment has been created with all required gate headings.\nFill in each section with substantive content to pass the plan gate.",
    )


def closeout_scaffold_exists() -> str:
    return _status_template(
        "Closeout scaffold — already exists",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:closeout:skipped:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A closeout retrospective comment for this issue already exists. No duplicate was created.",
        f"<!-- gpa:artifact-payload:{e('ARTIFACT_PAYLOAD')} -->",
    )


def closeout_scaffold_created() -> str:
    return _status_template(
        "Closeout scaffold — created",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:closeout:completed:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "A closeout retrospective comment has been posted on this issue.\nReview the retrospective sections and complete the exit checklist before closing the issue.",
        f"<!-- gpa:artifact-payload:{e('ARTIFACT_PAYLOAD')} -->",
    )


def closeout_pre_scaffold_failed() -> str:
    return f"""### Orchestration run — closeout pre-scaffold gate failed
<!-- gpa:run-status:{e("REQUESTED_STAGE")}:failed:{e("RUN_KEY")} -->

| Field | Value |
|-------|-------|
| **Run key** | `{e("RUN_KEY")}` |
| **Requested stage** | `{e("REQUESTED_STAGE")}` |
| **Actor** | @{e("ACTOR")} |
| **Result** | :x: Prerequisites not met — scaffold not posted |
| **Actions run** | [{e("RUN_ID")}]({e("RUN_URL")}) |

**Unmet prerequisites:**
{e("UNMET_LIST")}

**Waived conditions:**
{e("WAIVED_LIST")}

Resolve the unmet prerequisites and re-trigger.
"""


def followup_none() -> str:
    return _status_template(
        "Follow-up capture — no markers found",
        f"<!-- {e('STATUS_MARKER')} -->\n<!-- gpa:run-status:follow-up-capture:completed:{e('RUN_KEY')} -->",
        e("TABLE_ROWS"),
        "No `<!-- FOLLOW-UP: ... -->` markers were found in issue comments.",
        f"<!-- gpa:artifact-payload:{e('ARTIFACT_PAYLOAD')} -->",
    )


def followup_complete() -> str:
    return f"""### Follow-up capture — complete
<!-- {e("STATUS_MARKER")} -->
<!-- gpa:run-status:follow-up-capture:completed:{e("RUN_KEY")} -->
<!-- gpa:artifact-payload:{e("ARTIFACT_PAYLOAD")} -->

{e("META_ROWS")}

{e("TABLE_HEADER")}
{e("SUMMARY_ROWS")}

Follow-up issues have been created from `<!-- FOLLOW-UP: ... -->` markers in this issue's comments.
"""


TEMPLATES = {
    "agent-review-summary": agent_review_summary,
    "closeout-scaffold-created": closeout_scaffold_created,
    "closeout-pre-scaffold-failed": closeout_pre_scaffold_failed,
    "closeout-scaffold-exists": closeout_scaffold_exists,
    "design-scaffold-created": design_scaffold_created,
    "design-scaffold-exists": design_scaffold_exists,
    "operator-review-ready": operator_review_ready,
    "duplicate": duplicate,
    "execution-branch-prepared": execution_branch_prepared,
    "execution-scaffold-created": execution_scaffold_created,
    "execution-scaffold-exists": execution_scaffold_exists,
    "followup-complete": followup_complete,
    "followup-none": followup_none,
    "gate-failed": gate_failed,
    "ineligible": ineligible,
    "merge-remediation": merge_remediation,
    "next-stage-queued": next_stage_queued,
    "plan-scaffold-created": plan_scaffold_created,
    "plan-scaffold-exists": plan_scaffold_exists,
    "retry-dispatched": retry_dispatched,
    "retry-dispatch-failed": retry_dispatch_failed,
    "retry-ineligible": retry_ineligible,
    "stage-transition": stage_transition,
    "state-mismatch": state_mismatch,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("template", choices=sorted(TEMPLATES))
    args = parser.parse_args()
    print(TEMPLATES[args.template](), end="")


if __name__ == "__main__":
    main()
