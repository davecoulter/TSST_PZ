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
- **Baseline legacy lint, don't fix it on the side.** The first lint run found 48 latent bugs (undefined names, Python 2 syntax). We baseline them in `ruff.toml` so CI starts green, and only new violations fail. The baseline is a visible to-do list that should only shrink.
