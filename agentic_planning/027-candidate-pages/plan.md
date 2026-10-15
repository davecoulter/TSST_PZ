# 027: Candidate dashboard and candidate detail page

- **Issue:** #27 (part of #16)
- **Branch:** `27-candidate-pages`
- **Depends on:** #23 (merged, PR #32), #25 (merged, PR #33)
- **Status:** Part 1 (pages) built and verified on the local stack; revised 2026-10-15 to add Part 2 (payload v1.3, schema) and Part 3 (the candidate page); awaiting Dave's approval of the revision

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
| 2b | **Flagged by** (added 2026-10-14, Dave) | In the Candidate data section: each user who sent this candidate in, with first and last post time and points sent. Read from `TransientPhotData.created_by`: every POST creates new photometry rows as the poster (a re-post supersedes the old rows rather than editing them), so it records everyone; web resources and aliases are de-duplicated, so they don't. |
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
2. ~~The "Candidate" tag~~ **Decided: keep it as a label** (Dave). Keep adding it on ingest as a permanent "came from the candidate pipeline" label, never used for filtering, and show its box on the main dashboard for promoted ones (item 5). The alternative is to stop adding the tag, so a person adds a real tag when promoting; until they do, the promoted transient appears in no main-dashboard box.
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


## Revision 2026-10-15: v1.3, schema, and a candidate page

After verifying Part 1, Dave related his conversation with Justin (workflow in `agentic_planning/016-candidate-workflow/workflow.md`). Because the payload, the schema and the display are strongly coupled, Dave chose to roll them into this branch as three parts. Part 1 is what is described above and is verified.

### Part 2: payload v1.3 and schema

Contract: `agentic_planning/023-add-candidate-endpoint/contract.md` (v1.3).

| # | Deliverable | Notes |
|---|---|---|
| 2.1 | Notes and confidence as a comment | `notes` and `quality_flag` become one comment by the posting user, reusing the existing comment model; skipped when that user already left an identical one. Exact text format to settle. |
| 2.2 | `fitsmap_url` | A `TransientWebResource` from source "FitsMap" (created when missing). |
| 2.3 | Host reshape | New fields (`host_id`, `host_ra`, `host_dec`, `host_z`, `host_z2`, `host_sep`, `host_catalog`). `host_z` becomes the photo-z; `host_z2` is dropped with a warning; `host_sep` is not stored (computed from positions). Missing `host_catalog` assumes JADES, via a setting, with a warning (interim). Matched by catalog and ID, then by position. The first host stays: a different later host is **not** applied and is reported in the reply (`kept`). A match to an existing host is reported (`matched`). |
| 2.4 | Host schema (**model change, migration**) | A `HostCatalog` lookup table, and on `Host` a nullable `catalog` foreign key and a nullable integer `catalog_id`, with a unique pair. One catalog per host. Rows for new catalogs are created on demand. |
| 2.5 | Candidate tags (**model change, migration**) | A small `TagKind` lookup (Transient, Candidate) and a foreign key on `TransientTag`; existing tags become kind Transient (data migration). Payload `tags` match or create **candidate** tags (names trimmed, case-insensitive; stray tags are fine for now). The existing "Candidate" tag and the main dashboard's box for it: see open question 1. |
| 2.6 | `warnings` | The reply lists anything ignored or assumed (unknown top-level fields, the assumed catalog, `host_z2`, a host that was kept). |
| 2.7 | Files as URLs | `fits` values are stored as given; http(s) values render as links. |

