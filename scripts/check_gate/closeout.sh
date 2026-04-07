closeout_merged_pr=""
closeout_merged_branch=""
closeout_branch_json=$(python3 scripts/github_orchestration_context.py latest-pr --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" --state merged)
closeout_merged_pr=$(echo "$closeout_branch_json" | jq -r '.number // empty')
closeout_merged_branch=$(echo "$closeout_branch_json" | jq -r '.headRefName // empty')
if [ -z "$closeout_merged_pr" ]; then
  if ! check_waiver "closeout-merged-pr"; then
    unmet+=("No merged PR found referencing issue #${ISSUE_NUMBER} — a merged PR is required for closeout")
  fi
fi
if [ -n "$closeout_merged_branch" ]; then
  if gh api "repos/{owner}/{repo}/branches/${closeout_merged_branch}" --silent >/dev/null 2>&1; then
    if ! check_waiver "closeout-branch-deleted"; then
      unmet+=("Source branch '${closeout_merged_branch}' from merged PR #${closeout_merged_pr} still exists — delete it before closeout")
    fi
  fi
fi
closeout_comments_json=$(python3 scripts/github_orchestration_context.py issue-comments --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" 2>/dev/null || echo '{"comments":[]}')
followup_valid_count=$(echo "$closeout_comments_json" | python3 -c "import sys,json,re;vc={'technical-debt','accessibility','usability','documentation','automation','defect'};data=json.load(sys.stdin);cs=data.get('comments',[]);count=sum(1 for c in cs for m in re.finditer(r'<!--\s*FOLLOW-UP:\s*(.*?)-->',c.get('body',''),re.DOTALL) if len(m.group(1).split('|'))==5 and all(f.strip() for f in m.group(1).split('|')) and m.group(1).split('|')[1].strip() in vc and m.group(1).split('|')[4].strip().lower() in ('yes','no'));print(count)" 2>/dev/null || echo "0")
followup_status_marker="gpa:follow-up-status:#${ISSUE_NUMBER}"
followup_status_found=$(echo "$closeout_comments_json" | jq -r '.comments[].body // ""' | grep -cF "$followup_status_marker" || true)
if [ "$followup_valid_count" -eq 0 ] && [ "$followup_status_found" -eq 0 ]; then
  if ! check_waiver "closeout-follow-ups"; then
    unmet+=("No follow-up capture evidence found — run follow-up-capture stage or add valid FOLLOW-UP markers (all 5 fields required) before closeout")
  fi
fi
if [ "${CHECK_MODE:-full}" = "pre-scaffold" ]; then
  echo "::notice::Pre-scaffold mode: skipping closeout scaffold content checks (4–7)"
else
  repo_full_closeout="${GITHUB_REPOSITORY:-SlateLabs/github-project-automation}"
  closeout_artifact_marker="gpa:owned-artifact:closeout:${repo_full_closeout}#${ISSUE_NUMBER}"
  closeout_comment_body=""
  closeout_comment_count=$(echo "$closeout_comments_json" | jq '.comments | length')
  for (( ci=0; ci<closeout_comment_count; ci++ )); do
    ci_body=$(echo "$closeout_comments_json" | jq -r ".comments[$ci].body // \"\"")
    if echo "$ci_body" | grep -qF "$closeout_artifact_marker"; then
      closeout_comment_body="$ci_body"
      break
    fi
  done
  if [ -z "$closeout_comment_body" ]; then
    if ! check_waiver "closeout-scaffold"; then
      unmet+=("No closeout scaffold comment found — the closeout retrospective must be posted before advancing")
    fi
  else
    if ! echo "$closeout_comment_body" | grep -qE '^#{1,2}\s+Closeout'; then
      if ! check_waiver "closeout-heading"; then
        unmet+=("Closeout comment is missing required ## Closeout heading")
      fi
    fi
    if ! echo "$closeout_comment_body" | grep -qE '^#{1,2}\s+Deferred Work'; then
      if ! check_waiver "closeout-deferred-work"; then
        unmet+=("Closeout comment is missing required ## Deferred Work section")
      fi
    fi
    if ! echo "$closeout_comment_body" | grep -qE '^#{1,2}\s+Process Improvement'; then
      if ! check_waiver "closeout-process-improvement"; then
        unmet+=("Closeout comment is missing required ## Process Improvement section")
      fi
    else
      pi_section=$(echo "$closeout_comment_body" | sed -n '/^##\{0,1\} Process Improvement/,/^##\{0,1\} [^P]/p' | tail -n +2)
      pi_authored=$(echo "$pi_section" | sed '/<!--/,/-->/d' | grep -v '^- _To be filled' | grep -v '^\s*$')
      pi_disposition_re='\*\*\s*(adopt|backlog|reject)\s*\*\*'
      if ! echo "$pi_authored" | grep -qiE "$pi_disposition_re"; then
        if ! check_waiver "closeout-process-improvement-dispositions"; then
          unmet+=("## Process Improvement section must contain at least one item dispositioned as adopt, backlog, or reject")
        fi
      fi
    fi
  fi
fi
