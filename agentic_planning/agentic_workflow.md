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

## 2026-11-12: Lessons from #52 (TNS reporting), #70 (Aladin) and the v0.4.1 deploy

- **Mocks prove our code; only the real service proves the contract.** Each sandbox run taught something no mock could: TNS answers a refused report with HTTP 400 *and* the per-entry feedback in its body; it accepts discovery dates in the future (it named one 2028A); it checks bot/group membership per entry; its rate limit is 30 requests a minute per bot. Each became a recorded reply and a test. A fake TNS server was dropped (#52 amendment 30) because it would only encode our assumptions.
- **When a vendored library surprises you, read the library.** Aladin v3's documentation didn't say that it reports usage to CDS with the page's URL, looks up a built-in list of favourite surveys by name, or falls back to its default survey forever when the survey you gave it fails. Its source did, and each became a one-line option or a guard around it.
- **Check in before each chunk, even when the plan covers it.** The human decides the model, the effort and the scope at each boundary; "answering a question" is not permission to build the next thing.
- **Humans merge.** Claude pushes and opens the PR; the human does a last check of the committed files and merges.
- **Closing keywords mean what they say.** A PR body's deploy note, "Fix #70 (Aladin) first", closed #70 on merge. Only the issue a PR closes may follow `fix`, `close` or `resolve`; scan the body before opening the PR.
- **Before every deploy, look for hand edits on the server and read production's real migration state.** A hand edit to `settings.py` (the CSRF origin) would have blocked the pull, and dropping it would have broken login; it became a hotfix and a patch release (v0.4.1). The dump's `django_migrations` showed production at 0008, not 0009.
- **Deploy order: pull, migrate, collect static, restart.** The running server keeps the old code until it restarts, so with additive migrations the site stays up throughout. Bringing the stack down before the pull opens a window of new code on old tables.
- **Check that a config file parses before restarting on it.** Loading the settings in a separate process (`python -c "... django.setup() ..."`) showed the TNS target and which bots had keys, without printing a key, before the restart could take the site down.
