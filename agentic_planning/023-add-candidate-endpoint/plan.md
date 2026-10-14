# 023: `/add_candidate/` endpoint and payload contract

- **Issue:** #23 (part of #16)
- **Branch:** `23-add-candidate-endpoint`
- **Depends on:** #24 (data migrations: "Candidate" status, "Superseded" DataQuality, "diffpype" InformationSource, "Candidate" tag)
- **Status:** Verified on the local stack except the browser checks; ready for review

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
| 2b | Array form (contract v1.1) | `/add_candidate/` also accepts a JSON array: each candidate independent (own transaction), the reply lists per-item status and which failed (Dave, 2026-10-14). The web-sniff page packages an array and a driver script POSTs it. |
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
- [x] `add_transient` matches at 0.2″ through the shared helper; existing integration tests still pass. (9/9)
- [x] POST of a new candidate returns 201 and creates the transient (status Candidate, tag Candidate), a web resource, photometry and diff images.
- [x] POST of a different `candidate_id` within the radius returns 200 and appends (a new web resource and new photometry); name, slug and coordinates are unchanged.
- [ ] Re-posting a point with the same band and `obs_date` flags the old one "Superseded" (verified in the DB); light-curve plots show only the new one (browser check pending).
- [x] An invalid payload returns 400 and writes nothing.
- [x] Audit fields are the authenticated user.
- [ ] The main dashboard shows no candidates (no "Candidate" box; candidates excluded from field boxes). (Browser check: dashboard empty on the local DB; see Log.)
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
- **2026-10-14:** Plan approved by Dave (Opus, high effort). Implemented on this branch, with #24's branch merged in for migration 0005:
  - `YSE_App/candidate_ingest.py` (`add_candidate`, routed at `^add_candidate/`).
  - `find_nearest_within()` in `YSE_App/common/utilities.py` and `TRANSIENT_MATCH_RADIUS_ARCSEC = 0.2` in settings.
  - `add_transient` uses the shared match (3b). A side effect fixes a latent bug: its box query could match several transients, and `.update()` then rewrote all of them. Now only the nearest one is updated.
  - `view_utils.get_all_phot_for_transient` hides "Superseded" points. That covers the three light-curve plots, the detail page and RAPID; exports are unchanged.
  - `views.dashboard()` skips the Candidate tag's box and excludes status Candidate from the others (6b).
  - `scripts/examples/add_candidate.py` (stdlib client) and `tests/integration/test_add_candidate.py`.
- **2026-10-14:** Decisions made while building:
  - Aliases go in the existing `AlternateTransientNames` table (also used by `add_transient`), as well as one `TransientWebResource` per permalink.
  - A repeat of the same `candidate_id` (as name or alias) always appends, before any position check.
  - On a match to an existing non-candidate transient, its status and tags are kept, and the Candidate tag is not added.
  - Upper limits keep `flux`/`flux_err` (derived from the limiting mag if needed) with `mag` empty, because the existing plots draw a point with a mag as a detection.
  - Unknown payload `tags` are rejected (400), like the CLI.
  - Missing lookup rows (migration 0005 not applied) return 500 with a message.
  - Validation was exercised offline against the contract example and seven bad payloads. The example's max S/N comes out at 15.2, matching the websniff page. Nothing has run against a DB yet.
- **2026-10-14:** Merged master after #24 landed (PR #30). Following Local Claude's note on 0005, the endpoint's lookups (status, tag, obs group, DataQuality, InformationSource, mag system) and the dashboard's Candidate exclusion now match names ignoring case and surrounding whitespace, via `candidate_ingest.find_by_name()`, so they find the same rows 0005 reused. Instruments still match case-insensitively by name plus telescope. `ruff check .` passes.
- **2026-10-14:** Review (Local Claude) found no blocking issues. Decisions with Dave: (1) unexpected auth failure returns 403 before any write; (2) TESS and Thacher checks in the `Transient` post_save receiver are mothballed (`tag_TESS, tag_Thacher = False, False`, and the `else:` that also called `tess_obs` is now `elif tag_TESS:`), because `tess_obs()` makes an untimed live request to NASA HEASARC for every created transient and raises on non-200, which would hang or fail a POST on a network without internet (#31 tracks revisiting it); (3) a simultaneous POST race (two requests for the same new candidate before either commits) is accepted for one instance and human-rate use; (4) the "Superseded" filter in `view_utils` still matches the exact name, which is fine because 0005 creates it exactly.
- **2026-10-14:** Verified on Dave's local stack as an admin `test4`. The local DB predated the seed's JWST chain, so the example POST first returned 400 (`unknown instrument "NIRCam"`, as designed, nothing written); applied the seed's guarded JWST observatory/telescope/instrument block locally, and prod already has them. Then: example POST 201 (4 points), repeat 200 (4 superseded); every new row's `created_by`/`modified_by` is `test4`; status and tag `Candidate`; one web resource; thumbnail set. `test_add_candidate.py` 8/8 and `test_add_transient.py` 9/9 passed, with no leftover `ITEST_` rows.
- **2026-10-14:** Justin's `jwst_5324_trig7_candidates.json` (array of 2, NIRCam, 4 points each) validates against v1.0. Posted one object at a time: 201, 201; re-post: 200 and 4 superseded each; a copy under a new ID shifted 0.1″ appended to the first by position (`match_separation_arcsec` 0.1), kept its name and coordinates, and added one alias and its permalink. The two candidates are ~49″ apart and stayed separate.
- **2026-10-14:** Added the array form (contract v1.1) at Dave's request, as above: independent candidates, per-item results, at most 500, empty list is 400, a single object is unchanged. Three new tests (independence with a bad candidate in the middle, batch re-post supersedes, empty list); `test_add_candidate.py` 11/11. Justin's whole array in one POST returned 200 with `{"created": 0, "appended": 2, "failed": 0}` and 4 superseded each.
- **2026-10-14:** The main dashboard is empty on Dave's local DB, as designed: every transient there, including the old test rows SN0 and SN1 (tag `Justin`), has status `Candidate`, and the dashboard excludes status `Candidate`. **Before deploy, check prod:** any existing transient with status `Candidate` (the row exists on prod) would vanish from the main dashboard boxes.
