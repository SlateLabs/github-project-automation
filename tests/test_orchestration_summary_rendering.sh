#!/usr/bin/env bash
set -euo pipefail

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

assert_contains() {
  local label="$1" pattern="$2" text="$3"
  if echo "$text" | grep -qE -- "$pattern"; then
    check "$label" "pass"
  else
    check "$label" "fail"
  fi
}

assert_not_contains() {
  local label="$1" pattern="$2" text="$3"
  if echo "$text" | grep -qE -- "$pattern"; then
    check "$label" "fail"
  else
    check "$label" "pass"
  fi
}

render_summary() {
  env -i \
    PATH="$PATH" \
    RUN_KEY="SlateLabs/github-project-automation/36/${REQUESTED_STAGE}/1711234567890" \
    ISSUE_NUMBER="36" \
    REPO="SlateLabs/github-project-automation" \
    ACTOR="operator" \
    TRIGGER="${TRIGGER:-repository_dispatch}" \
    REQUESTED_STAGE="$REQUESTED_STAGE" \
    DUPLICATE="${DUPLICATE:-false}" \
    ELIGIBLE="${ELIGIBLE:-true}" \
    GATE_PASSED="${GATE_PASSED:-true}" \
    NEXT_STAGE="${NEXT_STAGE:-}" \
    TARGET_STATUS="${TARGET_STATUS:-In Progress}" \
    STATUS_UPDATED="${STATUS_UPDATED:-true}" \
    HANDOFF_DISPATCHED="${HANDOFF_DISPATCHED:-false}" \
    NEXT_RUN_KEY="${NEXT_RUN_KEY:-}" \
    PR_NUMBER="${PR_NUMBER:-}" \
    PR_URL="${PR_URL:-}" \
    PR_BRANCH="${PR_BRANCH:-}" \
    RUN_ID="999999" \
    RUN_URL="https://github.com/SlateLabs/github-project-automation/actions/runs/999999" \
    ISSUE_URL="https://github.com/SlateLabs/github-project-automation/issues/36" \
    PREVIOUS_RUN_KEY="${PREVIOUS_RUN_KEY:-SlateLabs/github-project-automation/36/plan/1711234000000}" \
    PREVIOUS_RUN_URL="${PREVIOUS_RUN_URL:-https://github.com/SlateLabs/github-project-automation/issues/36#issuecomment-1}" \
    PREVIOUS_RUN_VALUE="${PREVIOUS_RUN_VALUE:-[SlateLabs/github-project-automation/36/plan/1711234000000](https://github.com/SlateLabs/github-project-automation/issues/36#issuecomment-1)}" \
    STATUS_CLASS="${STATUS_CLASS:-}" \
    FAILURE_OR_BLOCK_REASON="${FAILURE_OR_BLOCK_REASON:-}" \
    OPERATOR_INTERVENTION_REQUIRED="${OPERATOR_INTERVENTION_REQUIRED:-}" \
    OPERATOR_NEXT_ACTION="${OPERATOR_NEXT_ACTION:-}" \
    NEXT_STAGE_OR_WAIT_STATE="${NEXT_STAGE_OR_WAIT_STATE:-}" \
    ADVANCED_DESCRIPTION="${ADVANCED_DESCRIPTION:-}" \
    TRIGGER_DESCRIPTION="${TRIGGER_DESCRIPTION:-}" \
    TRIGGER_URL="${TRIGGER_URL:-}" \
    scripts/render_orchestration_summary.sh
}

reset_fixture_env() {
  unset TRIGGER DUPLICATE ELIGIBLE GATE_PASSED NEXT_STAGE TARGET_STATUS STATUS_UPDATED
  unset HANDOFF_DISPATCHED NEXT_RUN_KEY PR_NUMBER PR_URL PR_BRANCH PREVIOUS_RUN_KEY
  unset PREVIOUS_RUN_URL PREVIOUS_RUN_VALUE STATUS_CLASS FAILURE_OR_BLOCK_REASON
  unset OPERATOR_INTERVENTION_REQUIRED OPERATOR_NEXT_ACTION NEXT_STAGE_OR_WAIT_STATE
  unset ADVANCED_DESCRIPTION TRIGGER_DESCRIPTION TRIGGER_URL
}

echo "=== Orchestration Summary Rendering Tests ==="

echo ""
echo "1. Success narrative precedes diagnostics"
REQUESTED_STAGE="execution"
reset_fixture_env
NEXT_STAGE="agent-review"
HANDOFF_DISPATCHED="true"
out_success="$(render_summary)"
outcome_line=$(echo "$out_success" | grep -n '^Outcome:' | cut -d: -f1 | head -1)
details_line=$(echo "$out_success" | grep -n '^<details><summary>Dispatch metadata</summary>$' | cut -d: -f1 | head -1)
if [ -n "$outcome_line" ] && [ -n "$details_line" ] && [ "$outcome_line" -lt "$details_line" ]; then
  check "narrative appears before details block" "pass"
else
  check "narrative appears before details block" "fail"
fi
assert_contains "success includes advancement" 'Advanced: .*queued `agent-review`' "$out_success"
assert_contains "success includes flow position" 'Flow position: Stage `execution` completed successfully\.' "$out_success"
assert_contains "success includes next stage" 'Next: Next expected stage: `agent-review`\.' "$out_success"

