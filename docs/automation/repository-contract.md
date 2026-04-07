# Repository Contract

## Required repo-local workflows

- `orchestration-dispatch.yml`
- `retry-stage.yml` is optional

Internal reusable workflows in this repo are implementation details and are not part of the participating-repo contract.

## Required GitHub features

- GitHub Actions enabled
- GitHub Discussions enabled
- `Ideas` discussion category available for design scaffolding

## Required labels

- `do-not-automate`
- `blocked`
- `follow-up`
- `blocking`
- `technical-debt`
- `accessibility`
- `usability`
- `documentation`
- `automation`
- `defect`

## Artifact contract

- Structured orchestration state is stored in checkpoint comments.
- Durable content lives in GitHub artifacts:
  - issue body
  - discussion
  - issue comments
  - PRs

Canonical contracts are defined in:
- [`.github/schemas/orchestration-contract-v1.json`](/Users/jlamb/Projects/slatelabs/github-project-automation/.github/schemas/orchestration-contract-v1.json)

## Dispatch payload

`repository_dispatch` uses event type `orchestration-start` with payload fields:

- `issue_number`
- `issue_title`
- `requested_stage`
- `run_key`
- `actor`
- `timestamp`
- `project_item_id`
- optional `feedback_source`
- optional `feedback_body`

Allowed `requested_stage` values match the public stage vocabulary from the operator runbook.
