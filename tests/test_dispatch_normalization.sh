#!/usr/bin/env bash
# Tests for repository_dispatch payload validation and input normalization
# in orchestration-dispatch.yml.
#
# These tests exercise the validation logic inline — they source the validation
# function and check outputs/exit codes for both trigger paths.
set -euo pipefail

PASS=0
FAIL=0
TESTS=()

# --- Test helpers ---

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1))
    echo "  ✓ $label"
  else
    FAIL=$((FAIL + 1))
    echo "  ✗ $label: expected '$expected', got '$actual'"
    TESTS+=("FAIL: $label")
  fi
}

assert_contains() {
  local label="$1" pattern="$2" text="$3"
  if echo "$text" | grep -qE "$pattern"; then
    PASS=$((PASS + 1))
    echo "  ✓ $label"
  else
    FAIL=$((FAIL + 1))
    echo "  ✗ $label: pattern '$pattern' not found in output"
    TESTS+=("FAIL: $label")
  fi
}

# The normalize step validation logic extracted as a function.
# Takes env vars as arguments and writes outputs to a temp file.
# Returns 0 on valid, 1 on invalid.
run_validation() {
  local trigger="$1"
  local rd_issue_number="${2:-}"
  local rd_requested_stage="${3:-}"
  local rd_run_key="${4:-}"
  local rd_actor="${5:-}"
  local rd_timestamp="${6:-}"
  local rd_project_item_id="${7:-}"
  local rd_feedback_instructions="${8:-}"
  local rd_source_command="${9:-}"
  local rd_source_comment_id="${10:-}"
  local wd_issue_number="${11:-}"
  local wd_requested_stage="${12:-}"
  local wd_actor="${13:-}"
  local current_repo="${14:-}"

  local output_file
  output_file=$(mktemp)
  local error_output
  error_output=$(mktemp)

  VALID_STAGES="kickoff clarification design plan execution deploy-review review-intake feedback-implementation redeploy-review merge post-merge-verify follow-up-capture review closeout"

  (
    set -euo pipefail
    GITHUB_OUTPUT="$output_file"

    if [ "$trigger" = "repository_dispatch" ]; then
      errors=()

      if [ -z "${rd_issue_number:-}" ]; then
        errors+=("missing required field: issue_number")
      elif ! echo "$rd_issue_number" | grep -qE '^[1-9][0-9]*$'; then
        errors+=("issue_number must be a positive integer, got: '${rd_issue_number}'")
      fi

      if [ -z "${rd_requested_stage:-}" ]; then
        errors+=("missing required field: requested_stage")
      else
        stage_valid="false"
        for s in $VALID_STAGES; do
          if [ "$s" = "$rd_requested_stage" ]; then
            stage_valid="true"
            break
          fi
        done
        if [ "$stage_valid" = "false" ]; then
          errors+=("unknown requested_stage: '${rd_requested_stage}'")
        fi
      fi

      if [ -z "${rd_run_key:-}" ]; then
        errors+=("missing required field: run_key")
      elif ! echo "$rd_run_key" | grep -qE '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[0-9]+/[A-Za-z0-9_-]+/[0-9]+$'; then
        errors+=("run_key does not match canonical format")
      else
        # Parse run_key and validate consistency with payload fields
        rk_owner=$(echo "$rd_run_key" | cut -d/ -f1)
        rk_repo=$(echo "$rd_run_key" | cut -d/ -f2)
        rk_issue=$(echo "$rd_run_key" | cut -d/ -f3)
        rk_stage=$(echo "$rd_run_key" | cut -d/ -f4)
        rk_timestamp=$(echo "$rd_run_key" | cut -d/ -f5)

        if [ -n "${current_repo:-}" ] && [ "${rk_owner}/${rk_repo}" != "$current_repo" ]; then
          errors+=("run_key repo '${rk_owner}/${rk_repo}' does not match current repo '${current_repo}'")
        fi
        if [ -n "${rd_issue_number:-}" ] && [ "$rk_issue" != "$rd_issue_number" ]; then
          errors+=("run_key issue_number '${rk_issue}' does not match client_payload.issue_number '${rd_issue_number}'")
        fi
        if [ -n "${rd_requested_stage:-}" ] && [ "$rk_stage" != "$rd_requested_stage" ]; then
          errors+=("run_key stage '${rk_stage}' does not match client_payload.requested_stage '${rd_requested_stage}'")
        fi
        if [ -n "${rd_timestamp:-}" ] && [ "$rk_timestamp" != "$rd_timestamp" ]; then
          errors+=("run_key timestamp '${rk_timestamp}' does not match client_payload.timestamp '${rd_timestamp}'")
        fi
      fi

      if [ -z "${rd_actor:-}" ]; then
        errors+=("missing required field: actor")
      fi

      if [ -z "${rd_timestamp:-}" ]; then
        errors+=("missing required field: timestamp")
      fi

      has_source_command="false"
      has_source_comment_id="false"
      if [ -n "${rd_source_command:-}" ]; then
        has_source_command="true"
        case "$rd_source_command" in
          feedback|approve) ;;
          *)
            errors+=("source_command must be one of: feedback, approve")
            ;;
        esac
      fi
      if [ -n "${rd_source_comment_id:-}" ]; then
        has_source_comment_id="true"
        if ! echo "$rd_source_comment_id" | grep -qE '^[1-9][0-9]*$'; then
          errors+=("source_comment_id must be a positive integer")
        fi
      fi
      if [ "$has_source_command" = "true" ] && [ "$has_source_comment_id" = "false" ]; then
        errors+=("source_comment_id is required when source_command is provided")
      fi
      if [ "$has_source_command" = "false" ] && [ "$has_source_comment_id" = "true" ]; then
        errors+=("source_command is required when source_comment_id is provided")
      fi
      if [ "$rd_source_command" = "feedback" ]; then
        if [ "$rd_requested_stage" != "feedback-implementation" ]; then
          errors+=("source_command 'feedback' requires requested_stage 'feedback-implementation'")
        fi
        if [ -z "${rd_feedback_instructions:-}" ]; then
          errors+=("feedback_instructions is required when source_command is 'feedback'")
        fi
      fi
      if [ "$rd_source_command" = "approve" ] && [ "$rd_requested_stage" != "merge" ]; then
        errors+=("source_command 'approve' requires requested_stage 'merge'")
      fi
      if [ -n "${rd_feedback_instructions:-}" ] && [ "${rd_source_command:-}" != "feedback" ]; then
        errors+=("feedback_instructions may only be set when source_command is 'feedback'")
      fi

      if [ ${#errors[@]} -gt 0 ]; then
        for e in "${errors[@]}"; do
          echo "ERROR: $e" >&2
        done
        exit 1
      fi

      echo "issue_number=${rd_issue_number}" >> "$GITHUB_OUTPUT"
      echo "requested_stage=${rd_requested_stage}" >> "$GITHUB_OUTPUT"
      echo "actor=${rd_actor}" >> "$GITHUB_OUTPUT"
      echo "trigger=repository_dispatch" >> "$GITHUB_OUTPUT"
      echo "project_item_id=${rd_project_item_id}" >> "$GITHUB_OUTPUT"
      echo "source_command=${rd_source_command}" >> "$GITHUB_OUTPUT"
      echo "source_comment_id=${rd_source_comment_id}" >> "$GITHUB_OUTPUT"
      echo "feedback_instructions=${rd_feedback_instructions}" >> "$GITHUB_OUTPUT"
    else
      echo "issue_number=${wd_issue_number}" >> "$GITHUB_OUTPUT"
      echo "requested_stage=${wd_requested_stage}" >> "$GITHUB_OUTPUT"
      echo "actor=${wd_actor}" >> "$GITHUB_OUTPUT"
      echo "trigger=workflow_dispatch" >> "$GITHUB_OUTPUT"
      echo "project_item_id=" >> "$GITHUB_OUTPUT"
      echo "source_command=" >> "$GITHUB_OUTPUT"
      echo "source_comment_id=" >> "$GITHUB_OUTPUT"
      echo "feedback_instructions=" >> "$GITHUB_OUTPUT"
    fi
  ) 2>"$error_output"
  local rc=$?

  # Return outputs
  LAST_OUTPUT=$(cat "$output_file")
  LAST_ERRORS=$(cat "$error_output")
  rm -f "$output_file" "$error_output"
  return $rc
}

