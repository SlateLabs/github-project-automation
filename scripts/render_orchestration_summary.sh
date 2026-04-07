#!/usr/bin/env bash
set -euo pipefail

# Renders the orchestration Actions job summary from deterministic env inputs.
# Optional normalized inputs can be supplied directly (STATUS_CLASS, reason,
# intervention flags, trigger metadata); otherwise defaults are derived from
# existing workflow outputs.

bool_normalize() {
  case "${1:-}" in
    true|TRUE|True|1|yes|YES|y|Y) echo "true" ;;
    *) echo "false" ;;
  esac
}

link_or_text() {
  local label="$1"
  local url="${2:-}"
  if [ -n "$url" ]; then
    printf '[%s](%s)' "$label" "$url"
  else
    printf '%s' "$label"
  fi
}

CURRENT_STAGE="${CURRENT_STAGE:-${REQUESTED_STAGE:-unknown}}"
ISSUE_URL="${ISSUE_URL:-https://github.com/${REPO:-}/issues/${ISSUE_NUMBER:-}}"
RUN_URL="${RUN_URL:-https://github.com/${REPO:-}/actions/runs/${RUN_ID:-}}"

if [ -z "${TRIGGER_DESCRIPTION:-}" ]; then
  if [ "${TRIGGER:-}" = "repository_dispatch" ] && [ -n "${PREVIOUS_RUN_KEY:-}" ]; then
    TRIGGER_DESCRIPTION="repository_dispatch from prior run ${PREVIOUS_RUN_KEY}"
  elif [ "${TRIGGER:-}" = "repository_dispatch" ]; then
    TRIGGER_DESCRIPTION="repository_dispatch"
  else
    TRIGGER_DESCRIPTION="workflow_dispatch"
  fi
fi

if [ -z "${TRIGGER_URL:-}" ] && [ "${TRIGGER:-}" = "repository_dispatch" ] && [ -n "${PREVIOUS_RUN_URL:-}" ]; then
  TRIGGER_URL="$PREVIOUS_RUN_URL"
fi

if [ -z "${STATUS_CLASS:-}" ]; then
  if [ "$(bool_normalize "${DUPLICATE:-false}")" = "true" ]; then
    STATUS_CLASS="waiting"
  elif [ "${ELIGIBLE:-true}" != "true" ] || [ "${GATE_PASSED:-true}" != "true" ]; then
    STATUS_CLASS="failure"
  elif [ -n "${NEXT_STAGE:-}" ]; then
    STATUS_CLASS="success"
  elif [ -z "${NEXT_STAGE:-}" ] && [ "${TARGET_STATUS:-}" = "In Review" ]; then
    STATUS_CLASS="waiting"
  elif [ "$CURRENT_STAGE" = "merge" ]; then
    STATUS_CLASS="blocked"
  else
    STATUS_CLASS="success"
  fi
fi

if [ -z "${FAILURE_OR_BLOCK_REASON:-}" ]; then
  if [ "${ELIGIBLE:-true}" != "true" ]; then
    FAILURE_OR_BLOCK_REASON="Issue is not eligible for orchestration."
  elif [ "${GATE_PASSED:-true}" != "true" ]; then
    FAILURE_OR_BLOCK_REASON="Gate conditions were not satisfied for stage \`${CURRENT_STAGE}\`."
  elif [ "$STATUS_CLASS" = "blocked" ] && [ "$CURRENT_STAGE" = "merge" ]; then
    FAILURE_OR_BLOCK_REASON="Merge lane is blocked by unresolved merge conflicts."
  else
    FAILURE_OR_BLOCK_REASON="Stage \`${CURRENT_STAGE}\` did not complete successfully."
  fi
fi

if [ -z "${ADVANCED_DESCRIPTION:-}" ]; then
  if [ -n "${NEXT_STAGE:-}" ]; then
    ADVANCED_DESCRIPTION="Advanced stage \`${CURRENT_STAGE}\`; queued \`${NEXT_STAGE}\`."
  elif [ "$CURRENT_STAGE" = "closeout" ]; then
    ADVANCED_DESCRIPTION="Advanced stage \`closeout\`; orchestration reached terminal completion."
  else
    ADVANCED_DESCRIPTION="Advanced stage \`${CURRENT_STAGE}\`."
  fi
