# 024: Data migrations for the candidate flow

- **Issue:** #24 (part of #16; needed by #23)
- **Branch:** `24-candidate-data-migrations`
- **Status:** Approved; migration written, awaiting verification against the stack

## Why

The `/add_candidate/` endpoint (#23) relies on a few lookup rows that don't exist on every DB. The DB is the source of truth for these enums, so they have to exist on prod, on Dave's local DB and on any fresh install. A data migration is the "zero-day config": it reaches every DB through `migrate`, unlike the SQL seeds, which only run on an empty volume.

## Scope

One migration, `YSE_App/migrations/0005_candidate_lookup_rows.py` (`RunPython`), that ensures these rows exist:

| Model | Name | Used for |
|---|---|---|
| `TransientStatus` | Candidate | Keeps candidates out of the "New" queue until promoted (#28 changes the status). |
| `TransientTag` | Candidate | Added to every candidate by #23. Dave already created it by hand on his local DB. |
| `DataQuality` | Superseded | Marks a photometry point replaced by a re-post of the same band and MJD (#23). |
| `InformationSource` | diffpype | The source recorded on each candidate's permalink (`TransientWebResource`). |

Out of scope: any schema change, the endpoint itself (#23), and view changes (#27).

## Design notes

- **Idempotent.** It looks up each row by name, case-insensitively (`name__iexact`), and creates it only if missing. Dave's hand-made "Candidate" tag is reused, and re-running is a no-op. Names aren't unique in these tables, so the migration never touches existing rows.
- **Audit user.** `created_by`/`modified_by` are required (PROTECT). The migration uses the first superuser by id, the same rule the SQL seeds use (`YSE_rest_of_tables_insert.sql`, dashboard tags and JWST chain). If no superuser exists (only possible on a DB built purely from migrations, see #22), it skips with a printed note instead of failing. A later `migrate` won't re-run it, so the skip is documented in `docker/README.md`.
- **Historical models.** It uses `apps.get_model(...)` (migration-safe), not direct model imports.
- **Reverse.** A no-op: the rows stay. Deleting them could orphan transients, photometry flags or web resources that already point at them, and a no-op keeps `migrate YSE_App 0004` working.
- **Not in the SQL seeds.** A fresh install runs `migrate` after the seed (`docker/README.md`, "Migrations"), so duplicating these rows in `YSE_rest_of_tables_insert.sql` would add a second source of truth.
- **Dashboard.** The main dashboard draws one box per tag that has transients (`YSE_App/views.py`, `dashboard()`), so a "Candidate" box would appear once candidates exist. Dave wants candidates off the main dashboard, so #23 excludes them (plan 023, item 6b); #27 builds the candidate dashboard.

## Acceptance criteria

- [ ] `migrate` on Dave's local DB applies 0005 and reuses the existing "Candidate" tag (no duplicate).
- [ ] `migrate` on a fresh seeded DB applies 0004 and 0005 and creates all four rows.
- [ ] Running the migration body twice creates nothing new.
- [ ] `migrate YSE_App 0004` (reverse) succeeds and leaves the rows.
- [ ] `makemigrations YSE_App --check --dry-run` reports no changes.
- [ ] `ruff check .` passes; no dependency or image change.
- [ ] Prod: Dave runs `migrate` (applies 0004 and 0005) after merge.

## Verification

Local Claude, against the local stack:

```bash
cd docker
docker compose exec web python3 manage.py migrate YSE_App
docker compose exec web python3 manage.py shell -c "from YSE_App.models import *; \
  print(TransientStatus.objects.filter(name='Candidate').count(), \
        TransientTag.objects.filter(name__iexact='candidate').count(), \
        DataQuality.objects.filter(name='Superseded').count(), \
        InformationSource.objects.filter(name='diffpype').count())"   # expect 1 1 1 1
docker compose exec web python3 manage.py migrate YSE_App 0004 && \
docker compose exec web python3 manage.py migrate YSE_App               # reverse, then forward again
```

Repeat on a throwaway fresh DB (scratch `VOL_DB`), as in plan 019.

## Log

- **2026-10-14:** Plan drafted. The dashboard creates one box per tag (`views.dashboard()`), so the "Candidate" tag yields a candidate grid for free; noted for #27.
- **2026-10-14:** Dave agreed with idempotent creation and first-superuser attribution. Clarified that the reverse no-op leaves the rows, and that the rows live in the migration only, not the SQL seed.
- **2026-10-14:** Plan approved by Dave. Wrote `YSE_App/migrations/0005_candidate_lookup_rows.py` (RunPython, reverse no-op) and a note in `docker/README.md`. Not run against a DB yet; next, Local Claude runs the Verification steps.
