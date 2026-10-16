# Candidate pages and ingest: what was built (read this first)

A summary for anyone picking this up cold (Project Claude, a reviewer, a new developer). The detail is in the other files named below; this is the map. Written 2026-10-15.

## What it is
Candidates detected on JWST difference images (by Justin's pipeline, shown on static websniff pages) are posted to STZ-PZ, triaged here, and promoted to transients. The workflow and who owns each step: `agentic_planning/016-candidate-workflow/workflow.md`.

## Where to read
| File | What |
|---|---|
| `agentic_planning/016-candidate-workflow/workflow.md` | The workflow, separation of concerns, decisions on record |
| `agentic_planning/023-add-candidate-endpoint/contract.md` | The payload contract (v1.3) for `/add_candidate/` |
| `agentic_planning/027-candidate-pages/plan.md` | The plan (Parts 1 to 4) and a dated **Log** of every decision and finding |
| `agentic_planning/023-.../plan.md`, `024-...`, `025-...` | The endpoint, lookup-row migration and CLI plans |
| `docker/README.md` | Running the stack, migrations, the VS Code debugger |
| `scripts/README.md` | The ingest CLIs |
| `scripts/INSTALL_ingest_candidates_cli.md` | For someone posting candidates: install the CLI, set credentials, and the JSON payload in short (also for clients other than websniff) |

## Pieces (and the routes)
- **Endpoint** `POST /add_candidate/` (one object or a list; `?dry_run=1` runs everything and rolls back). Match by 0.2 arcsec, create or append, supersede repeated epochs, host by catalog and ID (the first host stays), notes and confidence as a comment, a FitsMap resource, candidate tags, `warnings` for anything ignored. Code: `YSE_App/candidate_ingest.py`.
- **CLI** `scripts/ingest_candidates_cli.py` (credentials from the environment or a prompt, no default password, always prints its target, `--dry-run`).
- **Candidates page** `/candidates/`, **candidate page** `/candidate/<slug>/`, **archive** `/archived/`, the main dashboard's **Needs review** grid. Code: `YSE_App/candidate_views.py`, `dashboard_sets.py`, templates `candidate_*.html`.
- Helpers: `/candidate_sed/<id>/` (SED), `/candidate_tag/<id>/` (add, create or remove a candidate tag), `/lightcurveplot_detail/<id>/?compact=1`.
- A site-wide CSRF header for jQuery requests in `base.html` (the old buttons were being refused with a 403).

## Schema and migrations (all applied from a seeded DB with `migrate`; the SQL seeds are not the source of truth for these)
0004 (state only) , 0005 (lookup rows: Candidate status, Superseded flag, diffpype source), 0006 (`HostCatalog`, `Host.catalog` and `catalog_object_id`, `TagKind`, `TransientTag.kind`), 0007 (tag kinds, the Archived status, NIRCam band wavelengths from the JWST docs), 0008 (the `New` tag on existing candidates). All tested forward, reversed and forward again on a throwaway fresh DB.

## Decisions worth knowing
Status is the lifecycle and tags are annotations; `New` is a call to action (not the absence of tags); candidates and transients are the same row seen two ways; limits are S/N below 3 (the JSON's `upper_limit` flag is read but not stored); hosts are one catalog per host for now; photometry rows have no groups, so every logged-in user sees them; the TESS and Thacher checks are off (#31); judgments are text (#35 for labels).

## Tests
`tests/integration/` (run against the local stack; `pytest.ini` has the marker): `test_add_candidate.py`, `test_candidate_payload_v13.py`, `test_candidate_pages.py`, `test_candidate_grids.py`, `test_dashboard_grids.py`, `test_ingest_candidates_cli.py`. They need an admin user (the suite deletes what it makes) and `YSE_URL`, `YSE_USER`, `YSE_PW`.

## Not done, tracked as issues
Real filter curves (#42), host catalog loader and overlapping catalogs (#43), probabilistic host association (#44), click a light-curve point to see its cutouts (#45), remove the assumed JADES default (#46), reference depth and SCI and REF magnitudes (#47), per-person labels (#35), promotion rules (#28), TNS (#29), the Save button, CORS and login (#26), security and TLS (#17). Open question for Justin: the field names he sends for the host are agreed except `host_catalog` (the catalog file name), which he has not added yet (STZ-PZ assumes JADES and warns).

## Before deploying
`migrate` (0004 to 0008) and restart; check whether any prod transient already has status `Candidate` (the main dashboard now hides those); delete prod's hand-made `Candidate` tag if it is still wanted gone; `showmigrations` after.
