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
gateway/              — Cloud Run listener runtime for org-project webhook intake
tests/                — automated coverage for gateway and contract logic
.github/
  workflows/          — orchestration workflows (dispatch, standalone, retry)
  actions/            — composite actions (validate-eligibility, check-gate, query-run-history, scaffolds)
```

## Repo-template propagation checklist

Anything in this section should be treated as part of the bootstrap contract for `SlateLabs/repo-template` so new repos can participate in the workflow automation without bespoke setup.

### Required repository settings

- GitHub Actions enabled
- GitHub Discussions enabled
- A discussion category available for design scaffolding
  - current default expected by the scaffold: `Ideas`

### Required labels

- `do-not-automate`
  - blocks orchestration entry and all scaffold mutations
- `blocked`
  - used by the clarification gate
- `follow-up`
  - applied to all captured follow-up issues
- `blocking`
  - applied to follow-up issues when the marker says `blocking: yes`
- category labels for follow-up capture:
  - `technical-debt`
  - `accessibility`
  - `usability`
  - `documentation`
  - `automation`
  - `defect`

### Required workflow entrypoints

The repo should expose repo-local workflow entrypoints that call the shared workflows in this repo at a pinned SHA or release tag:

- `orchestration-dispatch.yml`
- `retry-stage.yml`
- `scaffold-design-discussion.yml`
- `scaffold-impl-plan.yml`
- `scaffold-execution.yml`
- `capture-follow-ups.yml`
- `scaffold-closeout.yml`

These should be pinned to an immutable ref from `SlateLabs/github-project-automation`, never a mutable branch.

### Required docs/bootstrap guidance

The template should include bootstrap guidance explaining:

- required labels
- required discussion support and category expectations
- branch naming convention used by execution scaffolding:
  - `<issue-number>-<slug>`
- PR/body artifact expectations used by the gates
- how to manually retry a failed stage
- that org project routing is driven by the canonical `Status` field

### Required artifact conventions

New repos need to preserve the artifact conventions expected by the shared actions:

- issue bodies should support `## Summary`
- execution PRs should support:
  - `## Summary`
  - `## Test plan`
  - `## Review Checklist`
- follow-up capture uses structured issue-comment markers:
  - `<!-- FOLLOW-UP: title | category | reason | impact | blocking -->`
- automation-owned artifacts use `gpa:owned-artifact:*` markers and must not be stripped from templates/comments/PR bodies

### Required token/permission model

Repo-local workflows rely on `GITHUB_TOKEN` permissions matching the shared workflow requirements:

- `contents: write`
- `issues: write`
- `pull-requests: write`
- `discussions: write` for design scaffolding
- `actions: write` for retry dispatch

### Validation we should add to `repo-template`