fi

if [ -z "${NEXT_STAGE_OR_WAIT_STATE:-}" ]; then
  if [ -n "${NEXT_STAGE:-}" ]; then
    NEXT_STAGE_OR_WAIT_STATE="Next expected stage: \`${NEXT_STAGE}\`."
  elif [ "$STATUS_CLASS" = "waiting" ] && [ "${TARGET_STATUS:-}" = "In Review" ]; then
    NEXT_STAGE_OR_WAIT_STATE="Waiting for operator review input; automation will resume after approval or new feedback."
  elif [ "$STATUS_CLASS" = "waiting" ] && [ "$(bool_normalize "${DUPLICATE:-false}")" = "true" ]; then
    NEXT_STAGE_OR_WAIT_STATE="Waiting for dedup window expiry before rerun."
  elif [ "$STATUS_CLASS" = "blocked" ]; then
    NEXT_STAGE_OR_WAIT_STATE="Waiting for manual remediation before rerun."
  else
    NEXT_STAGE_OR_WAIT_STATE="No automatic handoff queued."
  fi
fi

if [ -z "${OPERATOR_INTERVENTION_REQUIRED:-}" ]; then
  case "$STATUS_CLASS" in
    failure|blocked) OPERATOR_INTERVENTION_REQUIRED="true" ;;
    waiting)
      if [ "${TARGET_STATUS:-}" = "In Review" ]; then
        OPERATOR_INTERVENTION_REQUIRED="true"
      else
        OPERATOR_INTERVENTION_REQUIRED="false"
      fi
      ;;
    *) OPERATOR_INTERVENTION_REQUIRED="false" ;;
  esac
fi

if [ -z "${OPERATOR_NEXT_ACTION:-}" ] && [ "$(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")" = "true" ]; then
  if [ "$STATUS_CLASS" = "blocked" ] && [ "$CURRENT_STAGE" = "merge" ]; then
    OPERATOR_NEXT_ACTION="Resolve conflicts on the PR branch, then re-trigger \`execution\` or \`merge\`."
  elif [ "$STATUS_CLASS" = "waiting" ] && [ "${TARGET_STATUS:-}" = "In Review" ]; then
    OPERATOR_NEXT_ACTION="Post \`gpa:approve\` to continue, or \`gpa:feedback ...\` to request changes."
  elif [ "${ELIGIBLE:-true}" != "true" ]; then
    OPERATOR_NEXT_ACTION="Update issue eligibility requirements, then re-trigger \`${CURRENT_STAGE}\`."
  else
    OPERATOR_NEXT_ACTION="Address run failure conditions, then re-trigger \`${CURRENT_STAGE}\`."
  fi
fi

run_link=$(link_or_text "run #${RUN_ID:-current}" "$RUN_URL")
issue_link=$(link_or_text "issue #${ISSUE_NUMBER:-}" "$ISSUE_URL")
pr_link=""
if [ -n "${PR_URL:-}" ] && [ -n "${PR_NUMBER:-}" ]; then
  pr_link=$(link_or_text "PR #${PR_NUMBER}" "$PR_URL")
fi
branch_link=""
if [ -n "${PR_BRANCH:-}" ] && [ -n "${REPO:-}" ]; then
  branch_link=$(link_or_text "${PR_BRANCH}" "https://github.com/${REPO}/tree/${PR_BRANCH}")
fi
trigger_line="$TRIGGER_DESCRIPTION"
if [ -n "${TRIGGER_URL:-}" ]; then
  trigger_line="$(link_or_text "$TRIGGER_DESCRIPTION" "$TRIGGER_URL")"
fi

