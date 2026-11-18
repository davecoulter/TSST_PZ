# 086: Group-based visibility for transients, photometry and spectra

- **Issue:** #86, with #88 folded in as phase 5 (the PR closes both)
- **Branch:** `86-group-visibility`
- **Status:** Approved by Dave 2026-11-17 for phases 1–4 (phase 5 later); building phase 1

## Why

STZ-PZ is to be shared with external users who should see only the data they're entitled to, including whether an unreported transient exists at all. Today:

- Transients have no visibility control: any logged-in user sees every transient and candidate.
- Photometry and spectra have `groups`, but "no group" means everyone sees them, and 18 read paths skip the rule anyway.
- Explorer lets any user run raw SQL.

## The rule

Everything here is decided (Dave, 2026-11-12 and 2026-11-17).

**Groups** are Django auth `Group`s, the same kind photometry and spectra already use. A reserved **`Public`** group, created by a migration, means "every logged-in user". An item may be in several groups, e.g. `Public`, `TSST`, or `TSST` + `COSMOS3D`. "No group" means **nobody** except superusers.

**Superusers** see everything. Nobody else bypasses the rule, not even internal staff: they're put in groups like everyone else.

**Transients** (candidates are transients and follow the same rule). Each user has one of three levels of access to a given transient:

| Level | When | What they see |
|---|---|---|
| **Full** | superuser, or in one of `transient.groups`, or `Public` is in them | Everything about the transient. Each photometry and spectrum still follows its own groups (below). |
| **TNS object** | not Full, but the transient has an `iau_name` | It shows in lists, search and counts. The detail page shows only the TNS facts: name, internal name as reported, position, TNS link, discovery date, TNS classification, host redshift / photo-z as TNS gives it, and photometry and spectra in `Public`. Data matched to or imported from TNS's record is `Public` (see "Resolve on TNS"), and `obs_group` gives its provenance. No notes, comments, tags, follow-ups, images, or any photometry or spectra outside their groups. |
| **None** | neither | No trace anywhere: lists, counts, badges, search, dashboards, API, exports and TNS pages. A detail URL returns a **404** page (below). |

**Photometry and spectra:** visible if the user is a superuser, or the item is in `Public`, or it's in one of the user's groups, **and** its transient is visible to the user at some level. The second half closes a hole: a `Public` point on a hidden transient would otherwise reveal that the transient exists. `PhotData`/`SpecData` follow their parent photometry or spectrum.

**Hosts:** have no groups of their own. A host is visible if at least one linked transient is visible to the user. Hosts with no linked transient (catalog-only) are visible to everyone.

**The 404 page:** missing and hidden transients get the same well-formatted page: "No transient `<slug>` that you can see. It may not exist, or you may not have access. Ask your group admin." The status is 404 for both, so the response can't tell anyone whether the transient exists. A 403 was considered: TSST's names are opaque, but other groups' uploads may use J-names that encode coordinates. Old slugs kept as aliases (#29) resolve first, and then the rule applies.

**Uploads fail fast:** every path that creates a transient, photometry or spectrum needs at least one existing group, and is refused with a clear error otherwise. There's no default group and no fallback to the uploader's groups, because guessing now means repairing data later. **Uploaders may assign only groups they belong to, or `Public`.** Superusers may assign any group. A pipeline account is made a member of the groups it writes for, so it needs no exception.