Issue [#19](https://github.com/SlateLabs/github-project-automation/issues/19) should implement validation or documented checks for:

- required labels exist
- Discussions are enabled
- the design discussion category exists
- shared workflow refs are pinned
- bootstrap docs are present
- PR/issue templates match the expected gate headings

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
| Webhook gateway | `projects_v2_item` org event → Cloud Run → `repository_dispatch` | Automated trigger when project item `Status` changes (issue #2) |

Both paths converge on the same orchestration workflow (`orchestration-dispatch.yml`). An input normalization step at the top of the workflow resolves inputs from either `workflow_dispatch` inputs or `repository_dispatch` client_payload, so all downstream steps (dedup, eligibility, gate checks, scaffolds, comments) execute identically regardless of trigger source.

### `repository_dispatch` consumer

The orchestration workflow accepts `repository_dispatch` events with `event_type: orchestration-start`. This is the automated entry point used by the webhook gateway (Slice 8).

**Payload contract:**

```json
{
  "event_type": "orchestration-start",
  "client_payload": {
    "issue_number": 42,
    "requested_stage": "kickoff",
    "run_key": "SlateLabs/github-project-automation/42/kickoff/1711234567890",
    "actor": "jflamb",
    "timestamp": "1711234567890",
    "project_item_id": "PVTI_lADOABUjKM4BTjIKzgABC"
  }
}
```

**Field validation (enforced at workflow start):**

| Field | Type | Validation |
|-------|------|------------|
| `issue_number` | integer | Positive integer (`>= 1`) |
| `requested_stage` | string | One of: `kickoff`, `clarification`, `design`, `plan`, `execution`, `follow-up-capture`, `review`, `merge`, `closeout` |
| `run_key` | string | Canonical format `<owner>/<repo>/<number>/<stage>/<timestamp>` — must be payload-consistent (see below) |
| `actor` | string | Non-empty |
| `timestamp` | string | Non-empty |
| `project_item_id` | string | Optional but recommended; enables closed-loop GitHub Project `Status` sync and auto-handoff preservation |

**Run key consistency (enforced at workflow start):** Beyond regex format, the `run_key` must be *payload-consistent* — its parsed components must agree with the other payload fields and the receiving repository:

- `<owner>/<repo>` must match `github.repository` (the repo receiving the dispatch)
- `<number>` must match `client_payload.issue_number`
- `<stage>` must match `client_payload.requested_stage`
- `<timestamp>` must match `client_payload.timestamp`

A run key that passes the format regex but fails any consistency check is rejected. This prevents correlation breaks, dedup bypasses, and audit trail mismatches that would occur if a well-formatted but internally inconsistent run key were accepted.

On validation failure, the workflow posts a diagnostic comment on the issue (if `issue_number` is parseable) listing all validation errors, then exits with a non-zero status.

**Run key preservation:** When triggered via `repository_dispatch`, the workflow uses the gateway-provided `run_key` directly instead of generating a new one. This preserves end-to-end correlation: gateway structured log → dispatch → orchestration issue comments all share the same run key.

**Closed-loop project sync:** When `project_item_id` is present, the workflow uses it to update the GitHub Project `Status` after a successful stage and preserves the same project item identity when it auto-dispatches the next stage. If `project_item_id` is absent, the stage still runs for manual/retry compatibility, but project-state mutation and automatic next-stage dispatch are skipped.

**Actions auth requirement for org project mutation:** GitHub Actions' built-in `GITHUB_TOKEN` can post issue comments and dispatch follow-on runs in this repo, but it is not sufficient for mutating the SlateLabs org project. Closed-loop handoff therefore requires the repo to expose the orchestration GitHub App credentials to Actions:

- organization or repository variable: `ORCHESTRATION_APP_ID`
- organization or repository secret: `ORCHESTRATION_APP_PRIVATE_KEY`

These should live at **organization Actions scope** if you want `repo-template`-based rollout across multiple repos. The GitHub App must also have **Organization permissions -> Projects: Read and write**. Without that permission and those Actions settings, the stage itself can still pass, but `handoff` will fail when it tries to update the project `Status`.

**Manual simulation:**

```bash
gh api repos/SlateLabs/github-project-automation/dispatches \
  -f event_type=orchestration-start \
  -f 'client_payload[issue_number]=42' \
  -f 'client_payload[requested_stage]=kickoff' \
  -f 'client_payload[run_key]=SlateLabs/github-project-automation/42/kickoff/1711234567890' \
  -f 'client_payload[actor]=jflamb' \
  -f 'client_payload[timestamp]=1711234567890' \
  -f 'client_payload[project_item_id]=PVTI_lADOABUjKM4BTjIKzgABC'
```

Eligibility validation is shared but not yet at full parity: the manual path validates issue state, actor trust, labels, and body content; the webhook gateway path additionally validates live project-field state (`Status` transition and `Repository` mapping).

## Webhook gateway contract

The gateway is the org-level listener for `projects_v2_item` events. It stays intentionally thin:

- Validate `X-GitHub-Delivery`, `X-GitHub-Event`, and `X-Hub-Signature-256`
- Accept only `projects_v2_item` deliveries that prove a `Status` transition of `Backlog -> Ready`
- Resolve the project item via GraphQL to read the linked issue, `Repository`, and `Status` field
- Enforce kickoff eligibility (`Issue` item type, linked source issue, configured participating repo, `Status == Ready`, no `do-not-automate` label)
- Enforce trusted-actor outcomes using `config/trust-policy.yml`
- Deduplicate by delivery id, active run prefix, and 60-second recent-completion window
- Dispatch `repository_dispatch` with event type `orchestration-start`, preserving the source `project_item_id`

### HTTP surface

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/healthz` | Liveness / readiness probe |
| `POST` | `/github/webhook` | GitHub org-project webhook intake |

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GITHUB_WEBHOOK_SECRET` | Yes | HMAC secret for `X-Hub-Signature-256` validation |
| `GITHUB_APP_ID` | Yes | GitHub App ID used to mint installation access tokens |
| `GITHUB_APP_INSTALLATION_ID` | Yes | GitHub App installation ID for the participating repos |
| `GITHUB_APP_PRIVATE_KEY` | Yes | PEM-encoded GitHub App private key |
| `GITHUB_DISPATCH_TOKEN` | No | Legacy fallback token for local bootstrap; prefer GitHub App auth |
| `GITHUB_API_URL` | No | Override GitHub API base URL; defaults to `https://api.github.com` |
| `GPA_REPO_CONFIG_PATH` | No | Path to `config/repos.yml` |
| `GPA_TRUST_POLICY_PATH` | No | Path to `config/trust-policy.yml` |
| `GPA_DEDUP_WINDOW_MS` | No | Dedup window; defaults to `60000` |
| `PORT` | No | HTTP port; defaults to `8080` |

### Cloud Run source deployment

The simplest production path is a Cloud Run source deploy with Secret Manager-backed env vars:

```bash
gcloud run deploy github-project-automation-gateway \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --service-account github-automation-runner@PROJECT_ID.iam.gserviceaccount.com \
  --set-secrets GITHUB_WEBHOOK_SECRET=github-webhook-secret:latest \
  --set-secrets GITHUB_APP_ID=github-app-id:latest \
  --set-secrets GITHUB_APP_INSTALLATION_ID=github-app-installation-id:latest \
  --set-secrets GITHUB_APP_PRIVATE_KEY=github-app-private-key:latest
```

This repo does not require a `Dockerfile` for the initial rollout. Cloud Run can build from source using `requirements.txt`, and the root-level `app.py` provides the default Python entrypoint expected by Google buildpacks.

### GitHub Actions auto-deploy

This repo includes [deploy-gateway.yml](/Users/jlamb/Projects/slatelabs/github-project-automation/.github/workflows/deploy-gateway.yml), which redeploys the Cloud Run gateway on pushes to `main` when gateway/runtime files change.

The workflow:

- runs the gateway/unit tests
- validates workflow structure and config
- authenticates to Google Cloud with GitHub OIDC via Workload Identity Federation
- deploys the existing Cloud Run service from source

#### Required GitHub repository variables

Set these in `Settings -> Secrets and variables -> Actions -> Variables`:

| Variable | Example value | Purpose |
|----------|---------------|---------|
| `GCP_PROJECT_ID` | `github-gateway` | Google Cloud project id |
| `GCP_REGION` | `us-central1` | Cloud Run region |
| `CLOUD_RUN_SERVICE` | `github-project-automation-gateway` | Cloud Run service name |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/395454765628/locations/global/workloadIdentityPools/github/providers/github-actions` | Full Workload Identity Provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `github-gateway-deployer@github-gateway.iam.gserviceaccount.com` | Service account impersonated by GitHub Actions |
| `GCP_RUNTIME_SERVICE_ACCOUNT` | `github-automation-runner@github-gateway.iam.gserviceaccount.com` | Service account attached to the running Cloud Run service |

No GitHub secret is required for GCP auth if OIDC is configured correctly. Runtime secrets stay in Google Secret Manager and are injected during deploy.

#### Required Google Cloud setup for GitHub OIDC

The deploy workflow needs a dedicated deployer identity. Recommended shape:

1. Create a deployer service account, for example:
   - `github-gateway-deployer@github-gateway.iam.gserviceaccount.com`
2. Grant that deployer service account:
   - `roles/run.admin`
   - `roles/iam.serviceAccountUser` on `github-automation-runner@github-gateway.iam.gserviceaccount.com`
3. Create a Workload Identity Pool and GitHub OIDC provider
4. Grant the GitHub repo permission to impersonate the deployer service account via `roles/iam.workloadIdentityUser`

Recommended `gcloud` bootstrap, replacing values as needed:

```bash
PROJECT_ID=github-gateway
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
POOL_ID=github
PROVIDER_ID=github-actions
DEPLOYER_SA=github-gateway-deployer@${PROJECT_ID}.iam.gserviceaccount.com
RUNTIME_SA=github-automation-runner@${PROJECT_ID}.iam.gserviceaccount.com

gcloud iam service-accounts create github-gateway-deployer \
  --project "$PROJECT_ID" \
  --display-name "GitHub Actions Cloud Run deployer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOYER_SA}" \
  --role "roles/run.admin"

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOYER_SA}" \
  --role "roles/iam.serviceAccountUser"

gcloud iam workload-identity-pools create "$POOL_ID" \
  --project "$PROJECT_ID" \
  --location global \
  --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project "$PROJECT_ID" \
  --location global \
  --workload-identity-pool "$POOL_ID" \
  --display-name "GitHub OIDC" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" \
  --attribute-condition "assertion.repository=='SlateLabs/github-project-automation'"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --project "$PROJECT_ID" \
  --role "roles/iam.workloadIdentityUser" \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/SlateLabs/github-project-automation"
```

Use this resulting provider name as `GCP_WORKLOAD_IDENTITY_PROVIDER`:

```bash
projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}
```

This follows GitHub’s OIDC guidance and Google’s `google-github-actions/auth` / `deploy-cloudrun` action model.

#### Proven IAM matrix for `gcloud run deploy --source`

The first live GitHub Actions deploy for this repo exposed the full IAM chain required for Cloud Run source deploys. The deployer service account is not only talking to Cloud Run; it also has to drive Cloud Build, Artifact Registry, and the Cloud Storage staging bucket, and it must be allowed to act as both the runtime service account and the build service account.

The following grants are the **working** set for `github-gateway-deployer@github-gateway.iam.gserviceaccount.com` in project `github-gateway`.

Project-level on `github-gateway` for `github-gateway-deployer@github-gateway.iam.gserviceaccount.com`:

- `roles/run.admin`
- `roles/cloudbuild.builds.editor`
- `roles/artifactregistry.reader`
- `roles/storage.viewer`
- `roles/serviceusage.serviceUsageConsumer`

Bucket-level on `gs://run-sources-github-gateway-us-central1` for `github-gateway-deployer@github-gateway.iam.gserviceaccount.com`:

