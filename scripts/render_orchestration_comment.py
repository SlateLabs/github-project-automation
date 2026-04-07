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


TEMPLATES = {
    "operator-review-ready": operator_review_ready,
    "duplicate": duplicate,
    "gate-failed": gate_failed,
    "ineligible": ineligible,
    "merge-remediation": merge_remediation,
    "next-stage-queued": next_stage_queued,
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