get_output() {
  local key="$1"
  echo "$LAST_OUTPUT" | grep "^${key}=" | head -1 | cut -d= -f2-
}

# --- Tests ---

echo "=== Payload Validation Tests ==="

echo ""
echo "1. Valid repository_dispatch payload"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/github-project-automation/42/kickoff/1711234567890" "jflamb" "1711234567890" "PVTI_123"; then
  assert_eq "issue_number" "42" "$(get_output issue_number)"
  assert_eq "requested_stage" "kickoff" "$(get_output requested_stage)"
  assert_eq "actor" "jflamb" "$(get_output actor)"
  assert_eq "trigger" "repository_dispatch" "$(get_output trigger)"
  assert_eq "project_item_id" "PVTI_123" "$(get_output project_item_id)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ Valid payload should not fail validation"
  TESTS+=("FAIL: valid payload rejected")
fi

echo ""
echo "2. Missing issue_number"
if run_validation "repository_dispatch" \
  "" "kickoff" "SlateLabs/repo/42/kickoff/123" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with missing issue_number"
  TESTS+=("FAIL: missing issue_number accepted")
else
  assert_contains "error mentions issue_number" "missing required field: issue_number" "$LAST_ERRORS"
fi

echo ""
echo "3. Non-integer issue_number"
if run_validation "repository_dispatch" \
  "abc" "kickoff" "SlateLabs/repo/42/kickoff/123" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with non-integer issue_number"
  TESTS+=("FAIL: non-integer issue_number accepted")