- `roles/storage.objectViewer`
- `roles/storage.objectCreator`
- `roles/storage.legacyBucketReader`

Service-account-level:

- On `github-automation-runner@github-gateway.iam.gserviceaccount.com`:
  - grant `roles/iam.serviceAccountUser` to `github-gateway-deployer@github-gateway.iam.gserviceaccount.com`
- On `395454765628-compute@developer.gserviceaccount.com`:
  - grant `roles/iam.serviceAccountUser` to `github-gateway-deployer@github-gateway.iam.gserviceaccount.com`

Build service account:

- On project `github-gateway`, grant `roles/run.builder` to:
  - `395454765628-compute@developer.gserviceaccount.com`

Workload Identity:

- On `github-gateway-deployer@github-gateway.iam.gserviceaccount.com`, grant `roles/iam.workloadIdentityUser` to:
  - `principalSet://iam.googleapis.com/projects/395454765628/locations/global/workloadIdentityPools/github/attribute.repository/SlateLabs/github-project-automation`

These grants were validated by a successful run of:

- [Deploy Gateway workflow](https://github.com/SlateLabs/github-project-automation/actions/workflows/deploy-gateway.yml)

If the deploy workflow is cloned into another repo/project, do not assume the narrower initial role set is sufficient. Reuse this full matrix unless you are intentionally redesigning the Cloud Run build/deploy path.

### Kickoff payload contract

The listener is deliberately strict because `projects_v2_item` webhooks are still preview. The accepted kickoff shape is:

- `X-GitHub-Event: projects_v2_item`
- `projects_v2_item.node_id` or `projects_v2_item.id`
- `changes.field_value.field_name == "Status"`
- `changes.field_value.from == "Backlog"`
- `changes.field_value.to == "Ready"`

If the listener cannot prove that the event is a kickoff transition on the canonical `Status` field, it fails closed with a `202 skipped` response rather than guessing from partial payload state. `Status` is now the single source of truth for the automation lifecycle in the SlateLabs org project.

### Trusted-actor outcomes

| Outcome | Behavior |
|---------|----------|
| `trusted` | Dispatch `repository_dispatch` to the participating repo |
| `record-only` | Add `pending-review` label to the source issue; no dispatch; does not record a completed run (preserves the ability for a trusted actor to immediately re-trigger the same prefix) |
| `denied` | Log and drop the event with no repo mutation |

### Response codes

| Code | Meaning |
|------|---------|
| `200` | Kickoff dispatch accepted and sent |
| `202` | Event skipped, deduplicated, dropped, or pending-review |
| `400` | Missing headers or invalid JSON payload |
| `401` | Invalid webhook signature |
| `422` | Project item is ineligible for kickoff automation |
| `502` | GitHub API call failed while resolving, labeling, or dispatching (dispatch retries exhausted) |

### Dispatch retry/backoff

If `repository_dispatch` fails (GitHub API error), the gateway retries up to 3 times with exponential backoff: **1s, 4s, 16s**. Each retry attempt is logged with `outcome: dispatch-retry`, the attempt number, and the backoff duration. After all 3 attempts fail, the gateway logs `outcome: dispatch-failed`, clears the active-run slot, and returns `502`.

### Structured logs

Every gateway outcome emits JSON including:

- `delivery_id`
- `actor`
- `repo`
- `issue`
- `requested_stage`
- `run_key`
- `outcome`
- `reason` when applicable

### Local verification

Run the gateway tests, dispatch normalization tests, and config validation with:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
bash tests/test_dispatch_normalization.sh
bash tests/test_workflow_structure.sh
python3 scripts/validate-config.py
```

## Trust policy

Defined in `config/trust-policy.yml`. See [discussion #3 §8](https://github.com/SlateLabs/github-project-automation/discussions/3) for the full decision model.

**Current limitation:** The gateway currently enforces `trusted_users`, `trusted_apps`, `record_only_roles`, and `deny_roles`, but it still does **not** resolve `trusted_teams`. Team membership resolution requires the org API and is deferred to [issue #5](https://github.com/SlateLabs/github-project-automation/issues/5). Actors who are only trusted through team membership are denied for now. The trust check fails closed — org admin or repo write access alone is not sufficient.

## Stage model

The default workflow stages are: Backlog → Clarification → Design → Plan → Execution → Review → Merge → Closeout. Each transition has machine-testable gate conditions defined in discussion #3 §4.

## Stage actions

Stage actions run automatically after eligibility validation passes. Some actions (like the design scaffold) run **before** their gate check to create the artifacts the gate will then evaluate; others run after gate checks pass. Each action's trigger timing is documented below.

### Automatic stage handoff

`orchestration-dispatch.yml` is the canonical stage runner. When a stage passes its gate, the workflow now auto-dispatches the next stage back into the same orchestrator using `repository_dispatch`. This turns the existing stage actions into a connected state machine instead of a set of isolated entry points.

The current handoff sequence is:

| Completed stage | Auto-queued next stage |
|-----------------|------------------------|
| `kickoff` | `clarification` |
| `clarification` | `design` |
| `design` | `plan` |
| `plan` | `execution` |
| `execution` | `review` |
| `review` | `merge` |
| `merge` | `follow-up-capture` |
| `follow-up-capture` | `closeout` |
| `closeout` | _(terminal)_ |

This is intentionally "fail forward" for scaffold-driven stages:

- `design`, `plan`, and `execution` typically auto-queue, scaffold their required artifact, and then fail their gate until a human or agent fills in the discussion/comment/PR.
- `review`, `merge`, and `closeout` remain machine-checked stages; they only auto-advance when the required repo artifacts already satisfy the gate.
- Each auto-handoff posts a `gpa:run-status:<stage>:started:<run_key>` marker comment on the issue so the run history remains queryable across stages.
- When `project_item_id` is present, the orchestrator also updates the GitHub Project `Status` during handoff:
  - `kickoff`, `clarification`, `design`, `plan` -> `In Progress`
  - `execution`, `review` -> `In Review`
  - `merge`, `follow-up-capture` -> `In Progress`
  - `closeout` -> `Done`
- Manual/retry runs without `project_item_id` still execute, but they do not mutate project state and do not auto-queue the next stage.

The standalone `workflow_dispatch` wrappers remain as operator escape hatches, but they are no longer the intended happy-path glue between successful stages.

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

**Check-before-act guard:** Before creating a discussion (the mutation), the scaffold re-verifies that the source issue is still open and does not have the `do-not-automate` label. If the issue state changed after eligibility validation, the scaffold aborts without creating any artifacts.

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

**Check-before-act guard:** Before posting the plan comment (the mutation), the scaffold re-verifies that the source issue is still open and does not have the `do-not-automate` label. If the issue state changed after eligibility validation, the scaffold aborts without creating any artifacts.

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

**Recovery from abandoned PRs:** If a prior execution PR was closed without merge, the scaffold reopens it on the next run rather than creating a duplicate. The reopened PR retains its branch, body, and review history so the operator can continue from where they left off. To force a clean start, delete the branch and the closed PR before rerunning the scaffold.

**Check-before-act guard:** Before any state-mutating operation — creating a branch, creating a PR, or reopening a closed-unmerged PR for recovery — the scaffold re-verifies that the source issue is still open and does not have the `do-not-automate` label. If the issue state changed after eligibility validation, the scaffold aborts without mutating any artifacts. This guard covers both the fresh-creation path and the closed-unmerged recovery path.

**Permissions required:** `contents: write`, `issues: write`, `pull-requests: write`

### Follow-up capture

**Trigger:** `workflow_dispatch` via the standalone workflow or automatically via `orchestration-dispatch` when `requested_stage: follow-up-capture`.

**What it does:**
1. Scans all comments on the source issue for structured `<!-- FOLLOW-UP: ... -->` markers
2. For each marker, checks whether a backlog issue with the corresponding owned-artifact marker already exists (idempotency)
3. If no existing issue: renders `templates/follow-up-item.md` with marker metadata and creates a new issue with labels
4. If an existing issue already covers this marker: skips creation
5. Posts a summary status comment on the source issue listing all created and skipped follow-up issues

**Standalone usage:**
```
gh workflow run capture-follow-ups.yml -f issue_number=<N>
```

**Via orchestration:**
```
gh workflow run orchestration-dispatch.yml -f issue_number=<N> -f requested_stage=follow-up-capture
```
Both the standalone workflow and the orchestration path run the gate check **before** the capture action. The gate validates that valid FOLLOW-UP markers exist (all 5 fields present), that execution is complete (a merged PR references the issue), and that no open PRs remain (current work is finished). Once the gate passes, the capture action creates backlog issues from the markers.

**Marker format:**
```
<!-- FOLLOW-UP: <title> | <category> | <reason> | <impact> | <blocking: yes|no> -->
```

| Field | Description | Allowed values |
|-------|-------------|----------------|
| `title` | Short title for the new backlog issue | Free text |
| `category` | Follow-up category per discussion #3 §10 | `technical-debt`, `accessibility`, `usability`, `documentation`, `automation`, `defect` |
| `reason` | Why this was deferred | Free text |
| `impact` | Impact if this follow-up is ignored | Free text |
| `blocking` | Whether this blocks further slices | `yes` or `no` |

Example:
```
<!-- FOLLOW-UP: Pre-mutation guards for design/plan scaffolds | technical-debt | Lower blast radius (comments vs PRs), not needed for Slice 4 | Scaffold actions could mutate artifacts on closed issues | no -->
```

Markers use HTML comments so they are invisible in rendered markdown but machine-parseable.

**Created issue format:** Each created issue gets:
- Title: `[follow-up] <marker title>`
- Body: rendered from `templates/follow-up-item.md` with source traceability (source issue, category, reason, blocking status, run key)
- Labels: `follow-up` + category label (e.g., `technical-debt`) + `blocking` if applicable
- Owned-artifact marker: `<!-- gpa:owned-artifact:follow-up:REPO#SOURCE:SEQ -->` for dedup

**Label requirements:** The following labels should exist in the repo for full functionality:
- `follow-up` — applied to all captured follow-up issues
- `technical-debt`, `accessibility`, `usability`, `documentation`, `automation`, `defect` — category labels
- `blocking` — applied when the marker specifies `blocking: yes`

If a label does not exist, the action attempts to create the issue without it and logs a warning. Missing labels do not cause the action to fail.

**Idempotency:** Each marker is assigned a stable sequence number (1-indexed across all comments in comment-date order). The created issue embeds an owned-artifact marker with this sequence (`gpa:owned-artifact:follow-up:REPO#SOURCE:SEQ`). Re-running the action on the same issue checks for existing issues with matching markers and skips them. Status comments use a distinct marker (`<!-- gpa:follow-up-status:#N -->`) and are not treated as follow-up artifacts.

**Check-before-act guard:** Before creating each follow-up issue, the action re-verifies that the source issue is still open and does not have the `do-not-automate` label. If the issue state changed during processing, the action aborts without creating further issues.

**Gate check (follow-up-capture):**
- At least one valid `<!-- FOLLOW-UP: title | category | reason | impact | blocking -->` marker must exist in the issue comments (all 5 fields required)
- A merged PR referencing the source issue (or matching the branch convention `<issue-number>-*`) must exist (execution is complete)
- No open PRs referencing the source issue may remain (ensures current execution work is finished, not just historical PRs)
- All conditions support `GATE-WAIVER` override by trusted actors

**Permissions required:** `contents: read`, `issues: write`

### Closeout scaffold

**Trigger:** `workflow_dispatch` via the standalone workflow or automatically via `orchestration-dispatch` when `requested_stage: closeout`.

**What it does:**
1. Discovers whether a closeout retrospective comment already exists using owned-artifact lookup:
   - Owned-artifact marker (`<!-- gpa:owned-artifact:closeout:REPO#N -->`) embedded in the closeout comment itself (rendered from the template)
   - Status comments use a distinct marker (`<!-- gpa:closeout-status:#N -->`) and are **not** treated as the closeout artifact
2. If no closeout comment exists: gathers merged PR list and follow-up issue counts, renders `templates/closeout.md` with issue metadata, and posts it as an issue comment with an owned-artifact marker
3. If a closeout comment already exists: skips creation and posts an informational status comment

**Standalone usage:**
```
gh workflow run scaffold-closeout.yml -f issue_number=<N>
```

**Via orchestration:**
```
gh workflow run orchestration-dispatch.yml -f issue_number=<N> -f requested_stage=closeout
```
Both entry points enforce the same closeout sequence: **pre-scaffold gate → scaffold → full gate**. The pre-scaffold gate (`check_mode: pre-scaffold`) verifies non-scaffold prerequisites (merged PR, branch deleted, follow-up evidence) before any scaffold comment is posted. If prerequisites are not met, the workflow fails without mutating any artifacts. Once the pre-scaffold gate passes, the closeout retrospective comment is created, and then the full gate validates scaffold content (headings, sections, process improvement dispositions).

**Closeout template:** `templates/closeout.md` contains structured sections for the retrospective (delivery summary, what went well, what could improve, follow-up status, exit checklist) plus auto-populated merged PR list and follow-up counts.

**Idempotency:** The scaffold identifies its own output via the owned-artifact marker (`<!-- gpa:owned-artifact:closeout:REPO#N -->`) embedded in the closeout comment itself. Status comments posted alongside the closeout use a distinct marker (`<!-- gpa:closeout-status:#N -->`) and are never mistaken for the closeout artifact. Running the scaffold twice for the same issue will not create a duplicate.

**Check-before-act guard:** Before posting the closeout comment, the scaffold re-verifies that the source issue is still open and does not have the `do-not-automate` label. If the issue state changed after eligibility validation, the scaffold aborts without mutating any artifacts.

**Permissions required:** `contents: read`, `issues: write`, `pull-requests: read`

### Gate checks — review, merge, closeout

These three gates complete the 8-stage model so every transition has a real machine-testable check. PR selection across all three gates is **deterministic**: branch-convention matches (`<issue-number>-*` or `<issue-number>/*`) are preferred and sorted by recency, so umbrella issues with multiple slice PRs always evaluate the most recent one.

**Review gate (Gate 6→7):**
- A PR referencing the issue must exist (open or merged)
- The PR must have at least one `APPROVED` review
- No unresolved `CHANGES_REQUESTED` reviews may remain (a `CHANGES_REQUESTED` review is resolved if the same user submitted an `APPROVED` or `DISMISSED` review *after* the `CHANGES_REQUESTED` timestamp — chronological ordering is enforced)
- Waiver keys: `review-pr`, `review-approval`, `review-changes-requested`
- **Not yet implemented** (per gate contract rule 2 — skipped checks are logged): CI status checks on PR head commit, unresolved review thread check, `## Review Checklist` completion/waiver handling, trusted/non-author approval semantics

**Merge gate (Gate 7→8):**
- A merged PR referencing the issue must exist
- The merged PR must have had at least one `APPROVED` review
- Waiver keys: `merge-pr`, `merge-approval`
- **Not yet implemented** (per gate contract rule 2 — skipped checks are logged): mergeability/conflict check, `do-not-merge` label check, latest commit status check

**Closeout gate (Gate 8→done):**
- A merged PR referencing the issue must exist
- The source branch from the merged PR must be deleted
- Follow-up capture evidence must exist: either valid `<!-- FOLLOW-UP: title | category | reason | impact | blocking -->` markers (all 5 fields required, category from the documented taxonomy) in issue comments, or a follow-up status comment (`gpa:follow-up-status`) indicating the capture stage was run
- A closeout scaffold comment with the owned-artifact marker must exist
- The closeout comment must contain `## Closeout` heading
- The closeout comment must contain `## Deferred Work` section (may be "None identified.")
- The closeout comment must contain `## Process Improvement` section with at least one real authored item dispositioned as `**adopt**`, `**backlog**`, or `**reject**` (bold markdown format; HTML comments and template placeholder text are excluded from the check)
- Waiver keys: `closeout-merged-pr`, `closeout-branch-deleted`, `closeout-follow-ups`, `closeout-scaffold`, `closeout-heading`, `closeout-deferred-work`, `closeout-process-improvement`, `closeout-process-improvement-dispositions`

All three gates support `GATE-WAIVER` override by trusted actors (per `config/trust-policy.yml`).

**Standalone closeout workflow:** The `scaffold-closeout.yml` workflow enforces closeout prerequisites *before* scaffolding and runs the full gate *after*. The sequence is `validate-eligibility → check-gate(closeout, pre-scaffold) → scaffold-closeout → check-gate(closeout, full) → status comment`. If the pre-scaffold gate fails (merged PR, branch deleted, follow-ups), the scaffold is not posted. If the post-scaffold gate fails (content checks), the workflow posts a failure comment listing unmet conditions and exits non-zero.

## Operator actions

| Action | How |
|--------|-----|
| View run status | Check automation comment on the issue, or Actions run |
| Query run history | Use the `query-run-history` action (see [Run history](#query-run-history) below) |
| Retry failed run | `gh workflow run retry-stage.yml -f issue_number=<N> -f target_stage=<stage>` |
| Scaffold a design discussion | `gh workflow run scaffold-design-discussion.yml -f issue_number=<N>` |
| Scaffold an implementation plan | `gh workflow run scaffold-impl-plan.yml -f issue_number=<N>` |
| Scaffold execution bootstrap | `gh workflow run scaffold-execution.yml -f issue_number=<N>` |
| Capture follow-ups | `gh workflow run capture-follow-ups.yml -f issue_number=<N>` |
| Scaffold closeout retrospective | `gh workflow run scaffold-closeout.yml -f issue_number=<N>` |
| Waive a gate | Post `GATE-WAIVER: <gate-name> — <reason>` on the issue/PR |
| Block automation | Add `do-not-automate` label to the issue |

### Query run history

The `query-run-history` composite action scans issue comments for machine-readable run-status markers (`<!-- gpa:run-status:STAGE:OUTCOME:RUN_KEY -->`) and outputs structured JSON. It is read-only and makes no mutations. The standalone workflows, orchestration workflow, and retry wrapper use this history to render a best-effort `Previous run` link in their job summaries.

**Inputs:** `issue_number`, `github_token`

**Outputs:**
- `run_history` — JSON array of `{stage, outcome, run_key, timestamp, actor, comment_url}` records, sorted by timestamp descending
- `run_count` — total number of run-status markers found
- `latest_run_key` — run key from the most recent marker

**Marker format:**
```
<!-- gpa:run-status:STAGE:OUTCOME:RUN_KEY -->
```
Where `OUTCOME` is one of: `started`, `completed`, `skipped`, `failed`.

All automation comments (scaffold actions, orchestration dispatch, retry-stage) include these markers. The markers are HTML comments and invisible in rendered markdown.

### Retry stage workflow

The `retry-stage.yml` workflow provides a single entry point for retrying any failed stage. It validates eligibility, maps the target stage to the correct standalone workflow, and dispatches it with the same run key so the retry wrapper comment, child workflow comments, and job summaries stay correlated.

**Usage:**
```bash
gh workflow run retry-stage.yml -f issue_number=<N> -f target_stage=<stage>
```

**Valid stages:** `design`, `plan`, `execution`, `follow-up-capture`, `closeout`

**Stage-to-workflow mapping:**

| Stage | Dispatched workflow |
|-------|-------------------|
| `design` | `scaffold-design-discussion.yml` |
| `plan` | `scaffold-impl-plan.yml` |
| `execution` | `scaffold-execution.yml` |
| `follow-up-capture` | `capture-follow-ups.yml` |
| `closeout` | `scaffold-closeout.yml` |

The retry workflow validates eligibility before dispatching (issue must be open, no `do-not-automate` label, actor must be trusted). The dispatched workflow runs independently and posts its own status comment, but it reuses the retry wrapper's run key for cross-surface correlation.

## Operator Runbook

### Checking automation status for an issue

1. **Quick check:** Look at the issue's comment thread for automation status comments. Each run posts a structured comment with a run key, result (checkmark/X/warning), and outcome details.

2. **Structured query:** Use the `query-run-history` action to get a JSON array of all runs:
   ```bash
   # In a workflow step:
   - uses: ./.github/actions/query-run-history
     with:
       issue_number: 42
       github_token: ${{ secrets.GITHUB_TOKEN }}
   ```

3. **Actions tab:** Go to the Actions tab and filter by workflow name. Each workflow run's job summary includes a clickable link back to the source issue, a best-effort `Previous run` link when discoverable from comments, and next-step guidance.

4. **Run key format:** `REPO/ISSUE_NUMBER/STAGE_SLUG/TIMESTAMP_MS` — e.g., `SlateLabs/github-project-automation/42/design-scaffold/1711234567890`. The timestamp is milliseconds since epoch.

### Retrying a failed stage

**Option 1 — Retry workflow (recommended):**
```bash
gh workflow run retry-stage.yml \
  -f issue_number=42 \
  -f target_stage=design
```
This validates eligibility and dispatches the correct stage workflow.

**Option 2 — Direct dispatch:**
```bash
gh workflow run scaffold-design-discussion.yml -f issue_number=42
```
Skip the retry wrapper and invoke the stage workflow directly. Same eligibility checks apply.

**Option 3 — Orchestration dispatch:**
```bash
gh workflow run orchestration-dispatch.yml \
  -f issue_number=42 \
  -f requested_stage=design
```
Routes through the full orchestration engine (dedup check, gate check, state verification).

### Overriding a gate (GATE-WAIVER)

When a gate condition cannot be met (e.g., a CI check is flaky, a review is not yet possible), a trusted actor can post a waiver comment on the issue:

```
GATE-WAIVER: <gate-name> — <reason>
```

**Requirements:**
- The commenter must be listed in `config/trust-policy.yml` under `trusted_users`
- The gate name must match the specific condition key (case-insensitive)
- The `— <reason>` part is required for auditability

**Common gate names:**

| Gate | Waiver key |
|------|-----------|
| Review approval | `review-approval` |
| Changes requested | `review-changes-requested` |
| Review PR exists | `review-pr` |
| Merged PR | `merge-pr` |
| Merge approval | `merge-approval` |
| Closeout merged PR | `closeout-merged-pr` |
| Closeout branch deleted | `closeout-branch-deleted` |
| Closeout follow-ups | `closeout-follow-ups` |
| Closeout scaffold | `closeout-scaffold` |
| Closeout heading | `closeout-heading` |
| Closeout deferred work | `closeout-deferred-work` |
| Closeout process improvement | `closeout-process-improvement` |
| Closeout PI dispositions | `closeout-process-improvement-dispositions` |
| Dedup override | `dedup` |

**Example:**
```
GATE-WAIVER: review-approval — PR was pair-programmed and self-reviewed; external review deferred to next slice
```

### Blocking automation (`do-not-automate` label)

Add the `do-not-automate` label to any issue to prevent all automation actions:
- Eligibility validation rejects the issue immediately
- All scaffold actions check for the label before mutations (check-before-act guard)
- The orchestration dispatch verifies the label hasn't been added mid-run (state check)
- The label can be removed to re-enable automation

### Diagnosing a stalled run

1. **Check the Actions tab:** Find the most recent workflow run for the issue. The job summary shows the outcome and any error details.

2. **Check issue comments:** Look for the most recent automation comment. The run key links to the specific Actions run.

3. **Common stall patterns:**

   | Symptom | Likely cause | Resolution |
   |---------|-------------|------------|
   | No automation comments | Eligibility failed (closed issue, missing label, untrusted actor) | Check issue state and `config/trust-policy.yml` |
   | "Gate conditions not met" | Gate prerequisites missing | Read the unmet conditions list; either fulfill them or post a GATE-WAIVER |
   | "Skipped (duplicate)" | Dedup window active | Wait 60s and re-trigger, or post `GATE-WAIVER: dedup — <reason>` |
   | "Superseded (state mismatch)" | Issue was closed or labeled during the run | Re-open the issue or remove the label, then re-trigger |
   | "Ineligible" with no clear reason | Actor not in trusted_users | Add the actor to `config/trust-policy.yml` |

4. **Run-status markers:** Search for `<!-- gpa:run-status:` in issue comments to see the machine-readable history of all runs, including their outcomes.

### Run key format reference

```
<repo-owner>/<repo-name>/<issue-number>/<stage-slug>/<timestamp-ms>
```

- **repo-owner/repo-name**: e.g., `SlateLabs/github-project-automation`
- **issue-number**: the source issue
- **stage-slug**: matches the workflow purpose (e.g., `design-scaffold`, `plan-scaffold`, `execution-scaffold`, `follow-up-capture`, `closeout`, `retry-design`)
- **timestamp-ms**: milliseconds since epoch when the run started

Search the Actions tab with the run key to find the exact workflow run.
