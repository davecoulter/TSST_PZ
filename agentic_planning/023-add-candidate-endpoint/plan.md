# 023: `/add_candidate/` endpoint and payload contract

- **Issue:** #23 (part of #16)
- **Branch:** `23-add-candidate-endpoint`
- **Depends on:** #24 (data migrations: "Candidate" status, "Superseded" DataQuality, "diffpype" InformationSource and tag)
- **Status:** Draft, awaiting approval

## Why

diff_pype publishes JWST candidates on static websniff pages. We want each candidate in STZ-PZ, stored in the existing transient tables, so that repeat detections from later runs accumulate on one object. Every client (the Save button, the CLI, a notebook) should get the same matching and merge rule, so the logic lives in one server-side endpoint rather than in clients. `add_transient` is the wrong base for this: it matches by name first, overwrites fields, and silently maps unknown bands and instruments to "Unknown".

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | Payload contract | This plan's "Contract" section, refined during review. It moves to `agentic_planning/023-add-candidate-endpoint/contract.md` once agreed. |
| 2 | `add_candidate` view | New module `YSE_App/candidate_ingest.py` (keeps `data_utils.py` from growing). It's routed at `^add_candidate/` in `YSE_App/urls.py` and uses `@csrf_exempt` and `@login_or_basic_auth_required`, like `add_transient`. |
| 3 | Cross-match | Prefilter with `getRADecBox`, then compute true angular separation (astropy `SkyCoord`, already in the image). Pick the nearest within the radius. Radius comes from settings (`CANDIDATE_MATCH_RADIUS_ARCSEC`, default 0.3), overridable per request up to a cap. |
| 4 | Create or append | See "Merge rules". Runs inside `transaction.atomic()`. |
| 5 | Superseded photometry | Same transient, instrument, band and `obs_date` (to the second): add DQ "Superseded" to the old point, then insert the new one. |
| 6 | Hide superseded points | Light-curve plots (`view_utils.lightcurveplot_summary`, `_detail`, `_flux`) and the transient detail data skip points flagged "Superseded" only. Other DQ flags keep today's behavior. |
| 7 | Notebook example | `scripts/examples/add_candidate.ipynb` or a `.py`: builds a payload and POSTs it, with credentials from the environment. |
| 8 | Docs | Endpoint section in `docker/README.md` or `docs/` (decide in review). |

