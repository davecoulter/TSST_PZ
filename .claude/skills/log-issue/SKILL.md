---
name: log-issue
description: File a GitHub issue (bug, enhancement, or tech-debt) for TSST_PZ without touching the working tree. Use when asked to log something as a bug, feature request, or tech debt.
---

# Log a GitHub issue

1. Pick the label: `bug`, `enhancement`, or `tech-debt`. If it's ambiguous, ask. Don't invent new labels without asking.
2. Draft:
   - **Title:** imperative, at most 70 characters.
   - **Body**, with these sections:
     - **What:** the problem or idea, with `file:line` references where relevant.
     - **Acceptance criteria:** what "done" looks like.
     - **Source:** how and when it surfaced (e.g. "found while working on #10").
3. Show the title, body and label to the human, and wait for confirmation. Never file silently.
4. On confirmation, run `gh issue create --title "..." --body "..." --label <label>`. If the label doesn't exist yet, ask before creating it with `gh label create`.
5. Report the issue number and URL.

Constraints:
- No branch, commit, or PR.
- `gh issue create` is pre-authorized for this skill only.
