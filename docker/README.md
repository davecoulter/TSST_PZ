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

## 5. Migrations

Model changes are tracked in `YSE_App/migrations/`. A fresh DB is built from the SQL scripts in `db_init/`, and `YSE_django_migrations_insert.sql` records which migrations that schema already includes. When the schema scripts change, that file has to change with them.

```bash
cd docker
docker compose exec web python3 manage.py showmigrations                  # what's applied
docker compose exec web python3 manage.py makemigrations YSE_App          # after a model change; commit the file
docker compose exec web python3 manage.py migrate                         # local dev DB only
```

Some migrations also add lookup rows (e.g. `0005_candidate_lookup_rows`: the "Candidate" status, the "Superseded" data-quality flag, and the "diffpype" information source). They're attributed to the first superuser. On a DB with no superuser they're skipped with a printed note; create the rows by hand, or create a superuser and re-run that migration's function.

A fresh DB built from `db_init/` therefore needs `migrate` run once after the seed: the candidate work lives in migrations 0004 to 0009 (the lookup rows above, host catalogs, tag kinds, the "Archived" status, NIRCam band wavelengths, and the `New` tag given to the candidates that already exist), not in the SQL scripts. If a migration fails partway, MySQL cannot roll back the schema changes it already made, so try a migration on a throwaway DB before a shared one.

The entrypoint does not run `migrate`. Shared and live DBs are migrated by a person, never automatically and never by Claude. Change the schema through migrations, not by hand-editing the `db_init/` SQL.

## 6. Tests

Two kinds, both run against the local stack:

```bash
# Unit tests (Django's runner). It builds a temporary database called test_YSE, runs the tests, and drops it.
cd docker
docker compose exec web python3 manage.py test YSE_App

# Integration tests: real HTTP against the running stack, in tests/integration/
pip install pytest requests
export YSE_URL=http://localhost:8001 YSE_USER=<an admin user> YSE_PW=<its password>
pytest tests/integration
```

The unit tests need the database user to be allowed to create the test database. If the runner stops with `Access denied for user 'dev'@'%' to database 'test_YSE'`, a MySQL admin (root, in Workbench) grants it once on your local DB (change the user name if yours differs):

```sql
GRANT ALL PRIVILEGES ON `test\_YSE`.* TO 'dev'@'%';
```

It gives access to the temporary test database only, and your real data is not touched. Do this on your local database only, never on a shared or production one: the proper home for the unit tests is CI (#53), which runs them on its own throwaway MySQL with a dedicated test user. The runner starts on an empty database, because importing the app no longer queries it (#22).

**Or use a separate local test account** instead of granting the app's user:
1. In Workbench, create an account (for example `local_test_account`).
   - Host: `%`. The tests connect from the web container, not from `localhost`.
   - Schema privileges: ALL on `test\_YSE`, entered without `.*`.
2. Point the tests at it with a settings file, `YSE_PZ/local_test_settings.py`. It is git-ignored, because it holds the account's password:

   ```python
   from YSE_PZ.settings import *  # noqa
   DATABASES['default'] = dict(DATABASES['default'], USER='local_test_account', PASSWORD='<its password>')  # noqa: F405
   ```
3. Run the tests with it:

   ```bash
   docker compose exec web python3 manage.py test YSE_App --settings=YSE_PZ.local_test_settings
   ```

## Changing dependencies

The runtime image is a brittle chain (see `web_image_history/`). Don't add or change dependencies as a side fix; see `CLAUDE.md`.