Out of scope:
- CLI bulk mode (#25), the Save button, CORS and login (#26), grid and detail views (#27), promotion (#28), TNS rename (#29).
- Updating ra/dec to a weighted mean across detections.
- Any dependency or image change.

## Contract (draft)

`POST /add_candidate/`, JSON body, HTTP basic auth (interim; tokens in #17).

```json
{
  "candidate_id": "jwst_5324_trig2_jw05324-o017_t014_nircam_clear_1",
  "ra": 189.21972548,
  "dec": 62.16717944,
  "permalink": "https://www.stsci.edu/~tsst/diffpype_test/jwst_5324_trig2/jw05324-o017_t014_nircam_clear/#jwst_5324_trig2_jw05324-o017_t014_nircam_clear_1",
  "source": "diffpype",
  "run_id": "jwst_5324_trig2",
  "telescope": "JWST",
  "instrument": "NIRCam",
  "obs_group": "JWST",
  "tags": ["COSMOS"],
  "match_radius_arcsec": 0.3,
  "host": {
    "name": "…", "ra": 189.2197, "dec": 62.1672,
    "photo_z": 0.81, "photo_z_err": 0.05,
    "redshift": null, "redshift_err": null
  },
  "photometry": [
    {
      "band": "F200W",
      "obs_date": "2026-03-14T05:12:00Z",
      "flux": 52.1, "flux_err": 4.7, "flux_zero_point": 23.9,
      "mag": 27.10, "mag_err": 0.09,
      "forced": false, "diffim": true,
      "stamps": {
        "sci": "https://…/F200W_sci.png",
        "ref": "https://…/F200W_ref.png",
        "diff": "https://…/F200W_diff.png",
        "sci_fits": null, "ref_fits": null, "diff_fits": null
      }
    }
  ]
}
```

- **Required:** `candidate_id`, `ra`, `dec`, `permalink`, `instrument`, and at least one `photometry` entry with `band`, `obs_date` and `flux`/`flux_err` (or `mag`/`mag_err`).
- **Optional:** `host`, `tags`, `stamps`, `run_id`, `telescope`, `obs_group`, `match_radius_arcsec`.
- **Never accepted from the client:** `created_by`, `modified_by`, `status`, `name` (set server-side).
- **Response 201 (created) / 200 (appended):**
  ```json
  {"result": "created", "transient": "jwst_…_1", "url": "/transient_detail/jwst_..._1/",
   "match_separation_arcsec": null, "photometry_added": 4, "photometry_superseded": 0}
  ```
- **Errors:** 400 with a field list for an invalid payload or an unknown instrument; 401/403 for auth. Nothing is written on error (transaction rollback).

## Merge rules

- **No match:** create the `Transient` with `name = candidate_id`, `status = Candidate`, tags "diffpype" plus any payload `tags` (existing tags only), and `obs_group`. Set `Transient.postage_stamp_*` from the highest-S/N stamp set as the grid thumbnail.
- **Match:** never change `name`, `slug`, `ra`/`dec` or `status`. Add tags if missing. Fill `postage_stamp_*` only if empty.
- **Always:** add a `TransientWebResource` (source "diffpype", `information_text = candidate_id`, `resource_url = permalink`), skipped if that permalink is already recorded. This is the alias list.
- **Host:** if the transient has no host, create or reuse a `Host` (by name, else position) and link it. If it has one, fill only empty redshift fields.
- **Photometry:** one `TransientPhotometry` per transient, instrument and obs_group (reused). For each point, if a non-superseded point exists with the same band and `obs_date`, flag it "Superseded". Then create the new `TransientPhotData` and, if stamps are given, a `TransientDiffImage` (`postage_stamp_file` = sci, `_ref`, `_diff`, plus `_fits`).
- **Audit:** `created_by` / `modified_by` = the authenticated user, everywhere.

## Decisions (recommendation first; confirm in review)

1. **Match radius:** 0.3″ default, configurable. The CLI uses 0.2″; `add_transient`'s box (`size=0.00042` deg) is about ±0.76″.
2. **Unknown band** for a known instrument: create the `PhotometricBand` (follows the CLI's lazy creation). **Unknown instrument:** reject with 400, instead of `add_transient`'s silent "Unknown".
3. **Upper limits:** store forced flux and flux error, and let S/N decide (YSE convention). Mark `forced=true` for non-detections. Needs confirming against diff_pype's output.
4. **Same-epoch key:** band and `obs_date` to the second. If diff_pype re-reduces with slightly different timestamps, we may need a tolerance.
5. **Error emails:** none (unlike `add_transient`).

## Acceptance criteria

- [ ] Contract agreed and written to `contract.md`.
- [ ] POST of a new candidate returns 201 and creates the transient (status Candidate, tag diffpype), a web resource, photometry and diff images.
- [ ] POST of a different `candidate_id` within the radius returns 200 and appends (a new web resource and new photometry); name, slug and coordinates are unchanged.
- [ ] Re-posting a point with the same band and `obs_date` flags the old one "Superseded"; light-curve plots show only the new one.
- [ ] An invalid payload returns 400 and writes nothing.
- [ ] Audit fields are the authenticated user.
- [ ] `ruff check .` passes; no dependency or image change.

## Verification

Local Claude, against the local stack, after #24's migrations are applied:

```bash
export YSE_URL=http://localhost:8001 YSE_USER=... YSE_PW=...
python scripts/examples/add_candidate.py --payload sample.json            # 201 created
python scripts/examples/add_candidate.py --payload sample_run2.json       # 200 appended
python scripts/examples/add_candidate.py --payload sample_run2.json       # 200, photometry_superseded > 0
```

Then check the transient detail page and the light curve. Add integration tests in `tests/integration/` alongside `test_add_transient.py`.

## Open questions

1. A sample of diff_pype's per-candidate data (JSON or the page's embedded data) to pin down field names, upper limits and timestamps. Can Justin share one?
2. Final match radius.
3. Should payload `tags` that don't exist be created, or rejected (current CLI behavior: hard fail)?

## Log

- **2026-10-14:** Plan drafted. Design agreed with Dave in the project thread: candidates are transients with status "Candidate", matching is server-side, re-posted epochs are superseded via DataQuality, and aliases are web resources.