echo ""
echo "2. Failure with intervention required"
REQUESTED_STAGE="plan"
reset_fixture_env
NEXT_STAGE=""
ELIGIBLE="true"
GATE_PASSED="false"
out_failure_intervene="$(render_summary)"
assert_contains "failure outcome shown" '^Outcome: ❌ Failure$' "$out_failure_intervene"
assert_contains "failing stage reason shown" 'Failed: Gate conditions were not satisfied for stage `plan`\.' "$out_failure_intervene"
assert_contains "intervention required true" 'Operator intervention required: true' "$out_failure_intervene"
assert_contains "next action present" '^Operator next action: ' "$out_failure_intervene"

echo ""
echo "3. Failure with intervention not required"
REQUESTED_STAGE="agent-review"
reset_fixture_env
STATUS_CLASS="failure"
ELIGIBLE="true"
GATE_PASSED="true"
OPERATOR_INTERVENTION_REQUIRED="false"
FAILURE_OR_BLOCK_REASON="Transient artifact fetch failure; automatic retry will handle continuation."
OPERATOR_NEXT_ACTION=""
out_failure_no_intervention="$(render_summary)"
assert_contains "failure no intervention status" 'Operator intervention required: false' "$out_failure_no_intervention"
assert_not_contains "no manual next action emitted" '^Operator next action:' "$out_failure_no_intervention"

echo ""
echo "4. Blocked state includes PR link"
REQUESTED_STAGE="execution"
reset_fixture_env
STATUS_CLASS="blocked"
PR_NUMBER="123"
PR_URL="https://github.com/SlateLabs/github-project-automation/pull/123"
PR_BRANCH="36-improve-orchestration-run-summaries-for-operators"
FAILURE_OR_BLOCK_REASON="Blocked by open review feedback."
out_blocked="$(render_summary)"
assert_contains "blocked outcome shown" '^Outcome: ⛔ Blocked$' "$out_blocked"
assert_contains "blocked includes PR link" '- PR: \[PR #123\]\(https://github.com/SlateLabs/github-project-automation/pull/123\)' "$out_blocked"

echo ""
echo "5. Merge-conflict block includes PR link and intervention"
REQUESTED_STAGE="merge"
reset_fixture_env
STATUS_CLASS=""
PR_NUMBER="456"
PR_URL="https://github.com/SlateLabs/github-project-automation/pull/456"
PR_BRANCH="36-improve-orchestration-run-summaries-for-operators"
ELIGIBLE="true"
GATE_PASSED="true"
NEXT_STAGE=""
out_merge_conflict="$(render_summary)"
assert_contains "merge inferred as blocked" '^Outcome: ⛔ Blocked$' "$out_merge_conflict"
assert_contains "merge conflict reason shown" 'Blocked: Merge lane is blocked by unresolved merge conflicts\.' "$out_merge_conflict"
assert_contains "merge intervention required" 'Operator intervention required: true' "$out_merge_conflict"
assert_contains "merge PR link present" '- PR: \[PR #456\]\(https://github.com/SlateLabs/github-project-automation/pull/456\)' "$out_merge_conflict"

echo ""
echo "6. Waiting state includes awaited condition and resume point"
REQUESTED_STAGE="agent-review"
reset_fixture_env
STATUS_CLASS=""
TARGET_STATUS="In Review"
PR_NUMBER=""
PR_URL=""
PR_BRANCH=""
ELIGIBLE="true"
GATE_PASSED="true"
NEXT_STAGE=""
out_waiting="$(render_summary)"
assert_contains "waiting outcome shown" '^Outcome: ⏳ Waiting$' "$out_waiting"
assert_contains "waiting condition shown" 'Waiting state: Waiting for operator review input; automation will resume after approval or new feedback\.' "$out_waiting"
assert_contains "waiting next action shown" 'Operator next action: Post `gpa:approve` to continue, or `gpa:feedback \.\.\.` to request changes\.' "$out_waiting"

echo ""
echo "7. Metadata table inside details wrapper and no leading Summary heading"
assert_contains "details summary wrapper present" '^<details><summary>Dispatch metadata</summary>$' "$out_success"
assert_contains "details close present" '^</details>$' "$out_success"
first_line=$(echo "$out_success" | head -1)
if [ "$first_line" = "Outcome: ✅ Success" ]; then
  check "summary starts with outcome line" "pass"
else
  check "summary starts with outcome line" "fail"
fi
assert_not_contains "does not start with heading Summary" '^# Summary' "$out_success"

echo ""
echo "8. Deterministic output for identical input"
REQUESTED_STAGE="execution"
reset_fixture_env
NEXT_STAGE="agent-review"
STATUS_CLASS=""
ELIGIBLE="true"
GATE_PASSED="true"
PR_NUMBER=""
PR_URL=""
PR_BRANCH=""
out_det_a="$(render_summary)"
out_det_b="$(render_summary)"
if [ "$out_det_a" = "$out_det_b" ]; then
  check "byte-identical output for identical input" "pass"
else
  check "byte-identical output for identical input" "fail"
fi

echo ""
echo "=== Results ==="
echo "Passed: $PASS"
echo "Failed: $FAIL"
echo "Total:  $((PASS + FAIL))"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi

echo ""
echo "All summary rendering checks passed."