case "$STATUS_CLASS" in
  success)
    outcome_line="Outcome: ✅ Success"
    ;;
  failure)
    outcome_line="Outcome: ❌ Failure"
    ;;
  blocked)
    outcome_line="Outcome: ⛔ Blocked"
    ;;
  waiting)
    outcome_line="Outcome: ⏳ Waiting"
    ;;
  *)
    outcome_line="Outcome: ${STATUS_CLASS}"
    ;;
esac

{
  echo "$outcome_line"
  echo ""
  echo "Trigger: $trigger_line"
  echo "Current stage: \`${CURRENT_STAGE}\`"

  case "$STATUS_CLASS" in
    success)
      echo "Advanced: $ADVANCED_DESCRIPTION"
      echo "Flow position: Stage \`${CURRENT_STAGE}\` completed successfully."
      echo "Next: $NEXT_STAGE_OR_WAIT_STATE"
      ;;
    failure)
      echo "Failed: $FAILURE_OR_BLOCK_REASON"
      echo "Operator intervention required: $(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")"
      if [ "$(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")" = "true" ] && [ -n "${OPERATOR_NEXT_ACTION:-}" ]; then
        echo "Operator next action: $OPERATOR_NEXT_ACTION"
      fi
      ;;
    blocked)
      echo "Blocked: $FAILURE_OR_BLOCK_REASON"
      echo "Operator intervention required: $(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")"
      if [ "$(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")" = "true" ] && [ -n "${OPERATOR_NEXT_ACTION:-}" ]; then
        echo "Operator next action: $OPERATOR_NEXT_ACTION"
      fi
      echo "Next: $NEXT_STAGE_OR_WAIT_STATE"
      ;;
    waiting)
      echo "Waiting state: $NEXT_STAGE_OR_WAIT_STATE"
      echo "Operator intervention required: $(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")"
      if [ "$(bool_normalize "$OPERATOR_INTERVENTION_REQUIRED")" = "true" ] && [ -n "${OPERATOR_NEXT_ACTION:-}" ]; then
        echo "Operator next action: $OPERATOR_NEXT_ACTION"
      fi
      ;;
  esac

  echo ""
  echo "Key links:"
  echo "- Run: $run_link"
  echo "- Issue: $issue_link"
  if [ -n "$pr_link" ]; then
    echo "- PR: $pr_link"
  fi
  if [ -n "$branch_link" ]; then
    echo "- Branch: $branch_link"
  fi
  if [ -n "${DISCUSSION_URL:-}" ]; then
    echo "- Discussion: $(link_or_text "design discussion" "$DISCUSSION_URL")"
  fi
  if [ -n "${DEPLOYMENT_URL:-}" ]; then
    echo "- Deployment: $(link_or_text "$DEPLOYMENT_URL" "$DEPLOYMENT_URL")"
  fi
  echo ""
  echo "<details><summary>Dispatch metadata</summary>"
  echo ""
  echo "| Field | Value |"
  echo "|-------|-------|"
  echo "| Run key | \`${RUN_KEY:-}\` |"
  echo "| Issue | $(link_or_text "#${ISSUE_NUMBER:-}" "$ISSUE_URL") |"
  echo "| Previous run | ${PREVIOUS_RUN_VALUE:-n/a} |"
  echo "| Trigger | \`${TRIGGER:-}\` |"
  echo "| Stage | \`${REQUESTED_STAGE:-}\` |"
  echo "| Actor | ${ACTOR:-} |"
  echo "| Duplicate | ${DUPLICATE:-false} |"
  echo "| Eligible | ${ELIGIBLE:-n/a} |"
  echo "| Gate passed | ${GATE_PASSED:-n/a} |"
  echo "| PR | ${PR_VALUE:-n/a} |"
  echo "| Branch | ${BRANCH_VALUE:-n/a} |"
  echo "| Project Status target | ${TARGET_STATUS:-n/a} |"
  echo "| Project Status updated | ${STATUS_UPDATED:-false} |"
  echo "| Next stage | ${NEXT_STAGE:-n/a} |"
  echo "| Next stage queued | ${HANDOFF_DISPATCHED:-false} |"
  echo ""
  echo "</details>"
} 