else
  assert_contains "error mentions positive integer" "issue_number must be a positive integer" "$LAST_ERRORS"
fi

echo ""
echo "4. Zero issue_number"
if run_validation "repository_dispatch" \
  "0" "kickoff" "SlateLabs/repo/0/kickoff/123" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with zero issue_number"
  TESTS+=("FAIL: zero issue_number accepted")
else
  assert_contains "error mentions positive integer" "issue_number must be a positive integer" "$LAST_ERRORS"
fi

echo ""
echo "5. Unknown requested_stage"
if run_validation "repository_dispatch" \
  "42" "invalid-stage" "SlateLabs/repo/42/invalid-stage/123" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with unknown stage"
  TESTS+=("FAIL: unknown stage accepted")
else
  assert_contains "error mentions unknown stage" "unknown requested_stage" "$LAST_ERRORS"
fi

echo ""
echo "6. Missing requested_stage"
if run_validation "repository_dispatch" \
  "42" "" "SlateLabs/repo/42/kickoff/123" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with missing stage"
  TESTS+=("FAIL: missing stage accepted")
else
  assert_contains "error mentions stage" "missing required field: requested_stage" "$LAST_ERRORS"
fi

echo ""
echo "7. Malformed run_key"
if run_validation "repository_dispatch" \
  "42" "kickoff" "bad-key-format" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with bad run_key format"
  TESTS+=("FAIL: bad run_key accepted")
else
  assert_contains "error mentions run_key format" "run_key does not match canonical format" "$LAST_ERRORS"
fi

echo ""
echo "8. Missing run_key"
if run_validation "repository_dispatch" \
  "42" "kickoff" "" "actor1" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with missing run_key"
  TESTS+=("FAIL: missing run_key accepted")
else
  assert_contains "error mentions run_key" "missing required field: run_key" "$LAST_ERRORS"
fi

echo ""
echo "9. Empty actor"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/repo/42/kickoff/123" "" "123" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with empty actor"
  TESTS+=("FAIL: empty actor accepted")
else
  assert_contains "error mentions actor" "missing required field: actor" "$LAST_ERRORS"
fi

echo ""
echo "10. Empty timestamp"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/repo/42/kickoff/123" "actor1" "" "PVTI_123"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with empty timestamp"
  TESTS+=("FAIL: empty timestamp accepted")
else
  assert_contains "error mentions timestamp" "missing required field: timestamp" "$LAST_ERRORS"
fi

echo ""
echo "11. Multiple validation errors reported together"
if run_validation "repository_dispatch" \
  "" "" "" "" "" ""; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with multiple errors"
  TESTS+=("FAIL: all-empty payload accepted")
else
  assert_contains "mentions issue_number" "issue_number" "$LAST_ERRORS"
  assert_contains "mentions requested_stage" "requested_stage" "$LAST_ERRORS"
  assert_contains "mentions run_key" "run_key" "$LAST_ERRORS"
  assert_contains "mentions actor" "actor" "$LAST_ERRORS"
  assert_contains "mentions timestamp" "timestamp" "$LAST_ERRORS"
fi

echo ""
echo "=== Trigger-Path Parity Tests ==="

