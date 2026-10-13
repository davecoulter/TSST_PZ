# Running TSST_PZ locally (Docker)

The stack is three containers under the compose project `tsstpz`: `web` (Django), `yse_db` (MySQL) and `yse_nginx` (serves the app on port 80 plus `/static/`).

## 1. Configure `docker/.env`

`docker/.env` is git-ignored. Copy `public.env` to `.env` and edit the values:

| Variable | Meaning |
|---|---|
| `VOL` | Repo root, mounted at `/app` in the web container |
| `VOL_DB` | Host folder for MySQL data (it persists across container restarts) |
| `VOL_DB_LOG`, `VOL_GHOST` | Host folders for DB logs and ghost logs |
| `STATIC_VOL` | `YSE_PZ/static/`, served by nginx at `/static/` |
| `DB_PWD` | MySQL `root` password |
| `LOCAL_HTTP_PORT` | Host port for nginx (default 80) |
| `LOCAL_WEB_PORT` | Host port for Django directly (default 8001) |
| `LOCAL_DB_PORT` | Host port for MySQL (default 53306) |
| `LOCAL_DEBUG_PORT` | Host port for the debugger (default 5678) |

Pick ports that don't collide with other projects on your machine.

If the data folders live on an external volume, mount it before starting the stack.

## 2. Start the stack

```bash
cd docker
docker compose up -d
docker compose exec web python3 manage.py collectstatic --noinput   # once; the entrypoint doesn't run it
```

Open http://localhost/ (or your `LOCAL_HTTP_PORT`). The web image is `linux/amd64`, so on Apple silicon it runs emulated.

Stop with `docker compose stop`. Never use `down -v` unless you mean to delete data.

The database initializes from `docker/db_init/*.sql` only when `VOL_DB` is empty.

## 3. Look at the database

Connect any MySQL client to `127.0.0.1:<LOCAL_DB_PORT>` as `root` with `DB_PWD`. The schema is `YSE`. The init scripts also create `dev` (full access to `YSE`) and `dev_explorer` (read-only), with passwords in `db_init/YSE_create_users.sql`.

## 4. Debug from VS Code

Install the VS Code **Python Debugger** and **Docker** extensions. Then:

```bash
cd docker
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d web
```

This restarts `web` under `debugpy` (Django's `runserver --noreload`). The first start installs `debugpy` into `.debugpy/` (git-ignored) from PyPI, so it needs network access once. The image is not modified.

In VS Code, run **Attach to web (debugpy)** from Run and Debug, set a breakpoint in a view, and load the page. Switch back to the normal server with a plain `docker compose up -d web`.

Notes:
- The debug server runs a single process, so nothing else in the app is parallel while debugging.
- The DB container keeps running when you detach, and its data persists.

## Changing dependencies

The runtime image is a brittle chain (see `web_image_history/`). Don't add or change dependencies as a side fix; see `CLAUDE.md`.
