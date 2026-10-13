---
name: gen-pr
description: Draft a commit message, PR title, and PR body for the current TSST_PZ branch from its diff and plan. Use when asked to write up or prepare a PR.
---

# Generate PR text

Gather context:
- `git branch --show-current`. Stop if it's `master`.
- `git log master...HEAD --oneline`
- `git diff master...HEAD --stat`
- Read `agentic_planning/<NNN>-<slug>/plan.md` for this branch, if it exists. It carries the intent.
- Read `.github/pull_request_template.md`.

Produce:
1. **Commit message** for any uncommitted work:
   - Imperative mood. The first line is at most 50 characters.
   - An optional short "why" paragraph.
2. **PR title:** at most 70 characters, describing the user-visible change.
3. **PR body:**
   - Fill in `.github/pull_request_template.md`, keeping its headings, inside a fenced block so it can be copied raw.
   - Start with `Fixes #<issue>`, taking the issue number from the branch name.
   - Tick only the checklist boxes the diff supports.
   - In "Additional context", link the plan file.

Output text only. Don't push or run `gh pr create` unless asked explicitly.
