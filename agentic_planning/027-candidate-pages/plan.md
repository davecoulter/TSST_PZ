# 027: Candidate dashboard and candidate detail page

- **Issue:** #27 (part of #16)
- **Branch:** `27-candidate-pages`
- **Depends on:** #23 (merged, PR #32), #25 (merged, PR #33)
- **Status:** Draft, awaiting approval

## Why

Candidates now arrive through `/add_candidate/` and the CLI, but there is nowhere to look at them. #23 keeps them off the main dashboard, and the regular detail page shows them badly:
- Its stamp code prefixes every stamp with the local static folder (`YSE_App/images/stamps/` + value), but candidate stamps are full websniff URLs, so the images break.
- Its "Forced Photometry and Difference Imaging" table shows "No Valid Pixels" for every candidate point, because `/add_candidate/` doesn't set `TransientDiffImage.valid_pixels`.
- It lists superseded points' stamps too (that table queries `TransientDiffImage` directly, not through `get_all_phot_for_transient`).
- Most of the page (follow-up, observing resources, spectra, TNS) doesn't apply to a candidate yet.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | **Candidate dashboard** at `/candidates/` (name `candidate_dashboard`) | Lists transients with **status** "Candidate" (promotion moves them off it). A django-tables2 table like the main dashboard, so sorting, paging and the filter form come for free. Columns: thumbnail (the DIFF headline stamp; SCI on hover/click), name (links to the candidate page), RA/Dec, filters detected ≥3σ, max S/N, host z (spec-z, else photo-z), last detection date, number of detections, number of runs (aliases), status dropdown (the same one as the main dashboard, so a human can promote by hand). Default sort: last detection, newest first. 25 per page. |
| 2 | **Candidate detail page** at `/candidate_detail/<slug>/` (name `candidate_detail`) | Header: name, coordinates, status dropdown, tags, discovery date. **Runs:** one row per alias (the original name plus each `AlternateTransientNames`), each linking to its websniff permalink (`TransientWebResource`, source "diffpype"). **Host:** photo-z ± err, spec-z ± err, source. **Light curve:** the existing Bokeh plot (`lightcurveplot_detail`), which already hides superseded points. **Stamps:** per epoch and filter, a row with date, band, flux ± err, S/N (or "limit"), and the SCI/REF/DIFF triplet; each image opens full size, and FITS paths are shown as text (they're pipeline paths, not links). Superseded points are hidden, with a "show superseded (N)" toggle. A link at the bottom opens the full transient page (`?full=1`) for anything this page doesn't cover (comments, follow-up, spectra). |
| 3 | **Routing** | `transient_detail` redirects a transient with status Candidate to `candidate_detail`, unless `?full=1`. That way search results, alias URLs, old bookmarks and the endpoint's `url` field all land on the candidate page with no other changes. |
| 4 | **Stamp URLs** | A template filter `stamp_src` returns the value unchanged if it is an absolute URL (`http(s)://` or `/`), else the static path the old templates build. The candidate pages use it. The regular detail page is not changed. |
| 5 | **Navigation** | A "Candidates" sidebar link in `base.html` under Main Dashboard, with a count badge of current candidates. |
| 6 | **Keep candidates out of other list views** | Audit the views that list transients by tag or status (`transient_summary`, `transient_tags`, `personaldashboard`, `followup`). Where one lists by tag (like the main dashboard did), exclude status Candidate. Search keeps finding candidates (it lands on the candidate page via 3). User-defined personal dashboard queries are left alone, since the user wrote them. |

Out of scope:
- Promotion rules or a scheduled scan (#28) and TNS renaming (#29).
- The Save button, CORS and login (#26).
- Fixing the regular detail page's stamp handling for non-candidates, or its `IndexError` on a bad slug (found in #23; separate tech-debt issue if wanted).
- Any model change, migration, dependency or image change. Everything uses existing tables.

## Design notes

- **Status, not tag, defines "a candidate".** #23 gives new candidates both. A candidate that matched an existing regular transient gets neither (that transient keeps its status and tags), so it already shows on the main pages. Promotion (#28, or a human using the status dropdown) changes the status, and the candidate moves to the main dashboard.
- **Per-row stats are computed in the query.** Max S/N, last detection, detection count and run count are annotations on the candidate queryset (`Max`/`Count` over photometry, excluding the "Superseded" flag and points with flux/flux_err < 3), so the table can sort on them. "Filters detected" is a per-row lookup for the 25 rows on the page.
- **Images come straight from websniff.** The browser loads them from Justin's server, so they show only where that server is reachable, as on the websniff page itself. If STZ-PZ moves to HTTPS (#17) while websniff stays HTTP, browsers will block the images (mixed content); copying stamps into STZ-PZ is a possible follow-up, not part of this plan.
- **No new JavaScript libraries.** The light curve reuses the Bokeh file already served; the toggle and status dropdown reuse the existing jQuery/AdminLTE setup.

## Decisions (recommendation first; confirm in review)

1. **Table vs. thumbnail grid** for the dashboard: a table with a thumbnail column (sortable, pages, reuses the filter form). A card grid looks nicer but loses sorting.
2. **Redirect** `transient_detail` → `candidate_detail` for status Candidate (item 3), with `?full=1` as the escape hatch.
3. **Headline thumbnail:** the DIFF stamp of the highest-S/N point (that's where a transient is visible). #23 already stores all three.
4. **Status dropdown on both pages**, so a person can promote a candidate before #28 exists.

## Acceptance criteria

- [ ] `/candidates/` lists every status-Candidate transient with the columns above, sorts by each stat, and shows nothing that isn't a candidate.
- [ ] `/candidate_detail/<slug>/` shows the runs with working permalinks, host z, the light curve without superseded points, and the stamp triplets per epoch and filter (superseded hidden by default).
- [ ] `/transient_detail/<candidate slug>/` redirects to the candidate page; `?full=1` shows the old page; a regular transient is unaffected.
- [ ] Changing the status to New from either page moves the candidate to the main dashboard.
- [ ] The main dashboard and the tag-based list views show no candidates.
- [ ] Sidebar link and count work.
- [ ] `ruff check .` passes; no model, migration, dependency or image change.

## Verification

Local Claude, on Dave's local stack, after loading the pipeline's real file (`jwst_5324_trig7_candidates.json`) and a re-run with the CLI from #25:
- Open `/candidates/`: both candidates, stats match the data (max S/N, 4 filters, 2 runs where an alias exists), each column sorts.
- Open each candidate: permalinks open the websniff pages, stamps load, light curve shows one point per filter and epoch, the superseded toggle reveals the older stamps.
- Visit the old `transient_detail` URL (redirects), with `?full=1` (old page), and a regular transient (unchanged).
- Set one candidate to New from the dropdown: it leaves `/candidates/` and appears on the main dashboard under its tags.
- Integration tests in `tests/integration/test_candidate_pages.py`: status codes and redirects for the three URLs, and that a non-candidate never appears on `/candidates/`.

## Log

- **2026-10-14:** Plan drafted after #23 and #25 merged. Surveyed `views.dashboard`, `transient_detail` and its template, `TransientTable` and `base.html`; found the stamp-URL, `valid_pixels` and superseded-stamps problems listed under "Why".
