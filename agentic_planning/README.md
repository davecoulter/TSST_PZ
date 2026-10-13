# agentic_planning/

This is where humans and Claude plan work before it's built. It's the team's engineering record: what we decided and why. It's not user docs (those live in `docs/`), and it's not tool config (that lives in `.claude/`).

## Layout

```
agentic_planning/
  README.md               ← this file: how we work + plan template
  agentic_workflow.md     ← running log of workflow lessons ("aha" moments)
  <NNN>-<slug>/           ← one folder per unit of work
    plan.md               ← scope, acceptance criteria, log
    …                     ← optional notes, diagrams, sample payloads
```

`<NNN>` is the GitHub issue number, zero-padded to 3 digits. `<slug>` matches the branch name. For example, issue #10 on branch `10-claude-setup` becomes `010-claude-setup/`.

## The loop

1. Open an issue. Create a branch `<issue#>-<slug>` from `master` and push it.
2. Write `plan.md` on that branch, together with Claude.
3. A human approves the plan. Claude gives its model/effort recommendation and waits for an OK.
4. Claude (or a human) implements against the plan on the same branch.
5. Review the PR together. Log decisions and bugs in the plan's `## Log`.
6. Merge. The plan stays as the record of what was built and why.

## Plan template

```markdown
# <NNN>: <Title>

- **Issue:** #<n>
- **Branch:** `<n>-<slug>`
- **Status:** Draft | Approved | In progress | Done

## Why
<the problem, in a few sentences>

## Scope
| # | Deliverable | Notes |
|---|---|---|

Out of scope: <what we're deliberately not doing>

## Design notes
<data model, API shape, tradeoffs considered>

## Acceptance criteria
- [ ] <observable, checkable outcome>

## Verification
<commands to run, pages to click>

## Open questions

## Log
- **YYYY-MM-DD:** <decision, bug, or change, and why>
```
