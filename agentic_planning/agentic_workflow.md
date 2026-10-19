# Agentic workflow log

Lessons about *how* we work with Claude, captured when they click. The ones that prove durable get promoted into `CLAUDE.md` rules or `.claude/skills/`.

## 2026-10-13: Setup (#10)

- **The repo is the shared brain.** Project Claude (cloud), Local Claude (VS Code), and humans don't share memory. Plans, issues, PRs, and `CLAUDE.md` carry all the context, so anyone can pick up a branch cold.
- **Pick the executor by whether the work needs your machine.** Config, refactors, and logic that can be checked by reading go to Project Claude, which pushes a branch. Anything that needs the running Docker stack, the real DB, or the live UI goes to Local Claude.
- **One writer per branch at a time.** The handoff is `git push` → `git pull`.
- **Plan → Claude builds → review together.** This keeps the human doing the critical thinking while still moving fast. Every decision is explicit, and progress can be recovered.
- **Keep three homes separate:**
  - `docs/` is the published user docs (RTD).
  - `.claude/` is tool config that Claude reads.
  - `agentic_planning/` is the team's planning record.

  This follows the spec-driven pattern (ADRs/RFCs, GitHub Spec Kit, Kiro).
- **Baseline legacy lint, don't fix it on the side.** The first lint run found 42 latent bugs (undefined names, Python 2 syntax). We baseline them in `ruff.toml` so CI starts green, and only new violations fail. The baseline is a visible to-do list that should only shrink.

## 2026-10-19: Lessons from the first deploy and #29

- **Test through the same door the clients use.** A new field passed every check that went through the model and the admin, but a PATCH through the API returned 200 and wrote nothing: the serializer's hand-written `update()` copies fields one by one and had not been given `iau_name`. `fields = "__all__"` makes a field appear in responses, not get written. The same gap was then found in two serializers from earlier work (#54). This is now the "API parity" rule in `CLAUDE.md`; generating those methods is #55.
- **Rehearse on a restored copy of prod.** Restoring the verified dump into a throwaway MySQL and running the migrations (and a delete script) against it showed what the real data looked like (a stray `Candidate` tag, the migration state, the exact foreign keys) before anyone touched prod. A check of the dump itself also caught a query of mine that assumed a column the dump predates.
- **Diff the server against what the pull brings.** Before the first deploy, comparing prod's old commit with `master` found local hand edits that would have blocked `git pull`, a renamed compose project (so the old stack had to come down first) and a changed default port. Hand edits on a server are debt (#51).
- **When a destructive step is wanted, show the script and the numbers.** Counts first, in a transaction, with an explicit `COMMIT` or `ROLLBACK`. The human runs it.
