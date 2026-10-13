# 019: Restore Django migrations for YSE_App

- **Issue:** #19
- **Branch:** `19-restore-migrations`
- **Status:** Draft, awaiting approval

## Why

We need migrations to track model changes, and CLAUDE.md already requires a model change to ship with its migration. Right now that's impossible: there is no `YSE_App/migrations/` package.

History:
- `d1bf3a4` (2022-04-07, dockerization) squashed the 68 original YSE_PZ migrations into a new `0001_initial`.
- `b205a60` (2022-05) added `0002_hostspectrum_reference_transientspectrum_reference_and_more` (spectrum `reference` fields, and `data_quality` moved from FK to M2M on phot/spec data).
- `eeb710b` (2022-08) added `0003_surveyobservation_priority`.
- The dev seed `docker/db_init/YSE_django_migrations_insert.sql` (mounted as `5.sql`) only recorded `YSE_App 0001_initial`, so a fresh DB didn't match 0002/0003.
- `496f10f` (PR #5, 2026-07) worked around that. It hand-applied 0002/0003 into `YSE_Initial_Schema.sql`, deleted the migration files and the seed (and its compose mount), and commented out `migrate` in the entrypoint ("This project has no Django migrations").

Consequences today:
- A fresh dev DB has an **empty** `django_migrations` table. Running `migrate` would try to re-create every table (auth, admin, YSE_App, ...).
- Existing DBs that were migrated properly still carry the records. An existing DB Dave checked on 2026-10-13 records `YSE_App` 0001–0003 (0002/0003 applied 2023-11-16), plus every third-party app up to `auditlog 0009`. It should match the restored files exactly.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | Restore `YSE_App/migrations/` | `__init__.py`, `0001_initial.py`, `0002_...and_more.py` and `0003_surveyobservation_priority.py`, restored verbatim from `496f10f^`. The names must match the existing DB records, so no regeneration or re-squash. |
| 2 | Restore the `django_migrations` seed | `docker/db_init/YSE_django_migrations_insert.sql`, mounted again as `5.sql`. Contents: the full record set from the existing DB (Dave's list, ids 1–124: all apps, including `YSE_App` 0002/0003 and `auditlog` 0008/0009), so a fresh DB matches an existing one. |
| 3 | Verify models ↔ migrations ↔ SQL schema | See Verification. Any drift becomes a new `0004_*` migration, never another SQL hand-edit. |
| 4 | Entrypoint and docs | Replace the "no Django migrations" comment. Keep `migrate` **out** of the entrypoint (see Design notes). Add a "Migrations" section to `docker/README.md`: how to `makemigrations`, how to `migrate` locally, and that shared/live DBs are migrated by a human. |
| 5 | Prod check | Dave compares prod's `django_migrations` with the seed. If prod lacks 0002/0003 records but has the columns, run `migrate YSE_App 0003 --fake` (human only). Record the outcome in the Log. |

Out of scope: reconciling with upstream YSE_PZ's migration lineage (it was broken by the 2022 squash), any model change (#16 comes after this), dependency or image changes.

## Design notes

- **Restore, don't regenerate.** Django matches migrations by `(app, name)`. Existing DBs already record these three names, so restoring them verbatim makes those DBs consistent with no `--fake` needed. A fresh `makemigrations` would produce new names and force every DB to be faked.
- **The seed is the source of truth for fresh DBs.** `YSE_Initial_Schema.sql` builds the tables; the seed says which migrations they represent. The two must change together. After this, the rule is: schema changes go through migrations, and the SQL dumps get regenerated from a migrated DB rather than hand-edited.
- **Third-party rows depend on the image.** `auditlog`, `explorer`, `silk`, `django_cron` and `authtoken` records must match the package versions in the runtime image. `showmigrations` on a fresh DB catches any mismatch (an unapplied `[ ]` row). If a mismatch shows up, investigate it; don't upgrade a package to fix it (dependency guardrail).
- **No auto-migrate.** Running `migrate` on container start would apply migrations to whatever DB the container points at, including prod. CLAUDE.md says a human runs `migrate` against shared or live DBs, so it stays manual.
- **`data_quality` M2M.** 0002 changes `data_quality` from FK to M2M. `496f10f` dropped the FK columns and added `*_data_quality` through tables by hand. The schema diff below is what proves the hand-written tables match what Django would create (names, unique keys, charset).

## Acceptance criteria

- [ ] `YSE_App/migrations/` holds `__init__.py` and 0001–0003, identical to `496f10f^`.
- [ ] On a fresh DB volume, `showmigrations` shows every migration applied (`[X]`), with none pending.
- [ ] `makemigrations --check --dry-run` reports "No changes detected" (or a reviewed `0004` is added).
- [ ] The schema built by `migrate` on an empty DB matches the SQL-seeded schema for `YSE_App_*` tables (`mysqldump --no-data` diff), or the differences are explained in the Log.
- [ ] Dave's existing local DB shows no pending migrations.
- [ ] Prod's state is checked, and any `--fake` step is documented and run by Dave.
- [ ] No change to the Docker image, requirements files or dependencies.

## Verification

Local Claude or Dave, against the running stack (never prod):

```bash
cd docker
# 1. Fresh DB from SQL seeds (use a throwaway VOL_DB path; never delete the real one)
docker compose up -d
docker compose exec web python3 manage.py showmigrations      # all [X]
docker compose exec web python3 manage.py makemigrations --check --dry-run

# 2. Schema built by migrations vs. schema built by SQL
#    Create an empty scratch database, point a one-off settings override at it, run
#    `migrate`, then diff `mysqldump --no-data` of both, restricted to YSE_App_* tables.

# 3. Existing local DB
docker compose exec web python3 manage.py showmigrations YSE_App
```

## Open questions

1. Which DB was the record list from: the old local one or prod? We need both checked.
2. Is a one-off settings override for the scratch DB in step 2 acceptable, or would you rather compare a `mysqldump --no-data` from your existing local DB?

## Log

- **2026-10-13:** Issue #19 filed. Traced the removal to `496f10f` (PR #5). The existing DB Dave checked has `YSE_App` 0001–0003 recorded, so restoring the files verbatim should make it consistent with no `--fake`.
