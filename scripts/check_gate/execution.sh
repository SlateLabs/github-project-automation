branch_exists=$(gh api "repos/{owner}/{repo}/branches" --paginate --jq ".[].name | select(test(\"^${ISSUE_NUMBER}[-/]\"))" 2>/dev/null | head -1 || true)
if [ -z "$branch_exists" ]; then
  if ! check_waiver "execution-branch"; then
    unmet+=("A branch matching ${ISSUE_NUMBER}-* or ${ISSUE_NUMBER}/* must exist")
  fi
fi
pr_json=$(python3 scripts/github_orchestration_context.py latest-pr --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" --state open)
pr_number=$(echo "$pr_json" | jq -r '.number // empty')
if [ -z "$pr_number" ]; then
  if ! check_waiver "execution-pr"; then
    unmet+=("A pull request referencing issue #${ISSUE_NUMBER} must exist")
  fi
else
  pr_is_draft=$(echo "$pr_json" | jq -r '.isDraft // false')
  if [ "$pr_is_draft" = "true" ]; then
    if ! check_waiver "execution-draft"; then
      unmet+=("PR #$pr_number is still in draft state — mark as ready for review or use GATE-WAIVER: execution-draft")
    fi
  fi
  pr_body=$(echo "$pr_json" | jq -r '.body // ""')
  if ! echo "$pr_body" | grep -qE '^#{1,2}\s+Summary'; then
    if ! check_waiver "execution-summary"; then
      unmet+=("PR #$pr_number body is missing required ## Summary heading")
    fi
  fi
  if ! echo "$pr_body" | grep -qE '^#{1,2}\s+Test [Pp]lan'; then
    if ! check_waiver "execution-test-plan"; then
      unmet+=("PR #$pr_number body is missing required ## Test plan heading")
    fi
  fi
fi
