# 023: `/add_candidate/` endpoint and payload contract

- **Issue:** #23 (part of #16)
- **Branch:** `23-add-candidate-endpoint`
- **Depends on:** #24 (data migrations: "Candidate" status, "Superseded" DataQuality, "diffpype" InformationSource, "Candidate" tag)
- **Status:** Draft, awaiting approval

## Why

diff_pype publishes JWST candidates on static websniff pages. We want each candidate in STZ-PZ, stored in the existing transient tables, so that repeat detections from later runs accumulate on one object. Every client (the Save button, the CLI, a notebook) should get the same matching and merge rule, so the logic lives in one server-side endpoint rather than in clients. `add_transient` is the wrong base for this: it matches by name first, overwrites fields, and silently maps unknown bands and instruments to "Unknown".

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | Payload contract | `contract.md` and `add_candidate_example.json` in this folder; v1.0, frozen. |
| 2 | `add_candidate` view | New module `YSE_App/candidate_ingest.py` (keeps `data_utils.py` from growing). It's routed at `^add_candidate/` in `YSE_App/urls.py` and uses `@csrf_exempt` and `@login_or_basic_auth_required`, like `add_transient`. |
| 3 | Cross-match | Shared helper (e.g. `YSE_App/common/utilities.py: find_transient_near(ra, dec, radius_arcsec)`): prefilter with `getRADecBox`, then compute true angular separation (astropy, already in the image) and return the nearest within the radius. The radius comes from settings, `TRANSIENT_MATCH_RADIUS_ARCSEC = 0.2` (decided by Dave 2026-10-14). |
| 3b | `add_transient` uses the same match | Replace its ±0.76″ box (`size=0.00042`) with the shared helper at 0.2″. Keep its name-first lookup and its ±1-year `disc_date` condition. **Behavior change** for every `add_transient` client (CLI, other ingests): objects 0.2–0.76″ apart that used to merge will now stay separate. |
| 4 | Create or append | See "Merge rules". Runs inside `transaction.atomic()`. |
| 5 | Superseded photometry | Same transient, instrument, band and `obs_date` (to the second): add DQ "Superseded" to the old point, then insert the new one. |
| 6 | Hide superseded points | Light-curve plots (`view_utils.lightcurveplot_summary`, `_detail`, `_flux`) and the transient detail data skip points flagged "Superseded" only. Other DQ flags keep today's behavior. |
| 6b | Keep candidates off the main dashboard | `views.dashboard()` draws one box per tag. Skip the "Candidate" tag's box and exclude status "Candidate" from every other box, so the first ingested candidate doesn't show up there (Dave, 2026-10-14). Candidate-specific dashboard and detail pages are #27. |
| 7 | Notebook example | `scripts/examples/add_candidate.ipynb` or a `.py`: builds a payload and POSTs it, with credentials from the environment. |
| 8 | Docs | Endpoint section in `docker/README.md` or `docs/` (decide in review). |

