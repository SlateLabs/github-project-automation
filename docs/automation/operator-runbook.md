# Operator Runbook

## Entry points

- Use `orchestration-dispatch.yml` for manual stage execution.
- Use `retry-stage.yml` only when you need a dedicated retry affordance.
- Trusted issue comments supported by the gateway:
  - `gpa:feedback <instructions>`
  - `gpa:approve`

## Public stage vocabulary

- `kickoff`
- `clarification`
- `design`
- `plan`
- `execution`
- `agent-review`
- `follow-up-capture`
- `merge`
- `closeout`

## Operator expectations

- `execution` with operator feedback may pause in `In Review` when no branch progress is detected.
- `agent-review` may:
  - advance to `merge`
  - send work back to `execution`
  - pause in `In Review` for operator approval or feedback
- `merge` may stop for manual remediation if pre-merge sync conflicts cannot be resolved automatically.

## Retry guidance

- Re-run the same stage if the run failed before gate pass.
- Use `execution` for both new implementation work and feedback-driven rework.
- Use `merge` only after the PR is review-ready and approvals are in place.