**Resolve on TNS (#88, phase 5):** reporting to TNS does **not** make any of our data public by itself, and the #52 IAU write-back doesn't change any groups. Instead, one "Resolve on TNS" page does both jobs:
- **Look up (read-only):** TNS cone search on RA/Dec, falling back to the internal name, then `/api/get/object` with photometry. It works the same for transients reported by us, by others, before #52 or outside STZ-PZ.
- **Results, per transient:**
  - the proposed IAU name, or "no match", or the candidates when there are several matches or a name conflict (the #52 "name differs" logic; nothing is offered for writing in that case);
  - **matched points:** ours that match TNS's, on the same rule (date, band and magnitude within the tolerance); tick to make them `Public`;
  - **TNS points we don't have:** tick to import them, add-only, as `Public`, with `obs_group` = the TNS reporting group for provenance.
- **Apply:** nothing is written until the user clicks Apply. Apply sets the IAU name, flips the ticked points to `Public` and imports the ticked TNS points. The confirm step says that the transient becomes visible to all users as a TNS object (e.g. "AT 2026abc will become visible to all users").
- **Instruments and bands** for imported points: the reverse of #52's `"<telescope> - <instrument>"` match against the TNS values snapshot. A telescope, instrument or band we don't have is created from the snapshot, named as TNS names it, and a new telescope goes under a placeholder `Observatory` "From TNS". `sync_tns_values` (#52) remains the only sync. No model change.
- **Record:** each Apply writes one `TNSResolveAttempt` (new model): who, when, transient, outcome (matched / no match / conflict), the IAU name set, and the ids of the points made `Public` and imported. Lookups that aren't applied aren't recorded. It's not exposed through the API, the same as `TNSReportAttempt` (API parity: on purpose). It's a model change, so it ships with a migration and Dave runs `migrate`.
- **Where:** under the "TNS Integration" submenu (#12), a page listing the transients the user has Full access to with no IAU name (select a batch, "Look up"), and a detail-page button that opens the same page with that one transient. A batch is capped at about 25, and lookups run one after another, stopping early on a TNS rate-limit reply; the rest stay "not looked up yet".
- **Who:** users with Full access who are in "TNS Reporters" (#52), plus superusers.
- Photometry only. Importing TNS spectra is #90. It uses `YSE_App/tns_client.py` (#52), not the legacy `util/tnsAPI.py`, which calls outdated URL formats.

**Who can edit:** writes in the app (edit transient, tags, status, comments, follow-ups, and API `PUT`/`PATCH`) need Full access. Fixing an upload someone else made is a job for an admin. Django's flags: `is_active` = can log in; `is_staff` = can enter the admin, but only for the models they've been given permissions on; `is_superuser` = every permission without being granted it (they still need `is_staff` to enter the admin).

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | **Model:** `Transient.groups` (M2M to auth `Group`) + migration | Schema migration, plus a data migration that only creates the `Public` group (`get_or_create`, reversible as a no-op). It assigns **no** groups to existing data: see #10. |
| 2 | **`TransientService`, upstream of the data services** | New `YSE_App/data/TransientService.py`, in the same style as `PhotometryService` and `SpectraService`, and the single home of the rule. **Group rule:** the existing `GetUserGroupQuery` moves here (superuser bypass, `Public`, the user's groups, no "no group" clause); the photometry and spectra services import it instead of defining their own. **Transients:** `visible_transients(user)` (Full ∪ TNS object), `full_access_transients(user)`, `access_level(user, transient)`, `get_visible_or_404(user, slug)`. **Anything hanging off a transient:** one helper, `filter_by_transient(qs, user, field='transient', level=FULL)`, plus a small DRF mixin so a viewset only declares its `transient_field`. Comments, follow-ups, images, tags, alternate names, tasks and hosts all use it, so there's no per-model copy of the rule. **Photometry and spectra:** their services add "its transient is visible" by calling `TransientService`. **Applying it to views:** decorators keep each URL to one line. `@transient_access(level='full'|'object', by='slug'|'transient_id')` loads the transient through `TransientService`, gives the 404 page, and passes the transient in. `@superuser_required` covers hidden pages. A matching mixin covers class-based form views, and the DRF mixin covers viewsets. The URL sweep checks that every route has one. |
| 3 | **Detail page and 404** | `transient_detail` (and the candidate page) get `access_level`. The TNS-object level renders a reduced template section (TNS facts + `Public` photometry and spectra). A shared 404 template, used through `TransientService.get_visible_or_404(user, slug)` (and the `@transient_access` decorator) by every slug lookup. |
| 4 | **The 18 known bypasses**, routed through the services | `candidate_views.py` (`candidate_stats`, `candidate_dashboard`, `candidate_section_context`, `photometry_epochs`); `tns_report.transient_fields`; `table_utils.py` (`order_by_display_name` ×7, `annotate_with_disc_mag`); `views.transient_summary`; `view_utils.py` (`spectrumplot`, `spectrumplot_summary` ×2, `spectrumplotsingle`). |
| 5 | **Every other read path** | The survey found direct queries in ~50 files. All user-facing ones go through the services (except the hidden legacy pages, open question 1): `views.py`, `view_utils.py`, `dashboard_sets.py`, `templatetags/transient_detail_extras.py`, `queries/yse_python_queries.py` (via `filter_query_results`), the `data_utils.py` GET endpoints (`get_transient`, `get_rising_transients*`, `get_*_transients_box`, `box_search`, `query_api`), and exports (`download_data`, `download_photometry`, `download_spectra`, `download_bulk_photometry`). The plots and images addressed by `transient_id` (`lightcurveplot_*`, `salt2*plot`, `spectrumplot*`, `finderchart`, `finderim`, `get_ps1_image` / `get_hst_image` / `get_chandra_image` / `get_legacy_image`, airmass, rise/set and moon angle) go through `TransientService` too: a hidden id gives a 404. **Saved queries on dashboards** (`query_api`, `transient_summary/<query>`, `UserQuery` links, including `python_query`): the stored SQL still runs on the `explorer` connection, but its rows never reach the user. `TransientService.filter_query_results(user, query)` reads only the transient `id` column from the result and returns `visible_transients(user).filter(id__in=ids)`. The grid is then built from that queryset with the standard dashboard columns, through the services, so a row shown at TNS-object level shows only TNS facts. A query with no transient `id` column is refused for non-superusers. `change_status_for_query` is superuser-only. **API viewsets:** `TransientViewSet` (`queryset = Transient.objects.all()` today) plus every viewset of a model hanging off a transient: `Log`, `TransientFollowup`, `TransientImage`, `TransientWebResource`, `AlternateTransientNames`, `TransientObservationTask`, `Host`, `HostPhotometry`/`HostSpectrum`, tags and additional info. Each gets its `get_queryset` from `TransientService`. **Writes** (`transient_edit`, `candidate_tag`, `add_transient_comment`, `add_transient_followup`, `add_transient_observation_task`, `delete_followup`, API `PUT`/`PATCH`) need Full access. Legacy YSE-only surfaces: see open question 1. |
| 5b | **Orphaned grid** (superusers only) | A page listing every transient with no group, plus counts of photometry and spectra with no group (per transient and overall), with a bulk "assign groups" action. It's a nav entry for superusers only, and it doubles as the tool for the ETL (#10). |
| 5c | **"Resolve on TNS" (#88)** | Phase 5, as in "Resolve on TNS" above: the nav page and detail button, the read-only lookup, the results with match/import checkboxes, Apply, and creating instruments and bands from the snapshot. Tests use recorded TNS responses: a single match, no match, several matches, a name conflict, a rate limit, add-only import (an existing point is never changed), and Apply making the transient a TNS object. |
| 6 | **Upload paths, fail fast** | Required `groups` (≥1 existing group name; unknown names refused; only groups the uploader belongs to, or `Public`): `data_utils.add_transient`, `add_transient_phot`, `add_transient_spec` (and their `*_util` helpers); the web form `upload_spectrum`; the candidate ingest endpoint (`candidate_ingest.py`); `scripts/ingest_candidates_cli.py` and `scripts/ingest_transients_cli.py` (new required `--groups`); the API serializers for Transient, TransientPhotometry, TransientSpectrum (validation plus the hand-written `create()`/`update()`); the admin (form validation needs ≥1 group). |
| 6b | **Legacy cron ingestion removed** | Every `CRON_CLASSES` entry that creates transients, photometry or spectra is taken out of `CRON_CLASSES` (the modules stay for now; deleting them is separate cleanup): `TNS_uploads.TNS_emails`, `QUB_data.*`, `Query_ZTF.AntaresZTF`, `Gaia_LC.GaiaLC`, `DECam_upload.DECam`, `YSE_Forced_Phot.*`, `YSE_observations.SurveyObs`, `rapid_classify_cron`, and the rest of the list once checked one by one. #89 covers rewriting the ones we need (ATLAS and ZTF forced photometry, tagged `Public`) as services that set groups. |
| 7 | **TNS** | The select page lists only Full-access transients. `tns_report.transient_fields` and the payload use only photometry the reporter can see (#4). The write-back doesn't touch groups: a transient becomes a TNS object by itself, because `iau_name` is set, and data goes `Public` only through "Resolve on TNS" (#5c). Results and history pages follow the transient rule. The legacy `submit_to_tns/<name>` URL becomes superuser-only. |
| 8 | **Explorer** | `EXPLORER_PERMISSION_VIEW` and `EXPLORER_PERMISSION_CHANGE` become `lambda r: r.user.is_superuser` (check the signature our django-sql-explorer version expects: request or user). Only superusers write, run and see raw results. Other users reach saved queries only through dashboard links, which are filtered (#5). The `explorer` DB user isn't filtered, which is fine because no raw row reaches a non-superuser. **Why ad hoc queries stay superuser-only for now:** even with only IDs consumed, a query can work as an oracle. "Visible transients `WHERE` their hidden photometry is brighter than 20" returns only visible IDs, yet reveals hidden data. User-written queries later need a DB user that can read only views already filtered by the rule (future issue). |
| 9 | **Tests** | Unit tests per surface with three users (in group A, in group B, superuser) and fixtures: an unreported transient in A, an unreported transient in B, a reported transient in A with `Public` and A-only photometry, an ungrouped transient. **Plus a URL sweep:** a test that walks every URL pattern (`urls.py` has 132) as the group-B user and checks that the A-transient's name, slug and coordinates never appear in any response (non-matching patterns are listed in an explicit skip list with reasons). That sweep is what stops a new page from skipping the rule unnoticed. A test that a saved query returning both A's and B's transients shows group-B users only B's. Integration test (API parity): write `groups` through the API, read it back, and check that an upload without groups is refused. |
| 10 | **ETL for existing data (not a migration)** | `agentic_planning/086-group-visibility/etl.md` (or a SQL file next to it): read-only queries that list the transients, photometry and spectra with no group, counted by `obs_group`, and the transients whose photometry or spectra groups disagree with their own. Dave assigns groups by hand, with the orphaned grid (#5b) or SQL, rehearsed first on the local production restore. Release order: run the ETL on production **before** or right with the deploy. Until then, ungrouped data is visible only to superusers: the rule fails closed, never open. |
| 11 | **Docs** | User docs in `docs/`: groups, `Public`, what outside users see of a TNS object, required groups on upload (CLI and API examples). |
| 12 | **Navigation** (`templates/YSE_App/base.html`) | The sidebar is AdminLTE 2 with `data-widget="tree"` already on it, so submenus are `li.treeview` + `ul.treeview-menu`; no new library. **TNS Integration** (TNS Reporters + superusers): Resolve on TNS (phase 5), Report to TNS (the existing select page), and **TNS status**, which replaces "TNS reports". The status page lists report attempts and resolve records (`TNSResolveAttempt`) together, newest first, with a filter by kind, and follows the transient rule. **Admin** (superusers only): Django admin, Groups & users (a direct link to `admin/auth/group/`, since sharing is all about groups), Query Explorer, and Orphaned transients (#5b). The flat "Admin" and "Query Explorer" links are no longer shown to everyone. |

Out of scope:
- Group management UI: groups and memberships are managed in the Django admin by superusers.
- Login credentials and API tokens (#17).
- A "release approval" state for TNS (decided: reporters send only what they can see).
- Rewriting the ATLAS / ZTF forced-photometry ingesters (#89).
- Importing TNS spectra (#90; phase 5 imports photometry only).
- `YSE_App/util/scrub_private_data.py` and other offline scripts that aren't reachable from a URL or cron.

## Design notes

- **Fail closed.** Anything that the rule doesn't cover, or that has no group, is visible only to superusers. Nothing ever becomes public by accident.
- **Why tag TNS data `Public` instead of special-casing it:** the photometry and spectra rule stays one rule. Points matched to or imported from TNS are visible to all because someone ticked them `Public` in "Resolve on TNS", and `obs_group` already records who they came from.
- **Querying TNS objects:** `visible_transients(user)` = `Q(groups in user's groups or Public) | Q(iau_name__isnull=False) & ~Q(iau_name='')`, with `.distinct()`. Superusers get `.all()`. Pages that show internal data (notes, follow-ups, tags) use `full_access_transients`.
- **Performance:** the M2M join plus `distinct()` on the big dashboard tables. Check the query count and time on the local production restore, and add an index if needed.
- **API parity** (`CLAUDE.md`): `groups` is exposed. It's added to `TransientSerializer`, *including* the hand-written `create()` and `update()`; a `groups__name` filter on `TransientFilter`; no new model, so no new `*-detail` route; and an integration test that writes it and reads it back.
- **Dependencies:** none. Django auth groups and the existing services only; no image change.

## Acceptance criteria

- [ ] A user in group A sees no trace of an unreported transient restricted to group B anywhere: lists, counts, badges, search, dashboards, API, exports and TNS pages. Its detail URL gives the 404 page.
- [ ] A missing slug and a hidden slug give the same 404 page and status.
- [ ] A transient with an `iau_name` is visible as a TNS object (its TNS facts and `Public` data) to users outside its groups. Its other photometry, spectra, notes, comments, tags and follow-ups stay hidden from them.
- [ ] Photometry and spectra follow one rule on every page, plot and API path, including "its transient must be visible". No user-facing code queries them directly. The rule lives only in `TransientService` and the two data services that call it.
- [ ] **URL sweep:** a test visits every URL pattern as a user outside group A, and the name, slug and coordinates of A's unreported transient appear in none of the responses. Every skipped pattern is listed with a reason.
- [ ] "No group" is visible only to superusers. Every transient with no group is listed in the orphaned grid, which only superusers can open.
- [ ] Every upload path (web endpoints and form, candidate ingest, both CLIs, API, admin) refuses a transient, photometry or spectrum without a valid group, or with a group the uploader isn't in, with a clear error.
- [ ] Writes need Full access.
- [ ] A TNS report changes no groups. The report form uses only photometry the reporter can see.
- [ ] **Resolve on TNS (#88):** from the nav page (batch) or the detail button, a lookup writes nothing.
  - Results show the proposed IAU name (or no match, or candidates for a conflict), our points matching TNS's, and the TNS points we don't have.
  - Apply sets the IAU name, makes only the ticked matched points `Public`, and imports only the ticked TNS points, add-only, as `Public`, with instruments and bands from the snapshot.
  - Conflicts write nothing, and the rate limit stops a batch cleanly.
  - It's open only to Full-access TNS Reporters and superusers.
  - Each Apply leaves a `TNSResolveAttempt`, shown on the TNS status page.
- [ ] The sidebar has a "TNS Integration" submenu (Resolve, Report, Status) for TNS Reporters and superusers, and an "Admin" submenu (Django admin, Groups & users, Query Explorer, Orphaned transients) for superusers only. No other user sees Admin or Explorer links.
- [ ] Explorer, `change_status_for_query` and the legacy `submit_to_tns` are superuser-only. Saved queries linked to a dashboard (`personaldashboard`, `transient_summary/<query>`, `query_api`) show only the transients the user may see, through `filter_query_results`. A query with no transient `id` column is refused for non-superusers.
- [ ] The legacy YSE-only pages in open question 1 are superuser-only.
- [ ] Legacy cron ingesters are out of `CRON_CLASSES`, and #89 is filed for the ATLAS/ZTF rewrite.
- [ ] The ETL queries run on the local production restore. Dave has assigned groups there, and the visibility checks pass on that copy.
- [ ] `ruff check .` passes; unit tests and the API integration test pass.

## Verification

- `python manage.py test YSE_App` with the local MySQL test account (see `local-unit-tests` notes).
- On the local production restore: run the migrations, then the ETL queries; assign groups; log in as a superuser, a group-A user, and an outside user, and click through the dashboard, candidate dashboard, search, detail pages (reported and unreported), TNS pages and the API browser.
- `tests/integration` against the local stack, for the API parity test.

## Open questions

1. ~~Legacy YSE-only surfaces~~: decided (Dave), all hidden (`@superuser_required`). Follow-up and the observing calendar come back later, modeled properly, in their own enhancement. The list:
   - YSE survey planning: `yse_home`, `yse_planning`, `yse_fields`, `yse_sky`, `select_yse_fields`, `move_yse_field`, `msb_detail`, `yse_pointings*`, `adjust_yse_pointings*`, `yse_msb_change`, `view_yse_fields`, the `toggle*`/`get*Verts`/`initDraw*` helpers, `return_serialized_transients`.
   - Observing: `calendar`, `observing_calendar`, `too_calendar`, `yse_observing_calendar`, `decam_observing_calendar`, `yse_oncall_calendar`, `observing_night`, `yse_observing_night`, `too_requests`, `download_target_list`, `download_targets_and_finders`, `followup`, and the resource/survey/on-call forms.
   - Ingest and other: `add_yse_survey_obs`, `add_yse_survey_fields`, `add_gw_candidate`, `ztf_forced_phot`, `dashboard_example`, `archived`.
   - **Not hidden:** `personaldashboard` renders the dashboard-linked queries ([views.py:187](YSE_App/views.py#L187)), so it stays and gets the filtered queries (#5).
   - The static `surveypages` (survey, news, team, contact, acknowledgements) show no data and stay as they are.
2. ~~Legacy cron ingesters~~: decided, see #6b.
3. **Hosts with no linked transient:** there's no host detail page, but hosts can still be reached through `/api/hosts/` and `get_host/<ra>/<dec>/<sep>`, and both return coordinates. A host linked to a hidden transient gives its position away, so `get_host`, `/api/hosts/` and host photometry and spectra omit hosts whose linked transients are all hidden from the user. Catalog-only hosts (no transient): decided (Dave), visible to everyone, as catalog galaxies with nothing proprietary; easy to tighten later.
4. ~~Editing~~: decided, Full access for every write; otherwise an admin. Checked on the production restore (2026-11-17): 20 of 21 users are staff, 9 are superusers, and no model permissions have been granted to any user or group, so the admin is in practice superuser-only. **Before sharing:** the 9 superusers bypass every group, so check that list.
5. ~~Group membership on upload~~: decided, only one's own groups or `Public`.
6. ~~Delivery~~: decided, one PR built in phases (commits): 1 `TransientService`, model and rule + tests → 2 read paths, writes and the URL sweep → 3 uploads and the cron removal → 4 orphaned grid, TNS report changes, Explorer, docs → 5 "Resolve on TNS" (#88). The PR closes #86 and #88.
7. ~~Who may run "Resolve on TNS"~~: decided (Dave), users with Full access who are also in "TNS Reporters" (#52), plus superusers. Making data public is publishing, like reporting.
8. **Match tolerances for "Resolve on TNS"** (the same rule decides "matches ours" and "we don't have it"): decided (Dave), set them empirically. Start from 0.01 d / same band (via the #52 filter map) / 0.05 mag for photometry, and 0.01 d / same instrument for spectra. Compare against our reported transients on the production restore, then adjust and record the values here.

## Log

- **2026-11-17:** Requirements settled with Dave (see "The rule"). Changes to the issue text: (a) existing data gets its groups from a manual ETL step, not a Django data migration; (b) hidden or missing transient → one well-formatted 404 page (a 403 was discussed; Dave was fine with either); (c) a reserved `Public` group replaces "no group" as the way to share with everyone.
- **2026-11-17 (plan review 1, Dave):** Only TNS-reported data goes `Public`, picked by the user after matching it to TNS's record ("Match TNS"), not automatically at write-back. `TransientService` is the upstream service, and every related model routes through it. A superuser-only orphaned grid for ungrouped transients. Legacy cron ingestion is removed, with an issue for rewriting ATLAS/ZTF forced photometry. Writes need Full access, and admins fix other people's uploads. Uploaders assign only their own groups. One PR, in phases. Found during review: `query_api` and dashboard queries run saved Explorer SQL, so they're locked down with Explorer.
- **2026-11-17 (plan review 2, Dave):** Dashboard-linked queries stay available, with their results filtered down to visible transients by `TransientService.filter_query_results` (Dave's idea). Legacy pages are hidden. Hosts linked only to hidden transients are omitted. Decorators and mixins apply the rule per route. Match tolerances are set empirically. On the production restore, a `Public` group already exists (the migration uses `get_or_create`), along with 12 legacy YSE groups with 1 member each. "Match TNS" is open to Full-access TNS Reporters plus superusers. The ATLAS/ZFPS rewrite is filed as #89: public data, always tagged `Public`. `personaldashboard` stays visible, because it renders the filtered queries. Catalog-only hosts stay visible to everyone. Every open question is now decided.
- **2026-11-17 (plan review 3, Dave):** #88 ("Resolve on TNS" button) is folded in as phase 5, because "Match TNS" was most of it: one fetch, one matching rule, one page. It's a left-nav batch page plus a detail-page button. The lookup is read-only, and Apply writes: the IAU name, `Public` on ticked matches, and add-only import of ticked TNS photometry. Imported instruments and bands come from the TNS values snapshot (#52's label match reversed, creating what's missing). Photometry only; TNS spectra become a follow-up issue. It uses `tns_client.py`, not the legacy `tnsAPI.py` that #88 suggested.
- **2026-11-17 (plan review 4, Dave):** TNS spectra import filed as #90. A "TNS Integration" submenu (Resolve, Report, Status), with a new `TNSResolveAttempt` model so the status page shows resolves next to reports. An "Admin" submenu for superusers only (Django admin, Groups & users, Explorer, Orphaned transients). The calendars stay out of it: they're YSE-era pages, hidden under #86, and come back with the follow-up/observing enhancement.
- **2026-11-17 (phase 1 build):**
  - Group checks are subqueries on the M2M table (`pk__in` the through rows), not joins, so no `.distinct()` is needed and the querysets stay safe to count, annotate and order.
  - The photometry and spectra rule is `TransientService.authorized_data()`. The two services keep their public function names (about 30 call sites), and both copies of `GetUserGroupQuery` are gone.
  - `get_visible_or_404` became `find_visible_transient(user, slug)`, which returns None like `find_transient`. Rendering the 404 page needs the request, so that's the phase 2 decorator's job.
  - Found: `ObservingResourceService.py` has a third copy of the old rule, for telescope resources on the hidden legacy pages; left as is and filed as #91 (tech-debt). And `PhotometryService.GetAuthorizedHostPhotData_ByPhotometry` was broken (it filtered `HostPhotometry` on `photometry__id` and `HostPhotData` on `pk`, swapped) with no callers; removed (Dave). Checked on the production restore after migrating: Public reused, a non-superuser sees only the one TNS object and no photometry (fails closed), queries take about 0.01 s.
