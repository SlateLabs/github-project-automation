#!/usr/bin/env bash
# Structural verification for orchestration-dispatch.yml after Slice 9 changes.
# Validates that:
# 1. repository_dispatch trigger is present with correct event type
# 2. workflow_dispatch trigger is still present (regression check)
# 3. No remaining inputs.* references outside the normalize step
# 4. No remaining github.actor references outside the normalize step
# 5. Normalize step outputs are used by downstream steps
set -euo pipefail

WORKFLOW=".github/workflows/orchestration-dispatch.yml"
cd "$(git rev-parse --show-toplevel)"

PASS=0
FAIL=0

check() {
  local label="$1" result="$2"
  if [ "$result" = "pass" ]; then
    PASS=$((PASS + 1))
    echo "  ✓ $label"
  else
    FAIL=$((FAIL + 1))
    echo "  ✗ $label"
  fi
}

echo "=== Workflow Structure Tests ==="

echo ""
echo "1. Workflow parses as YAML"

if python3 - <<'PY' >/dev/null 2>&1
import pathlib, yaml
yaml.safe_load(pathlib.Path(".github/workflows/orchestration-dispatch.yml").read_text())
PY
then
  check "workflow YAML parses successfully" "pass"
else
  check "workflow YAML parses successfully" "fail"
fi

echo ""
echo "2. Trigger configuration"

if grep -q 'repository_dispatch:' "$WORKFLOW"; then
  check "repository_dispatch trigger present" "pass"
else
  check "repository_dispatch trigger present" "fail"
fi

if grep -q 'types: \[orchestration-start\]' "$WORKFLOW"; then
  check "orchestration-start event type configured" "pass"
else
  check "orchestration-start event type configured" "fail"
fi

if grep -q 'workflow_dispatch:' "$WORKFLOW"; then
  check "workflow_dispatch trigger still present (regression)" "pass"
else
  check "workflow_dispatch trigger still present (regression)" "fail"
fi

echo ""
echo "3. Normalize step present"

if grep -q 'id: normalize' "$WORKFLOW"; then
  check "normalize step exists with id" "pass"
else
  check "normalize step exists with id" "fail"
fi

if grep -q 'steps.normalize.outputs.issue_number' "$WORKFLOW"; then
  check "downstream steps reference normalize.outputs.issue_number" "pass"
else
  check "downstream steps reference normalize.outputs.issue_number" "fail"
fi

if grep -q 'steps.normalize.outputs.requested_stage' "$WORKFLOW"; then
  check "downstream steps reference normalize.outputs.requested_stage" "pass"
else
  check "downstream steps reference normalize.outputs.requested_stage" "fail"
fi

if grep -q 'steps.normalize.outputs.actor' "$WORKFLOW"; then
  check "downstream steps reference normalize.outputs.actor" "pass"
else
  check "downstream steps reference normalize.outputs.actor" "fail"
fi

if grep -q 'steps.normalize.outputs.project_item_id' "$WORKFLOW"; then
  check "downstream steps reference normalize.outputs.project_item_id" "pass"
else
  check "downstream steps reference normalize.outputs.project_item_id" "fail"
fi

echo ""
echo "4. No stale inputs.* references outside normalize step and run-name"

# Count inputs.* references — should only be inside the normalize step
# (lines with WD_ prefix env vars) or the top-level workflow_dispatch run-name.
stale_input_refs=$(grep -n 'inputs\.' "$WORKFLOW" | grep -v 'WD_ISSUE_NUMBER.*inputs\.' | grep -v 'WD_REQUESTED_STAGE.*inputs\.' | grep -v 'github\.event\.inputs\.' | grep -v 'description:' | grep -v 'type:' | grep -v 'required:' | grep -v 'options:' || true)
if [ -z "$stale_input_refs" ]; then
  check "no stale inputs.* references in downstream steps" "pass"
else
  check "no stale inputs.* references in downstream steps" "fail"
  echo "    Found stale references:"
  echo "$stale_input_refs" | sed 's/^/      /'
fi

echo ""
echo "5. No stale github.actor references outside normalize step"

stale_actor_refs=$(grep -n 'github\.actor' "$WORKFLOW" | grep -v 'WD_ACTOR.*github\.actor' || true)
if [ -z "$stale_actor_refs" ]; then
  check "no stale github.actor references in downstream steps" "pass"
else
  check "no stale github.actor references in downstream steps" "fail"
  echo "    Found stale references:"
  echo "$stale_actor_refs" | sed 's/^/      /'
fi

echo ""
echo "6. Run key generation handles both trigger paths"

if grep -q 'TRIGGER.*steps.normalize.outputs.trigger' "$WORKFLOW"; then
  check "run-key step receives trigger from normalize" "pass"
else
  check "run-key step receives trigger from normalize" "fail"
fi

if grep -q 'client_payload.run_key' "$WORKFLOW"; then
  check "run-key step can access gateway-provided run_key" "pass"
else
  check "run-key step can access gateway-provided run_key" "fail"
fi

echo ""
echo "7. Payload validation in normalize step"

if grep -q 'repository_dispatch payload validation failed' "$WORKFLOW"; then
  check "validation error message present" "pass"
else
  check "validation error message present" "fail"
fi

if grep -q 'issue_number must be a positive integer' "$WORKFLOW"; then
  check "issue_number type validation present" "pass"
else
  check "issue_number type validation present" "fail"
fi

if grep -q 'unknown requested_stage' "$WORKFLOW"; then
  check "stage validation present" "pass"
else
  check "stage validation present" "fail"