Out of scope:
- CLI bulk mode (#25), the Save button, CORS and login (#26), grid and detail views (#27), promotion (#28), TNS rename (#29).
- Updating ra/dec to a weighted mean across detections.
- Any dependency or image change.

## Contract

**v1.0 (frozen 2026-10-14)** in [`contract.md`](contract.md), with a full example in [`add_candidate_example.json`](add_candidate_example.json) (the real candidate `jwst_5324_trig2_jw05324-o017_t014_nircam_clear_1`). Dave decided to treat it as the contract, so both sides can build in parallel. Key points:
- Times are `mjd` (converted server-side to `obs_date`).
- Flux is in µJy with zero point 23.9.
- Non-detections send `upper_limit: true`, the limiting `mag` and `limit_sigma`.
- Per-point `stamps` (PNG URLs) and `fits` (paths) are optional.
- `created_by`, `status` and `name` are never accepted from the client.

## Merge rules

- **No match:** create the `Transient` with `name = candidate_id`, `status = Candidate`, tag "Candidate" plus any payload `tags` (existing tags only), and `obs_group`. Set `Transient.postage_stamp_*` from the highest-S/N stamp set as the grid thumbnail.
- **Match:** never change `name`, `slug`, `ra`/`dec` or `status`. Add tags if missing. Fill `postage_stamp_*` only if empty.
- **Always:** add a `TransientWebResource` (source "diffpype", `information_text = candidate_id`, `resource_url = permalink`), skipped if that permalink is already recorded. This is the alias list.
- **Host:** if the transient has no host, create or reuse a `Host` (by name, else position) and link it. If it has one, fill only empty redshift fields.
- **Photometry:** one `TransientPhotometry` per transient, instrument and obs_group (reused). For each point, if a non-superseded point exists with the same band and `obs_date`, flag it "Superseded". Then create the new `TransientPhotData` and, if stamps are given, a `TransientDiffImage` (`postage_stamp_file` = sci, `_ref`, `_diff`, plus `_fits`).
- **Audit:** `created_by` / `modified_by` = the authenticated user, everywhere.

## Decisions (recommendation first; confirm in review)

1. ~~Match radius~~ **Decided: 0.2″**, shared by `add_candidate` and `add_transient` (see 3b).
2. **Unknown band** for a known instrument: create the `PhotometricBand` (follows the CLI's lazy creation). **Unknown instrument:** reject with 400, instead of `add_transient`'s silent "Unknown".
3. **Upper limits:** the contract sends `upper_limit`, the limiting `mag` and `limit_sigma`. There is no limit column, so store `flux`/`flux_err`, `mag` = the limit and `mag_err` = null. Check how the existing light-curve plots draw such points (#27 may need a tweak).
4. **Same-epoch key:** band and `mjd` within ~1 s. If diff_pype re-reduces with slightly different timestamps, we may need a tolerance.
5. **Error emails:** none (unlike `add_transient`).

## Acceptance criteria

- [x] Contract v1.0 frozen (`contract.md`).
- [ ] `add_transient` matches at 0.2″ through the shared helper; existing integration tests still pass.
- [ ] POST of a new candidate returns 201 and creates the transient (status Candidate, tag Candidate), a web resource, photometry and diff images.
- [ ] POST of a different `candidate_id` within the radius returns 200 and appends (a new web resource and new photometry); name, slug and coordinates are unchanged.
- [ ] Re-posting a point with the same band and `obs_date` flags the old one "Superseded"; light-curve plots show only the new one.
- [ ] An invalid payload returns 400 and writes nothing.
- [ ] Audit fields are the authenticated user.
- [ ] The main dashboard shows no candidates (no "Candidate" box; candidates excluded from field boxes).
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

1. ~~A sample of diff_pype's data~~ Not needed: the contract is v1.0 and diff_pype builds to it.
2. ~~Final match radius~~ 0.2″.
3. Should payload `tags` that don't exist be created, or rejected (current CLI behavior: hard fail)?

## Log

- **2026-10-14:** Plan drafted. Design agreed with Dave in the project thread: candidates are transients with status "Candidate", matching is server-side, re-posted epochs are superseded via DataQuality, and aliases are web resources.
- **2026-10-14:** Dave set the match radius to 0.2″ and asked that `add_transient` use the same rule (added as 3b). Contract v0.1 written (`contract.md`, `add_candidate_example.json`) for Dave to share with Justin. Dave created the "Candidate" tag by hand on his local DB; #24's `get_or_create` migrations make fresh installs match.
- **2026-10-14:** The automatic tag is "Candidate" (Dave), not "diffpype". Provenance stays with the permalink's `InformationSource` "diffpype". Status "Candidate" is kept as well, so candidates stay out of the "New" queue until promoted.
- **2026-10-14:** Dave wants candidates off the main dashboard entirely, with their own dashboard and detail pages (#27). The exclusion is added here (6b), so it ships with the first candidate.
- **2026-10-14:** Dave froze the JSON as contract v1.0 so STZ-PZ and diff_pype can be built in parallel. #28 (promotion scan) is future work, not part of this sequence.
