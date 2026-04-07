followup_comments_json=$(python3 scripts/github_orchestration_context.py issue-comments --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" 2>/dev/null || echo '{"comments":[]}')
followup_marker_count=$(echo "$followup_comments_json" | python3 -c "import sys,json,re;vc={'technical-debt','accessibility','usability','documentation','automation','defect'};data=json.load(sys.stdin);cs=data.get('comments',[]);count=sum(1 for c in cs for m in re.finditer(r'<!--\s*FOLLOW-UP:\s*(.*?)-->',c.get('body',''),re.DOTALL) if len([f for f in (f.strip() for f in m.group(1).split('|')) if f])==5 and len(m.group(1).split('|'))==5 and m.group(1).split('|')[1].strip() in vc and m.group(1).split('|')[4].strip().lower() in ('yes','no'));print(count)")
if [ "$followup_marker_count" -eq 0 ]; then
  waived+=("follow-up-capture-no-followups")
fi
merged_pr_json=$(python3 scripts/github_orchestration_context.py latest-pr --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" --state merged)
merged_pr_number=$(echo "$merged_pr_json" | jq -r '.number // empty')
if [ -z "$merged_pr_number" ]; then
  if ! check_waiver "follow-up-capture-merged-pr"; then
    unmet+=("No merged PR found referencing issue #${ISSUE_NUMBER} — execution must be complete before capturing follow-ups")
  fi
fi
open_pr_json=$(python3 scripts/github_orchestration_context.py latest-pr --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" --state open)
open_pr_number=$(echo "$open_pr_json" | jq -r '.number // empty')
if [ -n "$open_pr_number" ]; then
  if ! check_waiver "follow-up-capture-open-prs"; then
    unmet+=("Open PRs still reference issue #${ISSUE_NUMBER} — all execution PRs must be merged or closed before capturing follow-ups")
  fi
fi