Not in Part 2: the catalog loader and the overlapping-catalog entry table, probabilistic host association, per-person labels (#35), anything on `DataQuality`.

### Part 3: the candidate page

A separate page for the same object, per Dave: `/candidate/<slug>/` (name `candidate_detail`), not a replacement for `/transient_detail/<slug>/`.

- **Links both ways.** The candidate page links to the transient page, and the transient page shows "Candidate page" whenever the object has candidate data. Promotion changes only the status, so the candidate page and its history stay reachable. A transient with no candidate data (e.g. from TNS) gets no link.
- **Where links go.** Cards on `/candidates/` open the candidate page. The main dashboard's boxes and other lists keep opening the transient page.
- **Quick-look layout** (to be fixed from Dave's drawing in `collab_scratch/`): above the fold, the highest-S/N detection with its cutouts, the latest detection, the light curve, an SED, the host (catalog, ID, separation computed from positions, photo-z), candidate tags with the create-a-tag widget, and the comment thread; links out to the websniff page, FitsMap and the FITS URLs. Below: runs, flagged by, and all image triplets (what Part 1 added), with superseded hidden behind the toggle.
- **The Part 1 section** on the transient page becomes a short pointer to the candidate page.
- An SED needs each band's wavelength; to confirm what the DB holds for bands.
- Later: click a light-curve point to see its cutouts.

### Open questions (Revision)

1. The "Candidate" tag: with candidate-kind tags, stop adding it at ingest (status already says candidate)? Then a promoted candidate appears in a main-dashboard box only if a transient-kind tag is added. Or keep adding it, as a candidate-kind tag.
2. Comment text format for notes plus confidence (waiting on the updated JSON).
3. What `host_z2` is (Justin).
4. On promotion, should candidate-kind tags still show on the transient page (read-only)?
5. SED: band wavelengths, and one SED per epoch or the latest?

### Acceptance criteria (Revision)

- [ ] A payload shaped like Justin's current file (host block, `notes`, `quality_flag`, `fitsmap_url`, a limit point) is accepted, and the reply lists what was ignored or assumed.
- [ ] `notes`/`quality_flag` appear as a comment by the posting user; posting twice adds no duplicate.
- [ ] The host is created or matched by catalog and ID, then position; a second post with a different host leaves the first and reports `kept`.
- [ ] The migrations apply on the existing local DB and on a fresh seeded DB; `makemigrations --check` is clean for `YSE_App`.
- [ ] Candidate-kind tags can be created and applied on the candidate page and do not show as main-dashboard boxes.
- [ ] `/candidate/<slug>/` shows the first-look items above the fold and links to the transient page, and back.
- [ ] Promoting a candidate keeps its candidate page reachable.

## Log

- **2026-10-14:** Plan drafted after #23 and #25 merged. Surveyed `views.dashboard`, `transient_detail` and its template, `TransientTable` and `base.html`; found the stamp-URL, `valid_pixels` and superseded-stamps problems listed under "Why".
- **2026-10-14:** Reviewed with Dave. Dashboard: thumbnail grid; drop obs group, spec class, last mag and last obs date; no promotion on the dashboard. Detail: build on the existing detail page rather than a separate one, show everything the JSON import stores (diff images, web resources, aliases, host z) with links back to websniff in a new tab, and keep the rest of the page for now. Stats computed at render. Status is the switch for "candidate"; the tag's role is decision 2. Replaced the redirect and `?full=1` idea with the single detail page (decision 3). Also found the detail page shows no aliases or permalinks at all today.
- **2026-10-14:** Dave chose decision 2: keep adding the "Candidate" tag as a permanent pipeline label, and show its main-dashboard box for promoted candidates (item 5).
- **2026-10-14:** Dave approved the plan (Opus, medium). Built:
  - `YSE_App/candidate_views.py`: `candidate_dashboard` (`/candidates/`) and `candidate_section_context()` for the detail page. Stats (max S/N, filters ≥3σ, detections, best DIFF thumbnail) come from one query over the candidates' photometry, superseded points excluded, using the plots' detection rule (S/N ≥ 3, or a mag with no flux). Sorting by max S/N needs every candidate's stats, so all are computed and then paged in Python; fine for hundreds of candidates.
  - Templates `candidate_dashboard.html` (card grid) and `candidate_section.html` (runs, host, image triplets with the superseded toggle). The section sits at the top of the detail page's Summary tab.
  - `YSE_App/templatetags/candidate_extras.py`: `stamp_src`, `is_url`, and `candidate_count` for the sidebar (a template tag, so no settings change for a context processor).
  - Detail page: the "Image Stamps" box and the diff-image table use `stamp_src`. The table's "No Valid Pixels" check now also passes rows whose stamps are URLs (`/add_candidate/` doesn't set `valid_pixels`). The QUB button is hidden when the headline stamp is a URL (its ID is parsed from a QUB file name).
  - Main dashboard shows the Candidate tag's box again (promoted ones only). `transient_summary` by tag leaves out status Candidate, like the dashboard boxes.
  - `tests/integration/test_candidate_pages.py` (session login through `/login/`).
- **2026-10-14:** Decisions made while building:
  - "Search By Tag" (`get_transient_tags`) is left alone: it's a search, like the name search, so choosing the Candidate tag finds candidates. `followup` doesn't list by tag.
  - The candidate pages read photometry directly rather than through `PhotometryService`'s per-group authorization, which the regular detail page applies. Every current user is in the TSST group; revisit if group-restricted photometry appears.
  - FITS paths are shown as text in the new section. In the old "Image Stamps" box a FITS path starting with `/` becomes a link on STZ-PZ's host that won't resolve, as non-local FITS links didn't before either.
  - Checked offline: `ruff check .`; the new templates render with Django 4.0 and fake data (URL and local stamps, limits, superseded toggle, paging), and the edited `transient_detail.html` and `base.html` parse. Nothing has run against a DB yet.
- **2026-10-14:** Dave asked for two more review features. (1) "Flagged by" on the detail page: added as item 2b, since it only reads existing rows. (2) Rejection reasons (cosmic ray, snowball, proper-motion star, alignment artifact, ...) for later CNN training: needs per-user labels stored in a new table, so it is a model change with its own issue (#35) and plan, not part of #27.
- **2026-10-15:** Verified Part 1 on Dave's local stack (see the verification entries above and the test results). Dave related a conversation with Justin about the workflow and sent Justin's newer JSON; with the server's validator it was rejected (host block) and three fields (`fitsmap_url`, `quality_flag`, `notes`) were silently ignored. Decisions with Dave: adapt the endpoint to Justin's shape now (v1.3, Part 2); notes and confidence as a comment; `host_z` becomes the host photo-z, `host_z2` dropped, `host_sep` computed not stored; assume catalog JADES when not sent (interim); one catalog per host with `catalog` and an integer `catalog_id` on `Host`; first host wins and a different one is reported; candidate tags as a separate kind of tag (a `TagKind` table and a foreign key); a separate candidate page with links both ways (Part 3); fitsmap URL as a second web resource; run and field recorded in the web resource text. Written up in `agentic_planning/016-candidate-workflow/workflow.md`; contract v1.3 drafted. Waiting for Dave's drawing, an updated JSON, and approval of this revision.
