#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def read(path: str) -> str:
    return Path(path).read_text()


def write_output(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text)
        return
    print(text, end="" if text.endswith("\n") else "\n")


def build_design_author() -> str:
    return f"""You are Codex acting as the design author for a GitHub workflow orchestration system.

Task:
- Produce a complete replacement body for the GitHub discussion associated with issue #{env("ISSUE_NUMBER")}.
- The output must be valid Markdown only. Do not wrap it in code fences.
- Keep the owned-artifact marker and source-issue lines.
- Replace placeholder text with substantive content derived from the issue.
- Resolve every open question by either answering it directly in the proposal or marking it `DEFERRED-TO-PLAN`.
- Make the design specific enough that the next `plan` stage can proceed without operator clarification.
- Do not invent unrelated scope or infrastructure not implied by the issue.

Required structure:
- # Design Discussion: <issue title>
- owned-artifact marker comment
- source issue lines
- ## Summary
- ## Problem
- ## Goals
- ## Non-goals
- ## Proposed Approach
- ## Open Questions
- ## Exit Criteria

Guidance:
- The proposal should preserve the issue's intent and acceptance criteria.
- Prefer concrete workflow/state-machine changes over abstract architecture prose.
- For open questions that are better answered later, mark them `DEFERRED-TO-PLAN`.
- The exit criteria checklist should be marked complete if the generated body itself satisfies the design gate.

Source issue title:
{env("ISSUE_TITLE")}

Source issue body:
---
{env("ISSUE_BODY")}
---

Existing discussion body:
---
{env("DISCUSSION_BODY")}
---
"""


def build_design_review() -> str:
    return f"""Review the following design discussion for issue #{env("ISSUE_NUMBER")} and produce structured JSON only.

Review goals:
- Check whether the design is coherent, specific, and aligned to the source issue.
- Prefer actionable critique over generic praise.
- If the design is good enough for planning, say so clearly.
- The review comment should read like a concise review from a second agent, not an approval checkbox dump.
- Do not ask the operator to do work unless absolutely necessary.
- Reply with markdown only. Do not wrap the response in JSON, YAML, or code fences.
- Start the comment with `gpa:design-review:auto`.

Source issue title:
{env("ISSUE_TITLE")}

Source issue body:
---
{env("ISSUE_BODY")}
---

Proposed design discussion:
---
{read(env("DISCUSSION_FILE"))}
---
"""


def build_plan_author() -> str:
    return f"""You are Codex acting as the implementation planner for issue #{env("ISSUE_NUMBER")}.

Task:
- Produce a complete replacement body for the GitHub issue comment that holds the implementation plan.
- Output valid Markdown only. Do not wrap it in code fences.
- Preserve the owned-artifact marker and source issue lines.
- Replace placeholder text with substantive content derived from the issue and design discussion.
- Make the plan concrete enough that the execution stage can proceed autonomously with minimal operator input.
- Keep the work bounded; do not invent unrelated scope.

Required structure:
- # Implementation Plan: <issue title>
- owned-artifact marker comment
- source issue lines
- ## Implementation Plan
- ## Acceptance Criteria
- ## Verification Plan
- ## Review Expectations
- ## Slices
- ## Exit Criteria

Hard requirements:
- Acceptance Criteria must contain checklist items.
- Verification Plan must contain checklist items.
- Review Expectations must include explicit dispositions for Accessibility, Usability/content, Documentation, and Hygiene.
- Slices must be numbered and specific enough to execute in order.
- Exit Criteria may mark items complete when the generated plan itself satisfies them.

Source issue title:
{env("ISSUE_TITLE")}

Source issue body:
---
{env("ISSUE_BODY")}
---

Design discussion:
---
{env("DESIGN_BODY")}
---

Existing plan comment:
---
{env("PLAN_BODY")}
---
"""


def build_plan_review() -> str:
    return f"""Review the following implementation plan for issue #{env("ISSUE_NUMBER")}.

Review goals:
- Check whether the plan is bounded, executable, and aligned to the issue and design.
- Prefer actionable critique over generic praise.
- If the plan is good enough for execution, say so clearly.
- Reply with markdown only. Do not wrap the response in JSON, YAML, or code fences.
- Start the comment with `gpa:plan-review:auto`.
- Keep the review concise and execution-oriented.

Source issue title:
{env("ISSUE_TITLE")}

Source issue body:
---
{env("ISSUE_BODY")}
---

Proposed implementation plan:
---
{read(env("PLAN_FILE"))}
---
"""


