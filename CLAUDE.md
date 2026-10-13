# CLAUDE.md: TSST_PZ (a.k.a. STZ-PZ)

Team rules for Claude and for the humans working with it. Personal preferences go in `CLAUDE.local.md` (git-ignored), not here.

## What this is
This is a TSST customization of [YSE_PZ](https://github.com/davecoulter/YSE_PZ), a Django transient-survey management app backed by MySQL and run in Docker.
- `YSE_App/` is the Django app: models, views, templates, API, and data-ingest utilities.
- `YSE_PZ/settings.py` holds the settings, which read DB config from the environment.
- `docker/` holds the compose files and image history. The runtime image is `ghcr.io/davecoulter/yse_pz` (legacy Python).
- `scripts/` holds CLI tools, e.g. `ingest_transients_cli.py`.
- `tests/integration/` holds live-service tests, which need a running deployment (`YSE_URL`).
- `docs/` is the Read the Docs (Sphinx) source. It holds user docs only.
- `agentic_planning/` holds the workplans and the workflow log. See its README.

## How we work
1. **Plan:** every non-trivial change starts as `agentic_planning/<NNN>-<slug>/plan.md`, with scope and acceptance criteria. It's committed on the feature branch.
2. **Approve:** don't write implementation code until a human approves the plan.
3. **Model/effort check-in:**
   - Before implementing a plan, recommend a model and an effort level (low/medium/high/xhigh/max), with a one-line reason for each, and wait for an OK.
   - Afterwards, remind the human to switch back to their defaults.
4. **Build, then review together:** explain the non-obvious choices. When you use a newer language, tool or DevOps feature, name it briefly.
5. **Log:** decisions and bugs go in the plan's `## Log`, as dated entries. Workflow lessons go in `agentic_planning/agentic_workflow.md`.

## Git (GitHub flow)
- Open an issue, branch `<issue#>-<slug>` from `master`, then open a PR to `master`. Never commit directly to `master`.
- Trivial doc/config fixes may skip the issue: use a `hotfix_<slug>` branch and a PR. Anything with a plan, a behavior change or a model change still gets an issue.
- Create the plan on the branch, never on `master`.
- Only one writer per branch at a time (a person, Local Claude, or Project Claude). Hand off with `git push` / `git pull`.
- PR bodies use `.github/pull_request_template.md` (`/gen-pr` drafts one).

## Guardrails
- **Every permission prompt gets context:** before any command that may prompt the human (push, migrate, `gh` writes, anything outside the allow list), say in 1–2 sentences what it does and why it's needed now. Also put that in the tool call's description, so it shows up in the prompt itself.
- **Bugs found mid-work:** propose the fix in chat (what's broken, the fix, which layer) and wait for confirmation before applying it.
- **Tech debt:** file it as a GitHub issue labeled `tech-debt` (`/log-issue`). Don't fix it on the side.
- **Django models:** a model change ships with its migration (`python manage.py makemigrations`) in the same PR. Remind the human to `migrate`. Never run `migrate` against a shared or live DB yourself.
- **Data:** never delete DB volumes or data directories (`docker compose down -v`, `rm -rf` on data) without explicit approval.
- **Secrets:** never commit `.env` files or credentials. `docker/.env` and `db_configuration/*.ini` are git-ignored for a reason.
- **Meta-config:**
  - Propose edits to this file or `.claude/**` in chat first, and wait for confirmation.
  - The exception is when the human dictated the exact change.

## Dependencies and the Docker image (handle with care)
- The runtime image is a bespoke, brittle chain. `docker/web_image_history/` has layered requirements files and hand-patched site-packages (`auditlog`, `el_pagination`, `django_cron`, `jsonfield`). Treat it as load-bearing.
- Never add, upgrade or remove a dependency, or touch the image chain, as a side fix. A dependency change needs its own issue and plan, a regression check against the running stack, and Dave's approval.
- If a bug looks like "just bump package X," stop and propose that instead of doing it.

## Checks
- CI (`.github/workflows/ci.yml`) runs `ruff check .` using `ruff.toml`. It catches syntax errors and undefined names only, against Python 3.8.
- Known legacy violations are baselined in `ruff.toml` under `per-file-ignores`. Shrink that list; never grow it to make CI pass.
- To run the check locally: `pip install ruff && ruff check .`

## Scratch
`collab_scratch/` is git-ignored handoff space. Create, edit and delete files there freely.
