discussion_url=""
discussion_number=""
artifact_marker="gpa:design-discussion:#${ISSUE_NUMBER}"
discussion_url=$(echo "$ISSUE_BODY" | grep -oE 'https://github\.com/[^/]+/[^/]+/discussions/[0-9]+' | head -1 || true)
if [ -z "$discussion_url" ]; then
marker_comments_json=$(python3 scripts/github_orchestration_context.py issue-comments --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" 2>/dev/null || echo '{"comments":[]}')
  marker_comment_count=$(echo "$marker_comments_json" | jq '.comments | length')
  for (( ci=0; ci<marker_comment_count; ci++ )); do
    ci_body=$(echo "$marker_comments_json" | jq -r ".comments[$ci].body // \"\"")
    if echo "$ci_body" | grep -qF "$artifact_marker"; then
      discussion_url=$(echo "$ci_body" | grep -oE 'https://github\.com/[^/]+/[^/]+/discussions/[0-9]+' | head -1 || true)
      if [ -n "$discussion_url" ]; then
        break
      fi
    fi
  done
fi
if [ -z "$discussion_url" ]; then
  if ! check_waiver "design"; then
    unmet+=("A GitHub Discussion must be linked from the issue (body or comment containing discussions/<number>)")
  fi
else
  discussion_number=$(echo "$discussion_url" | grep -oE '[0-9]+$')
  repo_path=$(echo "$discussion_url" | sed 's|https://github.com/||' | sed "s|/discussions/$discussion_number||")
  repo_owner=$(echo "$repo_path" | cut -d/ -f1)
  repo_name=$(echo "$repo_path" | cut -d/ -f2)
  current_owner="${GITHUB_REPOSITORY_OWNER:-}"
  if [ -n "$current_owner" ] && [ "$repo_owner" != "$current_owner" ]; then
    if ! check_waiver "design-same-org"; then
      unmet+=("Discussion URL points to $repo_owner/$repo_name but this repo belongs to $current_owner — discussion must be from the same org or repo")
    fi
  fi
  discussion_body=$(gh api graphql -f query='
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        discussion(number: $number) {
          body
          author { login }
          comments(first: 50) {
            nodes { author { login } }
          }
        }
      }
    }' -f owner="$repo_owner" -f name="$repo_name" -F number="$discussion_number" 2>&1) || {
    if ! check_waiver "design-api"; then
      unmet+=("Failed to fetch discussion #$discussion_number via API: $discussion_body")
    fi
    discussion_body=""
  }
  if [ -n "$discussion_body" ]; then
    disc_text=$(echo "$discussion_body" | jq -r '.data.repository.discussion.body // ""')
    disc_author=$(echo "$discussion_body" | jq -r '.data.repository.discussion.author.login // ""')
    required_headings=("Summary" "Problem" "Goals" "Non-goals" "Proposed Approach")
    for heading in "${required_headings[@]}"; do
      if ! echo "$disc_text" | grep -qE "^#{1,2}\s+${heading}"; then
        waiver_key="design-heading-$(echo "$heading" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
        if ! check_waiver "$waiver_key"; then
          unmet+=("Discussion #$discussion_number is missing required heading: ## $heading")
        fi
      fi
    done
    if echo "$disc_text" | grep -qE '^#{1,2}\s+Open Questions'; then
      oq_section=$(echo "$disc_text" | sed -n '/^##\{0,1\} Open Questions/,/^##\{0,1\} [^O]/p' | tail -n +2)
      unresolved_oq=$(echo "$oq_section" | grep -E '^\s*[-*]\s+' | grep -vE '(~~|DEFERRED-TO-PLAN)' || true)
      if [ -n "$unresolved_oq" ]; then
        if ! check_waiver "design-open-questions"; then
          oq_count=$(echo "$unresolved_oq" | wc -l | tr -d ' ')
          unmet+=("Discussion #$discussion_number has $oq_count unresolved open question(s) — strike through or mark DEFERRED-TO-PLAN")
        fi
      fi
    else
      if ! check_waiver "design-open-questions-missing"; then
        unmet+=("Discussion #$discussion_number is missing required ## Open Questions section")
      fi
    fi
    commenter_logins=$(echo "$discussion_body" | jq -r '.data.repository.discussion.comments.nodes[].author.login // ""' 2>/dev/null || true)
    has_non_author_comment="false"
    while IFS= read -r commenter; do
      if [ -n "$commenter" ] && [ "$commenter" != "$disc_author" ]; then
        has_non_author_comment="true"
        break
      fi
    done <<< "$commenter_logins"
    if [ "$has_non_author_comment" = "false" ]; then
      if ! check_waiver "design-review"; then
        unmet+=("Discussion #$discussion_number has no comments from anyone other than the author ($disc_author) — at least one review comment is required")
      fi
    fi
  fi
fi