echo ""
echo "12. workflow_dispatch produces normalized outputs"
if run_validation "workflow_dispatch" \
  "" "" "" "" "" "" "" "" "" "99" "design" "operator-user" ""; then
  assert_eq "issue_number" "99" "$(get_output issue_number)"
  assert_eq "requested_stage" "design" "$(get_output requested_stage)"
  assert_eq "actor" "operator-user" "$(get_output actor)"
  assert_eq "trigger" "workflow_dispatch" "$(get_output trigger)"
  assert_eq "project_item_id" "" "$(get_output project_item_id)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ workflow_dispatch normalization should not fail"
  TESTS+=("FAIL: workflow_dispatch normalization failed")
fi

echo ""
echo "13. repository_dispatch produces same output shape as workflow_dispatch"
if run_validation "repository_dispatch" \
  "99" "design" "SlateLabs/repo/99/design/1711234567890" "gateway-actor" "1711234567890" "PVTI_99"; then
  assert_eq "issue_number" "99" "$(get_output issue_number)"
  assert_eq "requested_stage" "design" "$(get_output requested_stage)"
  assert_eq "actor" "gateway-actor" "$(get_output actor)"
  assert_eq "trigger" "repository_dispatch" "$(get_output trigger)"
  assert_eq "project_item_id" "PVTI_99" "$(get_output project_item_id)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ repository_dispatch normalization should not fail for valid payload"
  TESTS+=("FAIL: valid repository_dispatch normalization failed")
fi

echo ""
echo "=== Run Key Tests ==="

echo ""
echo "14. All valid stages accepted"
for stage in kickoff clarification design plan execution deploy-review review-intake feedback-implementation redeploy-review merge post-merge-verify follow-up-capture review closeout; do
if run_validation "repository_dispatch" \
    "1" "$stage" "Org/repo/1/${stage}/100" "actor" "100" "PVTI_1"; then
    PASS=$((PASS + 1))
    echo "  ✓ stage '$stage' accepted"
  else
    FAIL=$((FAIL + 1))
    echo "  ✗ stage '$stage' rejected"
    TESTS+=("FAIL: stage $stage rejected")
  fi
done

echo ""
echo "15. Run key with dots and hyphens in owner/repo accepted"
if run_validation "repository_dispatch" \
  "5" "kickoff" "My-Org.name/my-repo.test/5/kickoff/999" "actor" "999" "PVTI_5"; then
  assert_eq "issue_number" "5" "$(get_output issue_number)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ run_key with dots/hyphens should be accepted"
  TESTS+=("FAIL: run_key with special chars rejected")
fi

echo ""
echo "=== Run Key Consistency Tests ==="

echo ""
echo "16. run_key repo mismatch rejected"
if run_validation "repository_dispatch" \
  "42" "kickoff" "WrongOrg/wrong-repo/42/kickoff/1711234567890" "actor1" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" "SlateLabs/github-project-automation"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with repo mismatch"
  TESTS+=("FAIL: repo mismatch accepted")
else
  assert_contains "error mentions repo mismatch" "run_key repo.*does not match current repo" "$LAST_ERRORS"
fi

echo ""
echo "17. run_key issue_number mismatch rejected"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/github-project-automation/99/kickoff/1711234567890" "actor1" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" "SlateLabs/github-project-automation"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with issue_number mismatch"
  TESTS+=("FAIL: issue_number mismatch accepted")
else
  assert_contains "error mentions issue_number mismatch" "run_key issue_number.*does not match" "$LAST_ERRORS"
fi

echo ""
echo "18. run_key stage mismatch rejected"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/github-project-automation/42/design/1711234567890" "actor1" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" "SlateLabs/github-project-automation"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with stage mismatch"
  TESTS+=("FAIL: stage mismatch accepted")
else
  assert_contains "error mentions stage mismatch" "run_key stage.*does not match" "$LAST_ERRORS"
fi

echo ""
echo "19. run_key timestamp mismatch rejected"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/github-project-automation/42/kickoff/9999999999999" "actor1" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" "SlateLabs/github-project-automation"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with timestamp mismatch"
  TESTS+=("FAIL: timestamp mismatch accepted")
else
  assert_contains "error mentions timestamp mismatch" "run_key timestamp.*does not match" "$LAST_ERRORS"
fi

echo ""
echo "20. Consistent run_key with current_repo passes"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/github-project-automation/42/kickoff/1711234567890" "jflamb" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" "SlateLabs/github-project-automation"; then
  assert_eq "issue_number" "42" "$(get_output issue_number)"
  assert_eq "trigger" "repository_dispatch" "$(get_output trigger)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ Consistent run_key should pass validation"
  TESTS+=("FAIL: consistent run_key rejected")
fi

