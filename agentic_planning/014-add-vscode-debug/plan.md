# 014: VS Code local run and debug setup

- **Issue:** #14
- **Branch:** `14-add-vscode-debug`
- **Status:** Done, in review

## Why

The old local workflow was a PyCharm Docker Compose interpreter, which lives in the git-ignored `.idea/` and isn't shared. There is no repo-supported way to run the stack and attach a debugger from VS Code. We want a documented, shareable setup that doesn't touch the brittle runtime image.

What PyCharm did, for reference: it used a "Remote Python 3.8.10 Docker Compose (web)" interpreter and a Django server run config (`runserver` on `0.0.0.0:8000`, `DJANGO_SETTINGS_MODULE=YSE_PZ.settings`), with PyCharm injecting its own debugger into the container.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | Compose isolation | `name: tsstpz` in `docker-compose.yml`; `LOCAL_WEB_PORT` for the web port; drop obsolete `version:`. Keeps this stack from colliding with other projects (e.g. diffpype). **Done.** |
| 2 | `docker/docker-compose.debug.yml` | Override for `web`: install `debugpy` into a mounted folder, then run `runserver 0.0.0.0:8000 --noreload` under `debugpy --listen 0.0.0.0:5678`. Publish 5678. DB and nginx unchanged. |
| 3 | `.vscode/launch.json` | Python attach config, `pathMappings` local repo root to `/app`. |
| 4 | `.gitignore` | Ignore the mounted debugpy folder (e.g. `.debugpy/`). `.vscode/` stays tracked. |
| 5 | `docker/README.md` | Replaces the stale `docker/readme.txt`. Setup steps: `docker/.env` (from `public.env`), `docker compose up -d`, one-time `collectstatic`, connecting a DB client (`root`, port 53306), starting the debug override and attaching VS Code. |

Out of scope: merging `docker/README.md` into the install guide under `docs/` (follow-up: update that guide or merge the two), baking `debugpy` into an image (possible follow-up on `requirements.web.dev` / `Dockerfile.web.dev`), changing the runtime image or any requirements file, automating `collectstatic`.

## Design notes

- **debugpy placement.** `pip install --target /app/.debugpy debugpy` runs at container start and is skipped if present. `/app` is the bind-mounted repo, so it persists on the host and later restarts reuse it. `PYTHONPATH` points at it. The image is untouched, which respects the dependency guardrail in `CLAUDE.md`.
- **Python 3.8.10.** The image has `python3` / `pip3` (3.8.10) and no `python` or conda, despite the conda variables in the compose file. Verified 2026-10-13: `pip3 install --target` of `debugpy` 1.8.21 imports fine on the image, run as `linux/amd64` under emulation (as compose does on Apple silicon). Pin `debugpy==1.8.21`. Use `python3` in the override's command.
- **Single process.** The debug override uses `runserver --noreload` instead of the default gunicorn (3 workers), because one process is what the debugger can follow.
- **DB persistence.** The DB data is a host bind mount (`VOL_DB`), so it survives container restarts. Start it alone with `docker compose up -d yse_db`.
- **Static files.** The entrypoint has `collectstatic` commented out. After a fresh setup, run `docker compose exec web python manage.py collectstatic --noinput`. `YSE_PZ/static/` is git-ignored, with 18 force-added tracked files; `collectstatic` did not modify any of them on the first run.
- **Ports.** Web `LOCAL_WEB_PORT` (8000), nginx `LOCAL_HTTP_PORT` (80), DB `LOCAL_DB_PORT` (53306), debugpy 5678.
- **Project rename.** Moving to `name: tsstpz` requires `docker compose -p docker down` once on a machine that ran the old stack, because the container names are fixed.

## Acceptance criteria

- [x] From a configured `docker/.env`, the stack runs under project `tsstpz` with no orphan warning and no port collisions with diffpype.
- [x] Starting with the debug override, attaching from VS Code hits a breakpoint in a view when a page loads.
- [x] The DB container stays up and its data persists after the debugger detaches.
- [x] No change to the Docker image, requirements files, or dependencies.
- [x] The setup steps are written down for new developers.

## Verification

```bash
cd docker
docker compose -p docker down                      # once, if the old stack is running
docker compose up -d                               # normal stack, project tsstpz
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d web
# VS Code: Run and Debug -> "Attach to web (debugpy)", set a breakpoint, load the page
```

## Open questions

1. ~~Where do the docs live?~~ `docker/README.md`, replacing `readme.txt`. The install guide in `docs/` gets updated or merged later.
2. ~~Does `debugpy` install on Python 3.8.10?~~ Yes, 1.8.21, verified in a throwaway container.
3. ~~Network on first start?~~ Needs PyPI once; acceptable for local dev.

## Log

- **2026-10-13:** Issue #14 filed. Verified the stack runs from the repo (DB healthy, app 200). Static assets 404'd because `collectstatic` is not run by the entrypoint; ran manually and it worked. Added compose isolation (project name, web port variable) so this stack doesn't collide with diffpype.
- **2026-10-13:** Web port default moved to 8001 (diffpype's API uses 8000). Verified `debugpy` 1.8.21 installs on the image's Python 3.8.10. Note: a `docker compose -p docker down` also removed two stopped diffpype containers that shared the old default project name; no data lost as far as known (bind-mounted DB).
- **2026-10-13:** Open questions resolved with Dave: docs go in `docker/README.md`; first-start PyPI access is fine. MySQL Workbench connects as `root` with `DB_PWD`; the `dev` and `dev_explorer` users have separate passwords from `YSE_create_users.sql`.
- **2026-10-13:** Implemented the debug override (`docker-compose.debug.yml` plus `entrypoints/docker-compose-debug-entrypoint.sh`), `.vscode/launch.json`, the `.debugpy/` ignore, and `docker/README.md` (replaces `readme.txt`). Tested: `debugpy` 1.8.21 installed on first start into the bind-mounted `.debugpy/`, port 5678 open, web (8001) and nginx (80) returned 200, and Dave attached from VS Code and hit a breakpoint in `YSE_App/views.py`.
- **2026-10-13:** Decided against a `tasks.json` / `preLaunchTask` to start the debug container on play. Dave is fine with the two-step flow (start with the override, then attach). Revisit if it gets tedious. Follow-up: update or merge the install guide in `docs/` with `docker/README.md`.
