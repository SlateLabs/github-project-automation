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

## Stage actions

Stage actions run automatically after eligibility validation passes. Some actions (like the design scaffold) run **before** their gate check to create the artifacts the gate will then evaluate; others run after gate checks pass. Each action's trigger timing is documented below.

### Design discussion scaffold

**Trigger:** `workflow_dispatch` via the standalone workflow or automatically via `orchestration-dispatch` when `requested_stage: design`.

**What it does:**
1. Discovers whether a discussion already exists using three-tier owned-artifact lookup:
   - **Tier 1:** Scaffold marker comment (`<!-- gpa:design-discussion:#N -->`) in issue comments
   - **Tier 2:** Discussion URL in issue body (user-placed)
   - **Tier 3:** Orphaned discussion recovery via GraphQL search (handles partial failure where discussion was created but backlink comment was not posted)
2. If no discussion exists: renders `templates/design-discussion.md` with issue metadata, creates a GitHub Discussion in the configured category (default: "Ideas"), and posts the discussion URL back to the issue with an owned-artifact marker
3. If a discussion already exists: skips creation and posts an informational comment (with the marker if not already present)

**Standalone usage:**
```
gh workflow run scaffold-design-discussion.yml -f issue_number=<N>
```

**Via orchestration:**
```
gh workflow run orchestration-dispatch.yml -f issue_number=<N> -f requested_stage=design
```
When triggered via orchestration, the scaffold runs **before** the design gate check. This means `requested_stage: design` on an issue with no discussion will create the discussion first, then the gate validates its quality (headings filled in, open questions resolved, review comment present). The first run typically scaffolds the discussion and then fails the gate — the operator fills in the discussion and re-triggers to pass.

**Discussion template:** `templates/design-discussion.md` contains all headings required by the design gate (Summary, Problem, Goals, Non-goals, Proposed Approach, Open Questions) plus exit criteria.

**Idempotency:** The scaffold uses an owned-artifact marker (`<!-- gpa:design-discussion:#N -->`) to identify its own output. Unrelated discussion URLs mentioned in issue comments do not suppress creation. Running the scaffold twice for the same issue will not create a duplicate. Partial failure between discussion creation and backlink comment is recoverable: the scaffold searches for orphaned discussions by source-issue marker in the discussion body.

**Permissions required:** `contents: read`, `issues: write`, `discussions: write`

### Implementation plan scaffold

**Trigger:** `workflow_dispatch` via the standalone workflow or automatically via `orchestration-dispatch` when `requested_stage: plan`.

**What it does:**
1. Discovers whether a plan comment already exists using two-tier owned-artifact lookup:
   - **Tier 1:** Owned-artifact marker (`<!-- gpa:owned-artifact:impl-plan:REPO#N -->`) embedded in the plan comment itself (rendered from the template)
   - **Tier 2:** Issue comment containing `## Implementation Plan` heading (user-placed)
   - Status comments use a distinct marker (`<!-- gpa:impl-plan-status:#N -->`) and are **not** treated as the plan artifact
2. If no plan comment exists: renders `templates/implementation-plan.md` with issue metadata and posts it as an issue comment with an owned-artifact marker
3. If a plan comment already exists: skips creation and posts an informational status comment

**Standalone usage:**
```
gh workflow run scaffold-impl-plan.yml -f issue_number=<N>
```

**Via orchestration:**
```
gh workflow run orchestration-dispatch.yml -f issue_number=<N> -f requested_stage=plan
```
When triggered via orchestration, the scaffold runs **before** the plan gate check. This means `requested_stage: plan` on an issue with no plan comment will create the comment first, then the gate validates its structure (headings present, checklists populated, review dispositions listed, slices numbered). The first run typically scaffolds the plan and then fails the gate — the operator fills in the plan and re-triggers to pass.

**Plan template:** `templates/implementation-plan.md` contains all headings required by the plan gate (Implementation Plan, Acceptance Criteria, Verification Plan, Review Expectations, Slices) plus exit criteria.

**Idempotency:** The scaffold identifies its own output via the owned-artifact marker (`<!-- gpa:owned-artifact:impl-plan:REPO#N -->`) embedded in the plan comment itself. Status comments posted alongside the plan use a distinct marker (`<!-- gpa:impl-plan-status:#N -->`) and are never mistaken for the plan artifact. Running the scaffold twice for the same issue will not create a duplicate. Unlike the design scaffold, no orphan recovery tier is needed because plan comments live directly on the issue and cannot be orphaned.

**Permissions required:** `contents: read`, `issues: write`

### Execution bootstrap scaffold

**Trigger:** `workflow_dispatch` via the standalone workflow or automatically via `orchestration-dispatch` when `requested_stage: execution`.

**What it does:**
1. Discovers whether an execution PR already exists using two-tier owned-artifact lookup:
   - **Tier 1:** Owned-artifact marker (`<!-- gpa:owned-artifact:execution-bootstrap:REPO#N -->`) embedded in the PR body (rendered from the template)
   - **Tier 2:** Open PR with branch matching `<issue-number>-*` (convention-based fallback)
   - Status comments use a distinct marker (`<!-- gpa:execution-status:#N -->`) and are **not** treated as the execution artifact
2. If no PR exists: derives a branch name from the issue title (`<issue-number>-<slug>`), creates the branch via the GitHub API, renders `templates/execution-bootstrap.md` with issue metadata, opens a draft PR, and posts a backlink comment on the source issue
3. If a PR already exists: skips creation and posts an informational status comment

**Standalone usage:**
```
gh workflow run scaffold-execution.yml -f issue_number=<N>
```

**Via orchestration:**
```
gh workflow run orchestration-dispatch.yml -f issue_number=<N> -f requested_stage=execution
```
When triggered via orchestration, the scaffold runs **before** the execution gate check. This means `requested_stage: execution` on an issue with no PR will create the branch and draft PR first, then the gate validates the PR (headings present, not draft, branch exists). The first run typically scaffolds the PR in draft state and then fails the gate on the draft check — the operator fills in the PR, marks it ready for review, and re-triggers to pass.

**PR template:** `templates/execution-bootstrap.md` contains all headings required by the execution gate (Summary, Test plan) plus Review Checklist for operator self-check.

**Branch naming:** `<issue-number>-<slug>` where the slug is derived from the issue title (lowercased, non-alphanumeric characters replaced with hyphens, truncated to 60 characters). This matches the pattern expected by the execution gate check in `check-gate`.

**Idempotency:** The scaffold identifies its own output via the owned-artifact marker (`<!-- gpa:owned-artifact:execution-bootstrap:REPO#N -->`) embedded in the PR body. Status comments posted alongside the PR use a distinct marker (`<!-- gpa:execution-status:#N -->`) and are never mistaken for the execution artifact. Running the scaffold twice for the same issue will not create duplicate branches or PRs.

**Permissions required:** `contents: write`, `issues: write`, `pull-requests: write`

## Operator actions

| Action | How |
|--------|-----|
| View run status | Check automation comment on the issue, or Actions run |
| Retry failed run | Re-trigger via `workflow_dispatch` with issue number and target stage |
| Scaffold a design discussion | `gh workflow run scaffold-design-discussion.yml -f issue_number=<N>` |
| Scaffold an implementation plan | `gh workflow run scaffold-impl-plan.yml -f issue_number=<N>` |
| Scaffold execution bootstrap | `gh workflow run scaffold-execution.yml -f issue_number=<N>` |
| Waive a gate | Post `GATE-WAIVER: <gate-name> — <reason>` on the issue/PR |
| Block automation | Add `do-not-automate` label to the issue |
