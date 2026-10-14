# 027: Candidate dashboard and candidate detail page

- **Issue:** #27 (part of #16)
- **Branch:** `27-candidate-pages`
- **Depends on:** #23 (merged, PR #32), #25 (merged, PR #33)
- **Status:** Draft (revised after Dave's review), awaiting approval

## Why

Candidates now arrive through `/add_candidate/` and the CLI, but there is nowhere to look at them. #23 keeps them off the main dashboard, and the regular detail page shows them badly:
- Its stamp code prefixes every stamp with the local static folder (`YSE_App/images/stamps/` + value), but candidate stamps are full websniff URLs, so the images break.
- Its "Forced Photometry and Difference Imaging" table shows "No Valid Pixels" for every candidate point, because `/add_candidate/` doesn't set `TransientDiffImage.valid_pixels`.
- It lists superseded points' stamps too (that table queries `TransientDiffImage` directly, not through `get_all_phot_for_transient`).
- Most of the page (follow-up, observing resources, spectra, TNS) doesn't apply to a candidate yet.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | **Candidate dashboard** at `/candidates/` (name `candidate_dashboard`) | A **thumbnail grid** of transients with **status** "Candidate", one card each: the DIFF stamp of the highest-S/N detection, name (links to the detail page), RA/Dec, discovery date, filters detected ≥3σ, max S/N, host z (spec-z, else photo-z), number of detections and number of runs. No obs group, spec class, last mag or last obs date (Dave). No status control here: promotion happens on the detail page. A small sort menu (newest first, max S/N, name) and paging (24 per page). |
| 2 | **Candidate data on the detail page** | The existing detail page stays as it is (status, tags, comments, follow-up all keep working) and gains a **Candidate data** section, shown whenever the transient has diff_pype data (permalinks with source "diffpype", or diff images). It shows everything the JSON import stored: **Runs:** each candidate ID (name and `AlternateTransientNames`) with its websniff permalink (`TransientWebResource`), opening in a new tab. **Image triplets:** every registered `TransientDiffImage`, one row per epoch and filter, with date, band, flux ± err, S/N (or "limit") and SCI/REF/DIFF, each image opening full size in a new tab, plus the FITS paths as text. Superseded points are hidden, with a "show superseded (N)" toggle. **Host:** photo-z ± err, spec-z ± err, source. The light curve is the existing plot, which already hides superseded points. |
| 3 | **Stamp URLs** | A template filter `stamp_src`: an absolute URL (`http(s)://` or `/`) is used as is, anything else gets the static path the page builds today. Used by the new section, and by the page's existing "Image Stamps" box and diff-image table, so candidate stamps stop showing as broken images there. Local stamp names render exactly as before. |
| 4 | **Navigation** | A "Candidates" sidebar link in `base.html` under Main Dashboard, with a count of current candidates. |
| 5 | **Promoted candidates stay visible** | The main dashboard draws one box per tag, and #23 skips the "Candidate" tag's box. A promoted candidate whose only tag is "Candidate" would then appear in no box at all. So the main dashboard shows the Candidate tag's box again; it lists only promoted ones, since status "Candidate" stays excluded everywhere on the main dashboard. See decision 2. |
| 6 | **Keep candidates out of other list views** | Audit the views that list transients by tag or status (`transient_summary`, `transient_tags`, `followup`). Where one lists by tag, exclude status Candidate, as the main dashboard does. Search keeps finding candidates. User-written personal dashboard queries are left alone. |

Out of scope:
- Promotion rules or a scheduled scan (#28) and TNS renaming (#29).
- The Save button, CORS and login (#26).
- Copying stamps into STZ-PZ (see "Images" below), and trimming the detail page down for candidates (later, iteratively).
- The detail page's `IndexError` on a bad slug (found in #23; separate tech-debt issue if wanted).
- Any model change, migration, dependency or image change. Everything uses existing tables.

## Design notes

- **Status is the switch.** Status "Candidate" decides what is on `/candidates/` and what is off the main pages. Promotion is a person changing the status on the detail page (for now), or #28 later. Manually setting a transient to "Candidate" moves it onto `/candidates/` and off the main dashboard, which is consistent.
- **Nothing is lost on promotion.** The candidate data lives in the regular tables (photometry, diff images, web resources, aliases, host), and changing the status touches none of it. Because it's shown on the regular detail page whenever it exists, a promoted candidate keeps its triplets and permalinks. A candidate that matched an existing regular transient already gets the same rows from #23 (it keeps that transient's status and tags), so its data shows there too.
- **Stats are computed when the page renders.** Max S/N, filters detected, detection and run counts and the best thumbnail come from the stored photometry (flux / flux_err, superseded points excluded) for the 24 cards on the page. Nothing new is stored, and there are no new columns.
- **Best thumbnail.** #23 already picks the highest flux/flux_err detection at ingest and stores its stamps in `Transient.postage_stamp_*`, but only on the first post, so a better later run doesn't replace it. The grid recomputes it from the photometry at render time instead, so it stays current, and falls back to the stored stamps. No flag from Justin's code is needed.
- **Images.** The page puts each websniff URL in an `<img>` tag, and the viewer's browser fetches the PNG straight from websniff. STZ-PZ never downloads or serves them, and no iframe is needed. So images show wherever websniff is reachable from the viewer's machine, as on the websniff page itself. Two cases would need us to copy the PNGs into STZ-PZ and serve them with nginx: websniff pages being cleaned up or moved (the links would break), or STZ-PZ moving to HTTPS (#17) while websniff stays HTTP (browsers block HTTP images on HTTPS pages). Neither is true yet; it would be a follow-up issue.
- **No new JavaScript.** The superseded toggle is a few lines of the jQuery already on the page.

## Decisions (recommendation first; confirm in review)

1. ~~Table vs grid~~ **Thumbnail grid** (Dave).
2. **The "Candidate" tag:** keep adding it on ingest as a permanent "came from the candidate pipeline" label, never used for filtering, and show its box on the main dashboard for promoted ones (item 5). The alternative is to stop adding the tag, so a person adds a real tag when promoting; until they do, the promoted transient appears in no main-dashboard box.
3. **One detail page** (item 2) rather than a separate candidate page: it follows Dave's "use the current detail page", keeps status and tag changes where they are, and keeps the candidate data visible after promotion. This replaces the earlier redirect and `?full=1` idea.

## Acceptance criteria

- [ ] `/candidates/` shows a card for every status-Candidate transient with the fields above, sorts and pages, and shows nothing that isn't a candidate.
- [ ] The detail page of a candidate shows its runs with working permalinks (new tab), every registered image triplet (superseded hidden, toggle works), FITS paths and host z; existing sections still work.
- [ ] Candidate stamps load in the existing "Image Stamps" box and diff-image table; a regular transient's stamps are unchanged.
- [ ] Changing the status to New on the detail page moves the candidate off `/candidates/` and onto the main dashboard, and its candidate data is still on its detail page.
- [ ] The main dashboard and the tag-based list views show no status-Candidate transients.
- [ ] Sidebar link and count work.
- [ ] `ruff check .` passes; no model, migration, dependency or image change.

## Verification

Local Claude, on Dave's local stack, after loading the pipeline's real file (`jwst_5324_trig7_candidates.json`) and a re-run with the CLI from #25:
- Open `/candidates/`: both candidates, stats match the data, sort and paging work.
- Open each candidate: permalinks open the websniff pages, all stamps load, the superseded toggle reveals the older stamps.
- Set one candidate to New: it leaves `/candidates/`, appears on the main dashboard, and its detail page still shows its candidate data.
- Open a regular transient: unchanged.
- Integration tests in `tests/integration/test_candidate_pages.py`: status codes for the pages, and that a non-candidate never appears on `/candidates/`.

## Log

- **2026-10-14:** Plan drafted after #23 and #25 merged. Surveyed `views.dashboard`, `transient_detail` and its template, `TransientTable` and `base.html`; found the stamp-URL, `valid_pixels` and superseded-stamps problems listed under "Why".
- **2026-10-14:** Reviewed with Dave. Dashboard: thumbnail grid; drop obs group, spec class, last mag and last obs date; no promotion on the dashboard. Detail: build on the existing detail page rather than a separate one, show everything the JSON import stores (diff images, web resources, aliases, host z) with links back to websniff in a new tab, and keep the rest of the page for now. Stats computed at render. Status is the switch for "candidate"; the tag's role is decision 2. Replaced the redirect and `?full=1` idea with the single detail page (decision 3). Also found the detail page shows no aliases or permalinks at all today.
