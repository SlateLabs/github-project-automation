comments_json=$(python3 scripts/github_orchestration_context.py issue-comments --repo "$GITHUB_REPOSITORY" --issue-number "$ISSUE_NUMBER" 2>/dev/null || echo '{"comments":[]}')
plan_comment_found="false"
plan_missing_headings=()
comment_count=$(echo "$comments_json" | jq '.comments | length')
for (( i=0; i<comment_count; i++ )); do
  comment_body=$(echo "$comments_json" | jq -r ".comments[$i].body // \"\"")
  if echo "$comment_body" | grep -qE '^#{1,2}\s+Implementation Plan'; then
    plan_comment_found="true"
    plan_missing_headings=()
    if ! echo "$comment_body" | grep -qE '^#{1,2}\s+Acceptance Criteria'; then
      plan_missing_headings+=("## Acceptance Criteria")
    fi
    if ! echo "$comment_body" | grep -qE '^#{1,2}\s+Verification Plan'; then
      plan_missing_headings+=("## Verification Plan")
    fi
    if ! echo "$comment_body" | grep -qE '^#{1,2}\s+Review Expectations'; then
      plan_missing_headings+=("## Review Expectations")
    fi
    if ! echo "$comment_body" | grep -qE '^#{1,2}\s+Slices'; then
      plan_missing_headings+=("## Slices")
    fi
    if [ ${#plan_missing_headings[@]} -eq 0 ]; then
      ac_section=$(echo "$comment_body" | sed -n '/^##\{0,1\} Acceptance Criteria/,/^##\{0,1\} [^A]/p' | tail -n +2)
      if ! echo "$ac_section" | grep -qE '^\s*- \[[ xX]\]'; then
        if ! check_waiver "plan-acceptance-criteria-content"; then
          unmet+=("## Acceptance Criteria must contain at least one checklist item (- [ ] or - [x])")
        fi
      fi
      vp_section=$(echo "$comment_body" | sed -n '/^##\{0,1\} Verification Plan/,/^##\{0,1\} [^V]/p' | tail -n +2)
      if ! echo "$vp_section" | grep -qE '^\s*- \[[ xX]\]'; then
        if ! check_waiver "plan-verification-plan-content"; then
          unmet+=("## Verification Plan must contain at least one checklist item (- [ ] or - [x])")
        fi
      fi
      re_section=$(echo "$comment_body" | sed -n '/^##\{0,1\} Review Expectations/,/^##\{0,1\} [^R]/p' | tail -n +2)
      re_disposition_re='(required|waived|N/A|n/a|deferred)'
      re_missing_cats=()
      if ! echo "$re_section" | grep -iE 'accessibility' | grep -qiE "$re_disposition_re"; then re_missing_cats+=("accessibility"); fi
      if ! echo "$re_section" | grep -iE 'usability\s*/\s*content' | grep -qiE "$re_disposition_re"; then re_missing_cats+=("usability/content"); fi
      if ! echo "$re_section" | grep -iE 'documentation' | grep -qiE "$re_disposition_re"; then re_missing_cats+=("documentation"); fi
      if ! echo "$re_section" | grep -iE 'hygiene' | grep -qiE "$re_disposition_re"; then re_missing_cats+=("hygiene"); fi
      if [ ${#re_missing_cats[@]} -gt 0 ]; then
        if ! check_waiver "plan-review-expectations-content"; then
          missing_list=$(IFS=', '; echo "${re_missing_cats[*]}")
          unmet+=("## Review Expectations must list explicit dispositions (required/waived/N/A/deferred) for: accessibility, usability/content, documentation, hygiene — missing or lacking disposition: $missing_list")
        fi
      fi
      slices_section=$(echo "$comment_body" | sed -n '/^##\{0,1\} Slices/,/^##\{0,1\} [^S]/p' | tail -n +2)
      if ! echo "$slices_section" | grep -qE '(^[0-9]+\.|^#{2,3}\s+(Slice|Step)\s+[0-9])'; then
        if ! check_waiver "plan-slices-content"; then
          unmet+=("## Slices must contain numbered items (1. ...) or numbered slice headings (### Slice 1)")
        fi
      fi
      break
    fi
  fi
done
if [ "$plan_comment_found" = "false" ]; then
  if ! check_waiver "plan-exists"; then
    unmet+=("No comment contains ## Implementation Plan heading")
  fi
elif [ ${#plan_missing_headings[@]} -gt 0 ]; then
  for heading in "${plan_missing_headings[@]}"; do
    waiver_key="plan-$(echo "$heading" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | sed 's/^-//;s/-$//')"
    if ! check_waiver "$waiver_key"; then
      unmet+=("Plan comment is missing required heading: $heading (all required headings must be co-located in a single comment)")
    fi
  done
fi
