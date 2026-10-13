# 010: Claude co-development workflow setup

- **Issue:** #10
- **Branch:** `10-claude-setup`
- **Status:** Implemented, in review

## Why

TSST_PZ (colloquially STZ-PZ) is a TSST customization of YSE_PZ that we're now co-developing with Claude. Before any feature work, we need shared rules of the road that every session (Claude in VS Code, Claude in the cloud project, and eventually other devs) reads from the repo. Sessions don't share memory, so the repo is the shared brain.

This is deliberately lightweight. Unit tests, coverage gates, docs builds and linting the legacy code are out of scope. They become `tech-debt` issues to work through later.

## Working posture (how we work, not just what we build)

This is the loop from diffpype:

1. **Plan together.** Each unit of work gets a folder `agentic_planning/<issue#>-<slug>/` with a `plan.md` with its scope and acceptance criteria. It's committed on the feature branch, and Dave approves it before any code is written.
2. **Claude writes the code** against the approved doc.
3. **Review together.** Claude explains the non-obvious choices, and maps newer concepts back to familiar ones where useful. Dave decides.
4. **Log what we learn.** Decisions and bugs go in the doc's `## Log` section. Workflow lessons ("aha" moments) go in `agentic_planning/agentic_workflow.md`.

Dave's goals, which shape how Claude explains things:
- Learn agentic engineering well, and formalize good ideas into workflows.
- Refresh DevOps and modern language and tooling knowledge, mapped from a 2010–2020 baseline.
- Grow into leading a small team that co-works with Claude.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | `CLAUDE.md` | One screen of team rules. See the contents below. |
| 2 | `.claude/settings.json` | Shared permission allow/ask/deny lists. |
| 3 | `.claude/skills/log-issue/SKILL.md` | `/log-issue`: draft, confirm, then `gh issue create`. Labels: `bug`, `enhancement`, `tech-debt`. |
| 4 | `.claude/skills/gen-pr/SKILL.md` | `/gen-pr`: draft commit message, PR title and body from the branch diff, filling `.github/pull_request_template.md`. |
| 5 | `agentic_planning/README.md` | How we work, the folder convention (`<zero-padded issue#>-<slug>/plan.md`, matching the branch), and a short plan template. |
| 6 | `agentic_planning/agentic_workflow.md` | Running log of workflow lessons. Seeded with this setup's decisions. |
| 7 | `.gitignore` additions | `collab_scratch/`, `.claude/settings.local.json`, `CLAUDE.local.md` |
| 8 | `.github/workflows/ci.yml` + `ruff.toml` | Minimal PR check, with the legacy violations baselined. See CI below. |
| 9 | Fix `.github/workflows/check_docker_build.yml` | Point it at `master` instead of the nonexistent `develop`. Keep the path filter. |

Out of scope: branch protection (a GitHub setting that Dave flips after merge), unit tests, Sphinx/RTD changes, reformatting or linting existing code, and the stray bower deletions seen locally (a separate `tech-debt` issue if we want to prune).

### `CLAUDE.md` contents

- What the project is, the stack (Django, MySQL, Docker), and where things live (`YSE_App/`, `YSE_PZ/settings.py`, `docker/`, `scripts/`, `tests/integration/`).
- **Git:** GitHub flow. Use an issue, then branch `<issue#>-<slug>` from `master`, then a PR to `master`. Never commit directly to `master`. Create the workplan doc on the branch, never on `master`.
- **Human in the loop:**
  - For anything beyond a trivial fix, Claude implements only against an approved workplan doc.
  - Bugs found mid-work are proposed in chat before they're fixed.
  - Edits to `CLAUDE.md` or `.claude/**` are proposed first, unless Dave dictated the exact change.
- **Model/effort check-in:**
  - Before starting implementation of a workplan doc, Claude recommends a model and an effort level (low/medium/high/xhigh/max), gives a one-line rationale for each, and waits for Dave's OK.
  - When the work is done, Claude reminds Dave to switch back to the default model and effort.
  - This is a lighter version of diffpype's Model Evaluation Phase.
- **Explain as we go:** for non-obvious choices, Claude says why. Claude names newer language, tool and DevOps features when it uses them.
- **Django:**
  - A model change ships with its migration (`makemigrations`) in the same PR.
  - Claude reminds Dave to `migrate`, and never runs it against a shared or live DB.
  - Never touch DB volumes without asking.
- **Tech debt** gets filed as an issue via `/log-issue`, not fixed on the side.
- **Scratch:** `collab_scratch/` is git-ignored and free for handoff files.
- **Personal preferences** go in `CLAUDE.local.md` (git-ignored), not here.

### `.claude/settings.json` permissions

