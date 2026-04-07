# Gateway Contract

## Accepted events

- `projects_v2_item`
- `issue_comment`

## Kickoff project transition

The gateway dispatches kickoff automation only for:

- project `Status` transition `Backlog -> Ready`
- issue-backed project items
- configured repositories
- open issues without `do-not-automate`

## Operator comment commands

- `gpa:feedback <instructions>` dispatches `execution` with feedback context
- `gpa:approve` dispatches `merge`

## Trust outcomes

- `trusted`: dispatch immediately
- `record-only`: add `pending-review`, do not dispatch
- `denied`: drop the event

## Dedup and retry

- delivery-id dedup is enforced
- active-run dedup is enforced
- recent completion dedup window is enforced
- dispatch retries use exponential backoff: `1s`, `4s`, `16s`

## Closed-loop status sync

When `project_item_id` is available and app credentials are configured, the system updates project `Status` during stage handoff:

- most successful transitions set `In Progress`
- operator review wait states set `In Review`
- terminal closeout sets `Done`