def build_execution_author() -> str:
    return f"""You are Codex acting as the execution agent for issue #{env("ISSUE_NUMBER")} on branch {env("BRANCH_NAME")}.

Task:
- Implement the smallest coherent slice of the approved implementation plan directly in this repository.
- Make real code and/or workflow changes; do not stop at comments or placeholder files.
- Keep the change bounded to the issue and implementation plan.
- Update any repository files necessary for the change to be reviewable.
- Do not merge or open the PR yourself; the workflow will handle that.

Required outcomes:
- Leave the workspace with concrete file changes suitable for a review-ready PR.
- Prefer a thin but functional vertical slice over a broad partial rewrite.
- If the plan implies a new contract or docs that must change with code, update them now.

Stage:
{env("REQUESTED_STAGE")}

Source issue title:
{env("ISSUE_TITLE")}

Source issue body:
---
{env("ISSUE_BODY")}
---

Implementation plan:
---
{env("PLAN_BODY")}
---

Operator feedback to address (if any):
---
{env("FEEDBACK_BODY")}
---

Feedback source:
{env("FEEDBACK_SOURCE")}
"""


def build_agent_review() -> str:
    return f"""You are the autonomous agent reviewer for issue #{env("ISSUE_NUMBER")}.

Review the proposed implementation and write markdown to the repository file `{env("REVIEW_FILE")}`.

Required file structure:
- Include exactly one HTML comment line in this format:
  `<!-- gpa:artifact-payload:<json> -->`
- JSON must use this envelope:
  - `kind`: `artifact_payload`
  - `version`: `gpa.v1`
  - `stage`: `agent-review`
  - `data.disposition`: one of `auto-approve`, `rework-required`, `operator-review-required`
  - `data.decision.next_stage`: one of `merge`, `execution`, or empty string
  - `data.decision.reason_codes`: non-empty array of machine-readable reason codes
- Then a blank line
- Then a section `## Summary`
- Then a short paragraph
- Then a section `## Feedback`
- Then markdown bullets or short paragraphs for the next actor

Decision rules:
- Use "auto-approve" when the PR is coherent, bounded, and safe to merge without operator review.
- Use "rework-required" when the automation should make another implementation pass on its own.
- Use "operator-review-required" only for exceptional situations: unresolved product ambiguity, risky/destructive changes, security/permission concerns, missing deployability where user interaction is required, or changes that require a human judgment call.
- Keep disposition and decision.next_stage consistent:
  - auto-approve -> merge
  - rework-required -> execution
  - operator-review-required -> empty string
- Default to "auto-approve" unless there is a concrete reason not to.
- Do not ask for operator review just because the change is incomplete; prefer "rework-required" in that case.
- Do not modify any tracked repository files other than writing `{env("REVIEW_FILE")}`.
- Do not print the review in prose; write the file directly.

Issue title:
{env("ISSUE_TITLE")}

Issue body:
---
{env("ISSUE_BODY")}
---

PR title:
{env("PR_TITLE")}

PR URL:
{env("PR_URL")}

PR body:
---
{env("PR_BODY")}
---

Changed files:
---
{env("FILES_SUMMARY")}
---

Diff excerpt:
---
{read(env("DIFF_FILE"))}
---
"""


def build_merge_conflict() -> str:
    return f"""You are Codex resolving merge conflicts on branch {env("BRANCH_NAME")} for issue #{env("ISSUE_NUMBER")} and PR #{env("PR_NUMBER")}.

The workflow attempted to merge origin/{env("BASE_REF")} into the feature branch before final merge and Git reported conflicts.

Required outcome:
- Resolve the merge conflicts in the repository working tree.
- Preserve the feature intent from the branch while incorporating the latest safe changes from origin/{env("BASE_REF")}.
- Leave the repository in a state where there are no unmerged files and the merge can be committed.

Constraints:
- Focus on the conflicted files first.
- Do not abandon the merge or reset the branch.
- Do not make unrelated refactors.
- Keep behavior coherent with the issue and the latest main-branch contracts.

Source issue title:
{env("ISSUE_TITLE")}

Source issue body:
---
{env("ISSUE_BODY")}
---

Conflicted files:
---
{env("CONFLICT_FILES")}
---
"""


BUILDERS = {
    "design-author": build_design_author,
    "design-review": build_design_review,
    "plan-author": build_plan_author,
    "plan-review": build_plan_review,
    "execution-author": build_execution_author,
    "agent-review": build_agent_review,
    "merge-conflict": build_merge_conflict,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(BUILDERS))
    parser.add_argument("--output")
    args = parser.parse_args()
    write_output(BUILDERS[args.mode](), args.output)


if __name__ == "__main__":
    main()