- **allow:**
  - `git status`, `git diff`, `git log`, `git branch`, `git switch`, `git add`, `git commit`
  - `docker compose ps`, `docker compose logs`, `docker compose build`, `docker compose up`, `docker compose restart`
  - `python -m pytest`
  - `python manage.py check`, `python manage.py makemigrations`, `python manage.py showmigrations`
  - `gh issue view`, `gh pr view`
- **ask:**
  - `git push`
  - `docker compose down`
  - `python manage.py migrate`
  - `gh issue create`, `gh pr create`
- **deny:**
  - `git push --force*`, any push to `master`
  - `docker compose down -v`
  - `rm -rf` outside `collab_scratch/`

### CI (`ci.yml`)

Triggers: `pull_request` to `master`, and `push` to `master`.

One job, `ruff (bugs only)`, which runs `astral-sh/ruff-action` (ruff pinned to 0.16.8) with the config in `ruff.toml`:
- Rules `E9, F63, F7, F82`: syntax errors, undefined names, invalid `print >>`. No style rules.
- `target-version = "py38"`, so CI doesn't need the legacy image's Python. Ruff is a standalone binary.
- Excludes the vendored `bower_components/` and the unreferenced Python 2 file `YSE_App/common/getGWevents.py`.
- Baselines 16 files with pre-existing violations under `per-file-ignores`. This list should only shrink.
- `compileall` was dropped. Ruff's `E9` already catches syntax errors, and it does so against the target version instead of the runner's Python.

Stretch goal, only if it's cheap: run `manage.py check` and `makemigrations --check --dry-run` inside the existing `ghcr.io/davecoulter/yse_pz` image. Settings need a DB config at import time, so if this needs real setup, defer it to a `tech-debt` issue rather than bloating this PR.

## Acceptance criteria

- [ ] All files in the Scope table exist on `10-claude-setup`, and `CLAUDE.md` fits on roughly one screen.
- [ ] Opening the repo in Claude Code (VS Code) loads `CLAUDE.md`, and `/log-issue` and `/gen-pr` show up as skills.
- [ ] A read-only command (e.g. `git status`) runs without a prompt, and `git push` prompts.
- [ ] The `ci.yml` check runs on this PR and passes on the current code.
- [ ] `check_docker_build.yml` targets `master`.
- [ ] `git diff master --stat` shows only the files listed in Scope.
- [ ] Dave has reviewed each file in the PR, and any open questions are resolved in the Log below.

## Verification

```bash
git switch 10-claude-setup && git pull
git diff master --stat                         # only scoped files
pip install ruff && ruff check --select E9,F63,F7,F82 .
python -m compileall -q YSE_App YSE_PZ scripts
# then open VS Code → Claude Code: confirm CLAUDE.md is loaded and /log-issue, /gen-pr are listed
```

## Open questions for Dave

1. ~~Python version for CI.~~ It's legacy, defined in the ghcr image (3.8 per `docker/web_image_history/base`). This is solved by ruff's `target-version = "py38"`, so no runtime is needed.
2. ~~Hard fail or warning?~~ Hard fail.
3. ~~Other devs soon?~~ Yes: Shane Benlolo (@sbenlolo), with more later. `CLAUDE.md` is written for newcomers, and personal preferences go in `CLAUDE.local.md`.
4. ~~One `tech-debt` issue for the baseline?~~ Yes: filed as #12.

## Log

- **2026-10-13:** Drafted the workplan from the setup plan agreed in the project thread. Dave chose this posture: plan in a doc, Claude drafts, review together.
- **2026-10-13:** Moved from `docs/workplans/` to `agentic_planning/010-claude-setup/plan.md`. `docs/` is the RTD Sphinx source, so it stays user docs only. The layout follows the spec-driven pattern (ADRs/RFCs, GitHub Spec Kit, Kiro): one numbered folder per feature, keyed to the issue and branch.
- **2026-10-13:** Added the model/effort check-in rule to the `CLAUDE.md` contents, at Dave's request.
- **2026-10-13:** Implemented the scope.
  - The first ruff run on `master` found 42 pre-existing violations in project code (48 including vendored `bower_components`), all latent bugs: undefined names (e.g. `transients_ra` in `get_YSE_PAs*.py`, `getIDfromName` in `uploadTransientData.py`), Python 2 `print >>` in `snana.py`, and Python 2 `raise X, msg` in `getGWevents.py`.
  - We baselined them rather than fixing them, per the tech-debt rule, so that CI starts green and only new violations fail.
  - The skill folders use hyphens (`log-issue`, `gen-pr`), matching their slash-command names.
- **2026-10-13:** Added a `CLAUDE.md` guardrail, dictated by Dave: every permission prompt comes with a 1–2 sentence synopsis of what the command does and why.
- **2026-10-13:** Filed #12 for the lint baseline. Added the `CLAUDE.md` section "Dependencies and the Docker image" (approved by Dave). The runtime image is a layered chain with hand-patched site-packages, so a dependency change always needs its own plan and a regression check.
