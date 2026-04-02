# GitHub Project Automation

This repo is the central home for SlateLabs org-level workflow orchestration. It owns:

- **Orchestration contracts**: stage model, gate definitions, trigger eligibility, trusted-actor policy, idempotency model
- **Shared workflows and actions**: reusable GitHub Actions that participating repos call at a pinned ref
- **Configuration**: trust policy and participating repo registry
- **Webhook gateway**: Cloud Run listener that routes org project events to participating repos (issue #2)

Canonical design: [discussion #3](https://github.com/SlateLabs/github-project-automation/discussions/3)
Implementation plan: [issue #1](https://github.com/SlateLabs/github-project-automation/issues/1)

## Repo structure

```
config/
  trust-policy.yml    — trusted-actor policy (who may trigger automation)
  repos.yml           — participating repos and their configuration
templates/            — shared prompt/scaffold templates
scripts/              — validation and utility scripts
.github/
  workflows/          — orchestration workflows (dispatch, reusable)
  actions/            — composite actions (validate-eligibility, check-gate)
```

## How participating repos integrate

1. Create a repo from `repo-template` (or manually add the orchestration workflow)
2. The repo-local workflow calls shared reusable workflows from this repo at a pinned ref:
   ```yaml
   uses: SlateLabs/github-project-automation/.github/workflows/<name>.yml@v0.1.0
   ```
3. Pin `<ref>` to a release tag or SHA — never pin to a mutable branch
4. Upgrade by bumping the pinned ref; release notes document breaking changes

## Entry points

| Path | Trigger | Description |
|------|---------|-------------|
| Manual kickoff | `workflow_dispatch` in participating repo | Operator provides `issue_number` and `requested_stage`; workflow validates eligibility and gates |
| Webhook gateway | `projects_v2_item` org event → Cloud Run → `repository_dispatch` | Automated trigger when project item status changes (issue #2) |

Both paths converge on the same gate-checking logic. Eligibility validation is shared but not yet at full parity: the manual path validates issue state, actor trust, labels, and body content; the webhook gateway path will additionally validate live project-field state (Status transition, Repository mapping, project linkage) once implemented (see [issue #9](https://github.com/SlateLabs/github-project-automation/issues/9)).

## Trust policy

Defined in `config/trust-policy.yml`. See [discussion #3 §8](https://github.com/SlateLabs/github-project-automation/discussions/3) for the full decision model.

**Current limitation:** Only `trusted_users` is enforced. Org team membership resolution (`trusted_teams`) requires the org API and is deferred to [issue #5](https://github.com/SlateLabs/github-project-automation/issues/5). Actors not listed in `trusted_users` will be rejected even if they belong to a trusted team. The trust check fails closed — write access to the repo is necessary but not sufficient.

## Stage model

The default workflow stages are: Backlog → Clarification → Design → Plan → Execution → Review → Merge → Closeout. Each transition has machine-testable gate conditions defined in discussion #3 §4.

## Operator actions

| Action | How |
|--------|-----|
| View run status | Check automation comment on the issue, or Actions run |
| Retry failed run | Re-trigger via `workflow_dispatch` with issue number and target stage |
| Waive a gate | Post `GATE-WAIVER: <gate-name> — <reason>` on the issue/PR |
| Block automation | Add `do-not-automate` label to the issue |
