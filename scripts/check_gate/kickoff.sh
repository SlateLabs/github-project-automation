# Gate 1→2: Backlog triage
if ! echo "$ISSUE_BODY" | grep -qE '^#{1,2}\s+Summary'; then
  if ! check_waiver "kickoff"; then
    unmet+=("Issue body must contain a ## Summary heading")
  fi
fi