echo ""
echo "21. run_key consistency skipped when current_repo is empty (no GITHUB_REPOSITORY)"
if run_validation "repository_dispatch" \
  "42" "kickoff" "AnyOrg/any-repo/42/kickoff/1711234567890" "actor1" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" ""; then
  assert_eq "issue_number" "42" "$(get_output issue_number)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ Should pass when current_repo is empty (repo check skipped)"
  TESTS+=("FAIL: empty current_repo caused rejection")
fi

echo ""
echo "22. Multiple run_key mismatches reported together"
if run_validation "repository_dispatch" \
  "42" "kickoff" "WrongOrg/wrong-repo/99/design/9999999999999" "actor1" "1711234567890" "PVTI_42" \
  "" "" "" "" "" "" "SlateLabs/github-project-automation"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with multiple mismatches"
  TESTS+=("FAIL: multiple mismatches accepted")
else
  assert_contains "mentions repo mismatch" "run_key repo" "$LAST_ERRORS"
  assert_contains "mentions issue_number mismatch" "run_key issue_number" "$LAST_ERRORS"
  assert_contains "mentions stage mismatch" "run_key stage" "$LAST_ERRORS"
  assert_contains "mentions timestamp mismatch" "run_key timestamp" "$LAST_ERRORS"
fi

echo ""
echo "23. Missing project_item_id is tolerated for manual/retry compatibility"
if run_validation "repository_dispatch" \
  "42" "kickoff" "SlateLabs/repo/42/kickoff/123" "actor1" "123" ""; then
  assert_eq "project_item_id" "" "$(get_output project_item_id)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ Missing project_item_id should be tolerated"
  TESTS+=("FAIL: missing project_item_id rejected")
fi

echo ""
echo "24. feedback source contract accepts coherent feedback payload"
if run_validation "repository_dispatch" \
  "77" "feedback-implementation" "SlateLabs/repo/77/feedback-implementation/123" "trusted-user" "123" "PVTI_77" \
  "tighten retry guardrails" "feedback" "7001"; then
  assert_eq "source_command" "feedback" "$(get_output source_command)"
  assert_eq "source_comment_id" "7001" "$(get_output source_comment_id)"
  assert_eq "feedback_instructions" "tighten retry guardrails" "$(get_output feedback_instructions)"
else
  FAIL=$((FAIL + 1))
  echo "  ✗ coherent feedback payload should pass"
  TESTS+=("FAIL: coherent feedback payload rejected")
fi

echo ""
echo "25. feedback source contract rejects missing feedback instructions"
if run_validation "repository_dispatch" \
  "77" "feedback-implementation" "SlateLabs/repo/77/feedback-implementation/123" "trusted-user" "123" "PVTI_77" \
  "" "feedback" "7002"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with missing feedback instructions"
  TESTS+=("FAIL: missing feedback instructions accepted")
else
  assert_contains "error mentions feedback instructions" "feedback_instructions is required when source_command is 'feedback'" "$LAST_ERRORS"
fi

echo ""
echo "26. feedback source contract rejects feedback command routed to wrong stage"
if run_validation "repository_dispatch" \
  "77" "merge" "SlateLabs/repo/77/merge/123" "trusted-user" "123" "PVTI_77" \
  "please adjust" "feedback" "7003"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with feedback stage mismatch"
  TESTS+=("FAIL: feedback stage mismatch accepted")
else
  assert_contains "error mentions feedback stage mapping" "source_command 'feedback' requires requested_stage 'feedback-implementation'" "$LAST_ERRORS"
fi

echo ""
echo "27. feedback source contract rejects orphan source_comment_id"
if run_validation "repository_dispatch" \
  "77" "kickoff" "SlateLabs/repo/77/kickoff/123" "trusted-user" "123" "PVTI_77" \
  "" "" "7004"; then
  FAIL=$((FAIL + 1))
  echo "  ✗ Should have failed with missing source_command"
  TESTS+=("FAIL: orphan source_comment_id accepted")
else
  assert_contains "error mentions source_command requirement" "source_command is required when source_comment_id is provided" "$LAST_ERRORS"
fi

echo ""
echo "=== Results ==="
echo "Passed: $PASS"
echo "Failed: $FAIL"
echo "Total:  $((PASS + FAIL))"

if [ $FAIL -gt 0 ]; then
  echo ""
  echo "Failed tests:"
  for t in "${TESTS[@]}"; do
    echo "  $t"
  done
  exit 1
fi

echo ""
echo "All tests passed."
