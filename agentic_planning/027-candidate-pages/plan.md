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
| 2.1 | Notes and confidence as a comment | `notes` and `quality_flag` become one comment by the posting user, reusing the existing comment model, in the form `quality_flag: 3; notes: test` (a part is left out when empty); skipped when that user already left an identical one. |
| 2.2 | `fitsmap_url` | A `TransientWebResource` from source "FitsMap" (created when missing). |
| 2.3 | Host reshape | New fields (`host_id`, `host_ra`, `host_dec`, `host_z`, `host_z2`, `host_sep`, `host_catalog`). `host_z` (the median of the photo-z PDF) becomes the photo-z; `host_z2` is accepted and dropped (no warning); `host_sep` is not stored (computed from positions). Missing `host_catalog` assumes JADES, via a setting, with a warning (interim). Matched by catalog and ID, then by position. The first host stays: a different later host is **not** applied and is reported in the reply (`kept`). A match to an existing host is reported (`matched`). |
| 2.4 | Host schema (**model change, migration**) | A `HostCatalog` lookup table keyed by the catalog **file name** (what the pipeline sends) with a nullable `nickname` (e.g. JADES, set on the server) for display, and on `Host` a nullable `catalog` foreign key and a nullable integer `catalog_id`, with a unique pair. One catalog per host. Rows for new catalogs are created on demand. |
| 2.5 | Candidate tags (**model change, migration**) | A small `TagKind` lookup (Transient, Candidate) and a foreign key on `TransientTag`; existing tags become kind Transient (data migration). Payload `tags` match or create **candidate** tags (names trimmed, case-insensitive; stray tags are fine for now). The automatic "Candidate" tag is **no longer added** at ingest: status is the lifecycle (Candidate -> New once promoted), tags are annotations (see decisions). |
| 2.6 | `warnings` | The reply lists anything ignored or assumed (unknown top-level fields, the assumed catalog, `host_z2`, a host that was kept). |
| 2.7 | Needs review and Archived (#40) | The main dashboard gets a **Needs review** grid (transients in no tag box, not archived) and an explicit archive action; an **Archived** dashboard lists archived ones (proposed as a status `Archived`; open: reuse `Ignore`?). Nothing is deleted. |
| 2.9 | Paths and URLs | `fits` values stored as given; URLs render as links; paths render as **copyable text**, or as links when they fall under a configured path-prefix to URL-prefix map (a server setting), so Justin's later symlinks need no payload change. |
| 2.8 | Files as URLs | `fits` values are stored as given; http(s) values render as links. |

Not in Part 2: the catalog loader and the overlapping-catalog entry table, probabilistic host association, per-person labels (#35), anything on `DataQuality`.

### Part 3: the candidate page

A separate page for the same object, per Dave: `/candidate/<slug>/` (name `candidate_detail`), not a replacement for `/transient_detail/<slug>/`.

- **Links both ways.** The candidate page links to the transient page, and the transient page shows "Candidate page" whenever the object has candidate data. Promotion changes only the status, so the candidate page and its history stay reachable. A transient with no candidate data (e.g. from TNS) gets no link.
- **Where links go.** Cards on `/candidates/` open the candidate page. The main dashboard's boxes and other lists keep opening the transient page.
- **Quick-look layout** (to be fixed from Dave's drawing in `collab_scratch/`): above the fold, the highest-S/N detection with its cutouts, the latest detection, the light curve, an SED, the host (catalog, ID, separation computed from positions, photo-z), candidate tags with the create-a-tag widget, and the comment thread; links out to the websniff page, FitsMap and the FITS URLs. Below: runs, flagged by, and all image triplets (what Part 1 added), with superseded hidden behind the toggle.
- **The Part 1 section** on the transient page becomes a short pointer to the candidate page.
- **SED:** one per epoch (default the latest, with a selector): the epoch's photometry with wavelength on the x-axis, from `PhotometricBand.lambda_eff` (text, in Angstroms). Only 85 of 224 bands have one and **no NIRCam band does** (the endpoint creates bands lazily), so a data step fills in the NIRCam pivot wavelengths from the official filter table first. `HostSED` in the schema is a different thing: a host galaxy's SED-fit result (type, mass, SFR, metallicity, E(B-V), age, redshift, chi2, plot file); it is empty and is not used here.
- **Reference design: Justin's static card** (screenshot shared 2026-10-15). Header: candidate name, RA/Dec, badges "3/4 filters >= 3 sigma" and "max S/N"; host line (RA, Dec, separation, z). A grid of cutouts, **one column per filter** and rows DIFF, SCI and REF, each with its magnitude on the image ("nondetection" where there is none, "NOT PROVIDED" for a missing image). On the right, an **observed SED** (observed AB magnitude against observed wavelength) and a **rest-frame SED** (absolute AB magnitude against rest wavelength, from the host redshift), then a "No P(z) available" placeholder. Footer: "Saved - Q1", Get photometry, View in field (FitsMap), Permalink. The STZ page should carry the same first-look information (filters and max S/N badges, the per-filter cutout grid, both SED panels, host z) and add what only STZ has: the light curve over all runs, tags, comments, history.
- **SED details:** limits are drawn as upper-limit arrows at the **3-sigma limiting magnitude** from `flux_err`, not at the measured magnitude; the magnitude axis is inverted; the rest-frame panel appears only when the host has a redshift; a P(z) panel is a placeholder for later (#43).
- **Answered (Dave, from Justin):** the payload's `mag` is the **difference-image** magnitude, and showing one magnitude per filter is enough for now, because the interest is in the change in behavior. The reference depth (and the SCI and REF magnitudes) would help judge an anomalous point's error; that waits (see the future issue).
- Later: click a light-curve point to see its cutouts.

### Decisions (Revision, 2026-10-15)

1. **Status is the lifecycle, tags are annotations.** The "Candidate" tag is no longer added. A candidate is promoted by changing its status (Candidate -> New). Embellishments ("Young?", "Candidate Watch") are candidate-kind tags; how the application treats the object stays with the status. (There is already a `Watch` status; "Candidate Watch" may just be that.)
2. **Comment text:** `quality_flag: 3; notes: test`.
3. **`host_z2`:** ignored.
4. **Promotion:** the transient page does not show candidate-kind tags; each page links to the other.
5. **SED:** one per epoch; see Part 3.

### Part 3 layout (from Dave's sketch, 2026-10-15)

The purpose of the candidate page is to **verify the point source**, not to say where it is numerically. Two columns above the fold, a synoptic block and tabs below.

**Header.** Name; badges ("n/N filters >= 3 sigma", "max S/N"); the **status control** (the existing Following / Watch / Interesting / Ignore buttons and the drop-down for the rest), moved above the fold so that **changing the status to New is the promotion**; links: Permalink, "View in field" (FitsMap), and "Transient page" when it exists.

**Above the fold, left column**
1. **Highest-S/N triplet:** SCI, REF and DIFF of the best detection, with its filter, date and magnitude.
2. **Most recent triplet:** the latest epoch's best filter.
3. **Host card:** reuses the existing host HTML: host name, catalog (nickname, else file name), RA/Dec, **photo-z and/or spec-z, whichever are present**, separation (computed from positions). External links dropped (these hosts are rarely in ground-based catalogs). Its image is the **highest-S/N reference cutout** (no supernova light in it), with a marker where the candidate is: cutouts are centred on the candidate, so with no WCS the marker goes at the centre of the image. Below it, a small gallery of **every filter's reference image**.

**Above the fold, right column**
4. **SED** (observed; a rest-frame view when the host has a redshift) with an epoch selector, and the **light curve** (the existing plot), side by side.
5. **Comments:** User, **time submitted** and Comment, with the add-comment form; the Save-dialog notes appear here.
6. **Candidate tags:** chips with the drop-down and create-a-tag widget (candidate kind).

**Below the fold: synoptic information**, the existing "Transient Detail" box, trimmed: R.A./Dec (sexagesimal and degrees), discovery date, Galactic l/b, and later Real/Bogus score, MW E(B-V) and best distance (host redshift plus a cosmology); plus the Photometric Summary (discovery magnitude, last non-detection, recent magnitude). **Dropped for candidates:** best and TNS spectral class, photometric class, YSE field.

**Tabs:** *Overview* (the above), *All cutouts* (every image triplet, one row per epoch and filter, superseded behind the toggle), and the runs and who flagged it.

The existing `/transient_detail/` page is unchanged apart from the "Candidate page" link; the Part 1 section on it becomes a pointer.

### Issues for the revision (filed 2026-10-15)

In this branch: #36 payload v1.3, #37 `HostCatalog` and `catalog_id`, #38 candidate-kind tags (`TagKind`), #39 the candidate triage page, #40 the Needs review grid and Archived state, #41 NIRCam band wavelengths. Future: #42 real filter curves, #43 host catalog loader and overlapping catalogs, #44 probabilistic host association, #45 point-to-cutout links, #46 remove the assumed JADES default. Also related: #31 (TESS), #35 (labels and rejection reasons), #28 (promotion), #29 (TNS), #26 (Save button, CORS, login), #17 (security).

Dave's decision on the main dashboard (replaces the "Untagged" box, 2.7): a **Needs review** grid for transients in no tag box and not archived, an explicit archive action, and an **Archived** dashboard. Nothing is deleted; state is managed explicitly (#40).

### Open questions (Revision)

1. Archived as a new status, or reuse `Ignore` (#40)?
2. SED epochs: points within a day form one epoch (Dave); tune on edge cases.
3. NIRCam pivot wavelengths: from the official filter table, with the source recorded (#41); real filter curves later (#42).

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
- **2026-10-15:** Dave answered the revision's open questions: stop adding the "Candidate" tag (status is the lifecycle, tags are annotations); comment text `quality_flag: 3; notes: test`; ignore `host_z2`; no candidate-kind tags on the transient page after promotion; one SED per epoch. Looked up the SED question: `HostSED` is a host-fit result model (empty), a candidate SED is photometry vs wavelength, and `PhotometricBand.lambda_eff` (Angstroms, text) is empty for all NIRCam bands, so a data step must fill it. Added an Untagged dashboard box (2.7) so a promoted candidate without a transient tag still shows somewhere.
- **2026-10-15:** Dave settled the loose items: the dashboard gets a Needs review grid and an explicit Archived state (replacing the Untagged box), SED epochs are grouped daily, band wavelengths come from approximate tables for now. Filed the issues #36-#46 (see above). Next: a high-level game plan review with Dave before building, and questions for Justin on the payload.
- **2026-10-15:** Dave's Slack thread with Justin settled the host fields: `host_catalog` will be the catalog's **file name** (a nickname is hard for the pipeline), so `HostCatalog` is keyed by file name with a nullable `nickname` set server-side; `host_z` is the median of the photo-z PDF and `host_z2` the maximum likelihood estimate (ignored); no error or PDF is sent yet. Contract v1.3 updated.
- **2026-10-15:** Dave relayed Justin's answers: `quality_flag` 1 definite, 2 probable, 3 possible, one per candidate; each reviewer posts their own choices with their own login (so the posting user is the reviewer); tags are strings from a drop-down mapped to or created as candidate tags; run IDs are salted and runs don't know each other (hence the spatial clustering); `flux` and `mag` are measurements at the position, and the limit is an interpretation (the 3-sigma limit would be about 28.99 where the measured value is 30.95, so plot a limit at the limiting magnitude); `mjd` is mid-exposure UTC; null is no image. FITS files cannot be served yet, so paths are shown as copyable text, or as links through a server-side path-prefix map (2.9). Dave also shared Justin's static card as the reference design for the first-look page (see Part 3).
- **2026-10-15:** `mag` is the difference-image magnitude; one magnitude per filter is enough for now (reference depth is a later ticket). `www.stsci.edu/~tsst` is **world-reachable**, so anything symlinked there (FITS included) is public: keep FITS as copyable paths unless a specific cutout is cleared to be public.
- **2026-10-15:** Dave clarified the data is public; the concern with FITS paths on the pages is revealing internal network paths. Fine for internal use now; noted on #17 so the raw paths are hidden or mapped to URLs before STZ-PZ is opened up.
- **2026-10-15:** Dave's sketch (`collab_scratch/CandidateDetailPageSketch.jpg`, not committed) and answers: the host image is the highest-S/N reference cutout with a centre marker, plus a gallery of each filter's reference image; the page is for verifying the point source, so the synoptic block is the trimmed Transient Detail box (RA/Dec, discovery date, Galactic l/b, later Real/Bogus, MW E(B-V), best distance) plus the Photometric Summary, without spectral classes or YSE field; the status control moves above the fold (changing it to New is the promotion); comments show the submission time; an *All cutouts* tab holds every triplet. Written into Part 3 above.
