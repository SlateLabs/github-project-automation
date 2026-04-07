agent_review_pr_json=$(python3 scripts/github_orchestration_context.py latest-pr --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" --state open)
agent_review_pr_number=$(echo "$agent_review_pr_json" | jq -r '.number // empty')
if [ -z "$agent_review_pr_number" ]; then
  if ! check_waiver "agent-review-pr"; then
    unmet+=("No open PR found referencing issue #${ISSUE_NUMBER} — an agent-reviewable PR is required")
  fi
else
  agent_review_is_draft=$(echo "$agent_review_pr_json" | jq -r '.isDraft // false')
  if [ "$agent_review_is_draft" = "true" ]; then
    if ! check_waiver "agent-review-draft"; then
      unmet+=("PR #$agent_review_pr_number is still draft — mark it ready for review before agent-review")
    fi
  fi
fi
