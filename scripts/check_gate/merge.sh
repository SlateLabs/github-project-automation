merge_pr_json=$(python3 scripts/github_orchestration_context.py latest-pr --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" --state open)
merge_pr_number=$(echo "$merge_pr_json" | jq -r '.number // empty')
if [ -z "$merge_pr_number" ]; then
  if ! check_waiver "merge-pr"; then
    unmet+=("No open PR found referencing issue #${ISSUE_NUMBER} — an open PR is required for merge")
  fi
fi
approval_comments_json=$(gh issue view "$ISSUE_NUMBER" --comments --json comments --jq '.comments[] | {author: .author.login, body: .body}' 2>/dev/null || true)
approval_found="false"
while IFS= read -r comment_line; do
  [ -z "$comment_line" ] && continue
  comment_author=$(echo "$comment_line" | jq -r '.author // ""')
  comment_body=$(echo "$comment_line" | jq -r '.body // ""')
  author_trusted="false"
  if [ -n "$trusted_users_list" ]; then
    while IFS= read -r tuser; do
      if [ "$tuser" = "$comment_author" ]; then
        author_trusted="true"
        break
      fi
    done <<< "$trusted_users_list"
  fi
  if [ "$author_trusted" = "true" ] && echo "$comment_body" | grep -qi '^gpa:approve\b'; then
    approval_found="true"
    break
  fi
done < <(echo "$approval_comments_json" | jq -c '.' 2>/dev/null || true)
agent_review_auto_approved="false"
agent_review_json=$(python3 scripts/github_orchestration_context.py latest-agent-review --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER")
if [ "$(echo "$agent_review_json" | jq -r '.disposition // ""')" = "auto-approve" ]; then
  agent_review_auto_approved="true"
fi
if [ "$approval_found" != "true" ] && [ "$agent_review_auto_approved" != "true" ]; then
  if ! check_waiver "merge-approval"; then
    unmet+=("No trusted operator approval or auto-approved agent review found — post gpa:approve or rerun agent-review with auto-approve before merge")
  fi
fi
