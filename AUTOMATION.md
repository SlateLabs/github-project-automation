# Automation Overview

This repository hosts the shared orchestration system for agent-driven issue delivery. The implementation is intentionally split between:

- a single operator-facing orchestrator: [`.github/workflows/orchestration-dispatch.yml`](/Users/jlamb/Projects/slatelabs/github-project-automation/.github/workflows/orchestration-dispatch.yml)
- reusable internal stage workflows under [`.github/workflows/`](/Users/jlamb/Projects/slatelabs/github-project-automation/.github/workflows)
- the webhook gateway under [`gateway/`](/Users/jlamb/Projects/slatelabs/github-project-automation/gateway)
- the machine contract schema at [`.github/schemas/orchestration-contract-v1.json`](/Users/jlamb/Projects/slatelabs/github-project-automation/.github/schemas/orchestration-contract-v1.json)

## Read this first

- Operator usage and stage vocabulary:
  [docs/automation/operator-runbook.md](/Users/jlamb/Projects/slatelabs/github-project-automation/docs/automation/operator-runbook.md)
- Participating repository requirements:
  [docs/automation/repository-contract.md](/Users/jlamb/Projects/slatelabs/github-project-automation/docs/automation/repository-contract.md)
- Gateway webhook and dispatch behavior:
  [docs/automation/gateway-contract.md](/Users/jlamb/Projects/slatelabs/github-project-automation/docs/automation/gateway-contract.md)

## Current shape

- `orchestration-dispatch.yml` is the only required participating-repo workflow entrypoint.
- `execution` handles both initial implementation and feedback-driven rework.
- `agent-review` handles both automated review outcomes and operator review waiting states.
- Automatic handoff and project status sync are driven from a shared stage map in [config/orchestration-stage-map.json](/Users/jlamb/Projects/slatelabs/github-project-automation/config/orchestration-stage-map.json).

## Internal implementation notes

- Reusable stage workflows are internal plumbing; GitHub may show them by file path in the Actions UI.
- Gateway operator commands and orchestration handoff rules are deliberately sourced from the same stage map to reduce drift.
- Checkpoint comments remain the machine-readable source of truth for stage outcomes and next-stage decisions.