fi

if grep -q 'run_key does not match canonical format' "$WORKFLOW"; then
  check "run_key format validation present" "pass"
else
  check "run_key format validation present" "fail"
fi

if grep -q 'project_item_id=' "$WORKFLOW"; then
  check "project_item_id normalization present" "pass"
else
  check "project_item_id normalization present" "fail"
fi

echo ""
echo "8. Automatic handoff configuration"

if grep -q 'Resolve next stage' "$WORKFLOW"; then
  check "next-stage resolution step present" "pass"
else
  check "next-stage resolution step present" "fail"
fi

if grep -q 'repos/${GITHUB_REPOSITORY}/dispatches' "$WORKFLOW"; then
  check "next-stage repository_dispatch present" "pass"
else
  check "next-stage repository_dispatch present" "fail"
fi

if grep -A3 'kickoff)' "$WORKFLOW" | grep -q 'next_stage="clarification"' && \
   grep -A3 'design)' "$WORKFLOW" | grep -q 'next_stage="plan"' && \
   grep -A3 'execution)' "$WORKFLOW" | grep -q 'next_stage="agent-review"' && \
   grep -A60 'agent-review)' "$WORKFLOW" | grep -q 'next_stage="merge"' && \
   grep -A3 'merge)' "$WORKFLOW" | grep -q 'next_stage="follow-up-capture"'; then
  check "stage handoff map includes key transitions" "pass"
else
  check "stage handoff map includes key transitions" "fail"
fi

if grep -Fq 'client_payload[project_item_id]' "$WORKFLOW"; then
  check "handoff preserves project_item_id in repository_dispatch" "pass"
else
  check "handoff preserves project_item_id in repository_dispatch" "fail"
fi

if grep -Fq 'client_payload[feedback_source]=agent' "$WORKFLOW"; then
  check "feedback source is preserved for agent loops" "pass"
else
  check "feedback source is preserved for agent loops" "fail"
fi

if grep -Fq '<!-- gpa:checkpoint ' "$WORKFLOW"; then
  check "structured checkpoint comments are emitted" "pass"
else
  check "structured checkpoint comments are emitted" "fail"
fi

if grep -Fq '<!-- gpa:checkpoint-v1 ' "$WORKFLOW"; then
  check "canonical checkpoint-v1 comments are emitted" "pass"
else
  check "canonical checkpoint-v1 comments are emitted" "fail"
fi

if grep -Fq 'gpa:artifact-payload:' "$WORKFLOW"; then
  check "agent-review artifact payload marker is parsed" "pass"
else
  check "agent-review artifact payload marker is parsed" "fail"
fi

if grep -q 'REVIEW_NEXT_STAGE: .*needs.gate.outputs.review_next_stage' "$WORKFLOW" && \
   grep -q 'Missing canonical review next-stage; falling back to disposition mapping' "$WORKFLOW"; then
  check "handoff resolves next stage from canonical review payload with fallback" "pass"
else
  check "handoff resolves next stage from canonical review payload with fallback" "fail"
fi

if [ ! -f .github/workflows/operator-review-intake.yml ]; then
  check "operator review intake workflow retired" "pass"
else
  check "operator review intake workflow retired" "fail"
fi

echo ""
echo "9. Project status synchronization"

if grep -q 'updateProjectV2ItemFieldValue' "$WORKFLOW"; then
  check "project status mutation present" "pass"
else
  check "project status mutation present" "fail"
fi

if grep -q 'target_status=' "$WORKFLOW" && grep -q 'Project Status target' scripts/render_orchestration_summary.sh; then
  check "project status target mapping and summary present" "pass"
else
  check "project status target mapping and summary present" "fail"
fi

echo ""
echo "10. Agent-backed authoring stages"

if grep -q 'Codex author design proposal' "$WORKFLOW" && grep -q 'openai/codex-action@v1' "$WORKFLOW"; then
  check "codex design author step present" "pass"
else
  check "codex design author step present" "fail"
fi

if grep -q 'Publish Claude design review comment (pre-gate)' "$WORKFLOW" && grep -q 'anthropics/claude-code-action@v1' "$WORKFLOW"; then
  check "claude design review step present" "pass"
else
  check "claude design review step present" "fail"
fi

if grep -q 'Codex author implementation plan' "$WORKFLOW"; then
  check "codex plan author step present" "pass"
else
  check "codex plan author step present" "fail"
fi

if grep -q 'Publish implementation plan review comment (pre-gate)' "$WORKFLOW"; then
  check "implementation plan review step present" "pass"
else
  check "implementation plan review step present" "fail"
fi

if grep -q 'Validate stage agent credentials' "$WORKFLOW" && grep -q 'OPENAI_API_KEY' "$WORKFLOW" && grep -q 'ANTHROPIC_API_KEY' "$WORKFLOW"; then
  check "stage agent credential validation present" "pass"
else
  check "stage agent credential validation present" "fail"
fi

echo ""
echo "11. Job summary includes trigger source"

if grep -q 'TRIGGER.*steps.normalize.outputs.trigger' "$WORKFLOW" && grep -q 'Trigger' scripts/render_orchestration_summary.sh; then
  check "job summary includes trigger field" "pass"
else
  check "job summary includes trigger field" "fail"
fi

echo ""
echo "=== Results ==="
echo "Passed: $PASS"
echo "Failed: $FAIL"
echo "Total:  $((PASS + FAIL))"

if [ $FAIL -gt 0 ]; then
  exit 1
fi

echo ""
echo "All structure checks passed."
