if ! echo "$ISSUE_BODY" | grep -qE '^#{1,2}\s+Summary'; then
  if ! check_waiver "clarification-summary"; then
    unmet+=("Issue body must contain a ## Summary heading")
  fi
fi
if ! echo "$ISSUE_BODY" | grep -qE '^#{1,2}\s+(Scope|Open Questions)'; then
  if ! check_waiver "clarification-scope"; then
    unmet+=("Issue body must contain a ## Scope or ## Open Questions heading")
  fi
fi
issue_labels=$(gh issue view "$ISSUE_NUMBER" --json labels --jq '.labels[].name' 2>/dev/null || true)
if echo "$issue_labels" | grep -qx "blocked"; then
  if ! check_waiver "clarification-blocked"; then
    unmet+=("Issue has 'blocked' label — remove the label before advancing to clarification")
  fi
fi
if echo "$ISSUE_BODY" | grep -qE '^#{1,2}\s+Open Questions'; then
  oq_section=$(echo "$ISSUE_BODY" | sed -n '/^##\{0,1\} Open Questions/,/^##\{0,1\} [^O]/p' | tail -n +2)
  unresolved_items=$(echo "$oq_section" | grep -E '^\s*[-*]\s+' | grep -vE '(~~|DEFERRED-TO-DESIGN)' || true)
  if [ -n "$unresolved_items" ]; then
    if ! check_waiver "clarification-open-questions"; then
      unresolved_count=$(echo "$unresolved_items" | wc -l | tr -d ' ')
      unmet+=("$unresolved_count open question(s) are unresolved — strike through or mark DEFERRED-TO-DESIGN")
    fi
  fi
fi
