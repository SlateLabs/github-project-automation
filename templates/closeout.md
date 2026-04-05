<!-- gpa:owned-artifact:closeout:{{repo}}#{{issue_number}} -->

## Closeout

> **Source issue:** {{repo}}#{{issue_number}}
> **Issue title:** {{issue_title}}
> **Closed by:** orchestration automation (run key: `{{run_key}}`)

---

### Delivery summary

<!-- Summarize what was delivered. Link to the merged PR(s). -->

| Field | Value |
|-------|-------|
| **Merged PRs** | {{merged_pr_list}} |
| **Follow-ups captured** | {{follow_up_count}} |

### What went well

<!-- List things that worked effectively during this issue's lifecycle. -->

- _To be filled in during retrospective_

### What could improve

<!-- List friction points, surprises, or process gaps encountered. -->

- _To be filled in during retrospective_

### Follow-up status

<!-- Summary of deferred work captured during execution. -->

{{follow_up_summary}}

## Deferred Work

<!-- List any work that was explicitly deferred during this issue's lifecycle.
     Use "None identified." if nothing was deferred. -->

None identified.

## Process Improvement

<!-- List at least one process improvement observation and disposition it.
     Use one of these labels: adopt, backlog, reject.

     adopt  — start doing this going forward
     backlog — worth doing but not urgent; create a follow-up issue
     reject  — considered but not worth changing

     Example format:
     - **adopt**: Gate checks should run in the standalone workflow, not just orchestration
     - **backlog**: Follow-up marker validation could be stricter (#XX)
     - **reject**: Splitting closeout into two stages adds overhead without clear benefit
-->

- **backlog**: Auto-populate more of the closeout retrospective from durable orchestration artifacts so fully autonomous runs do not stop on placeholder-only retrospective sections.

### Exit checklist

- [ ] All acceptance criteria from the implementation plan are met
- [ ] Merged PR(s) passed CI and review
- [ ] Follow-up items captured and triaged
- [ ] No open branches remain for this issue
- [ ] Documentation updated if required
- [ ] Process improvement items dispositioned above
- [ ] Issue is ready to close
