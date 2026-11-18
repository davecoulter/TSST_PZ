# 086: Test checklist

Every surface #86 touches, what its test checks, and where the test is. Updated as each part lands.
Unit tests are in `YSE_App/test_visibility.py` unless noted; run them with
`docker exec -w /app tsstpz_web_container python3 manage.py test YSE_App --settings=YSE_PZ.local_test_settings --noinput`.

**The fixture** (`VisibilityTestBase`):
- **Users:** one in group A, one in group B, one in no group, and a superuser.
- **Transients:** restricted to A, restricted to B, A's reported to TNS (`2026abc`), `Public`, A + `Public`, and one with no group.
- **Data:** photometry and spectra in `Public`, in A, and with no group, including a `Public` point on a hidden transient.
- **Hosts:** linked to hidden transients, linked to visible ones, and catalog-only.

Status: ✅ done · ⏳ to write (part named) · 🧪 manual check on the production restore.

## The rule (phase 1)

| Surface | Checks | Test | Status |
|---|---|---|---|
| Which transients a user sees | own groups + `Public` + TNS objects; no group = superusers only; anonymous = `Public` + TNS objects | `TransientRuleTests.test_each_user_sees_…`, `test_no_group_means_superusers_only`, `test_anonymous_users_…` | ✅ |
| Access levels | FULL / TNS object / none, per user and transient | `TransientRuleTests.test_access_levels`, `test_full_access_leaves_out_…` | ✅ |
| Writes (`can_edit`) | `Public` grants reading only; TNS objects are read-only to outsiders | `TransientRuleTests.test_public_grants_reading_only` | ✅ |
| Querysets | no duplicate rows; a queryset passed in is narrowed, not replaced | `TransientRuleTests.test_no_duplicate_rows_…`, `test_a_queryset_passed_in_…` | ✅ |
| Finding by slug, alias or name | hidden = not found | `TransientRuleTests.test_a_hidden_transient_is_not_found_…` | ✅ |
| Rows hanging off a transient | follow the transient | `TransientRuleTests.test_rows_hanging_off_a_transient_follow_it` | ✅ |
| Photometry and phot data | own group **and** a visible transient; no group = superusers only | `DataRuleTests` (4 tests) | ✅ |
| Spectra | the same rule | `DataRuleTests.test_spectra_follow_the_same_rule` | ✅ |
| Hosts and host photometry | follow their transients; catalog-only hosts open | `HostRuleTests` (2 tests) | ✅ |
| Roles | groups that grant permissions aren't data groups; `mutate_tns_metadata` from "TNS Reporters", superusers have it | `RolesTests` (2 tests) | ✅ |
| Comments | own group **and** a visible target (transient, photometry, ...) | `MetadataRuleTests.test_comments_need_…` | ✅ |
| Follow-ups | own group **and** a visible transient | `MetadataRuleTests.test_follow_ups_need_…` | ✅ |
| Rule on the production restore | non-superusers see only TNS objects until groups are assigned; query time | — | 🧪 done 2026-11-17 (0.01 s) |

## Phase 2: reads

| Surface | Checks | Test | Status |
|---|---|---|---|
| `@transient_access` | hidden id = 404; TNS object at FULL level = 403 | `AccessDecoratorTests` | ✅ |
| Transient and candidate detail pages | hidden = the 404 page by slug, alias or name, with no coordinates; missing = the same page | `TransientPagesTests.test_a_hidden_transient_is_the_not_found_page_…` | ✅ |
| Detail page as a TNS object | facts shown; private comment and diff stamp hidden; the owner sees both | `TransientPagesTests.test_a_tns_object_shows_its_facts_…` | ✅ |
| Transients near the host | hidden names left out | `TransientPagesTests.test_the_transients_near_the_host_…` | ✅ |
| Candidate dashboard | hidden candidates left out | `TransientPagesTests.test_the_candidate_dashboard_…` | ✅ |
| Spectrum plots, candidate SED | login needed; hidden id = 404 | `TransientPagesTests.test_plots_by_id_need_…` | ✅ |
| TNS report form | only photometry the reporter can see | `test_tns_report.TransientFieldsTests` (now with groups), `EndpointsTests.test_the_tns_form_offers_only_…` | ✅ |
| Dashboard table columns | Last Mag / Last Obs. Date / Disc. Mag from visible photometry only | `ListsTests.test_photometry_columns_…` | ✅ |
| Sorting by those columns | no private values leak through the order | `ListsTests.test_sorting_by_last_mag_…` | ✅ |
| Main dashboard, search by name and by coordinates | hidden transients left out | `ListsTests.test_search_and_the_dashboard_…`, `test_search_by_coordinates_…` | ✅ |
| Archived dashboard | hidden transients left out | `EndpointsTests.test_the_archived_page_and_count_…` | ✅ |
| Sidebar badges | counts per user | `ListsTests.test_the_sidebar_counts_…`, `EndpointsTests.test_the_archived_page_and_count_…` | ✅ |
| Search by tag | hidden transients left out | `ListsTests.test_search_by_tag_…` | ✅ |
| Saved queries (`filter_query_results`) | names narrowed to what the user may see | `ListsTests.test_saved_query_results_…` | ✅ (through the pages, including `query_api`'s raw rows for superusers only: 🧪 on the production restore, because the test database has no `explorer` connection) |
| `transient_summary` | filtered list; sorting by Last Mag / Last Obs. Date uses visible values | `EndpointsTests.test_transient_summary_…` | ✅ |
| Exports (`download_data`, `download_photometry`, `download_spectra`) | hidden = 404; only visible photometry | `EndpointsTests.test_exports_…` | ✅ (`download_bulk_photometry` runs saved SQL: 🧪) |
| `data_utils` lookups (`get_transient`, `get_new_transients_box`, `get_host`) | hidden transients and their hosts left out | `EndpointsTests.test_lookups_…` | ✅ (`get_rising_transients*` and `box_search`: covered by the URL sweep, part 4) |
| The `view_utils` endpoints (light curves, SALT2, finder charts, images, rise/set, moon, airmass) | login needed; hidden id = 404 | `EndpointsTests.test_plot_and_image_endpoints_…` | ✅ (rise/set/moon/airmass take an observing night too: URL sweep, part 4) |

## Phase 2: API and writes (part 3)

| Surface | Checks | Status |
|---|---|---|
| API default | `IsAuthenticated`; schema and root open; every other endpoint refuses anonymous users | ⏳ |
| `TransientViewSet` and the viewsets hanging off transients | list and detail filtered; hidden = 404 | ⏳ |
| Serializer related fields | can't link a comment or photometry to a hidden transient; the error doesn't reveal that it exists | ⏳ |
| API writes (`PUT`/`PATCH`) | need `can_edit`; a TNS object = 403 | ⏳ |
| Curating (status, tags, fields, follow-ups) | needs `curate_transients` **and** a non-`Public` group of the transient: a group member without the role gets a 403; a curator in another group gets a 403 (or a 404 if hidden); a superuser always passes; edit controls hidden otherwise | ⏳ |
| Comments | anyone who can see the transient may comment, tagged with their own data groups and/or `Public`; only the author or a superuser edits or deletes it | ⏳ |
| Follow-up requests | only resources in the user's groups are offered **and** accepted; the status change happens through the curator rule | ⏳ |
| Observing resources (#91) | follow the group rule; need a data group | ⏳ |
| Comment and follow-up forms | group checkboxes, `Public` included, author's data groups pre-ticked, at least one required | ⏳ |
| API parity (integration, `tests/integration`) | `groups` written and read back on transients, comments and follow-ups | ⏳ |

## Phase 3: uploads

| Surface | Checks | Status |
|---|---|---|
| `add_transient`, `add_transient_phot`, `add_transient_spec`, `upload_spectrum` | need `curate_transients` and a group of the transient; refused without a group, with an unknown group, a role group, a group the uploader isn't in, or `Public` | ⏳ |
| Candidate ingest endpoint and both CLIs (`--groups`) | the same | ⏳ |
| API serializers' `create()`/`update()` | the same | ⏳ |
| Admin | at least one group required | ⏳ |
| Comments created by code (candidate ingest, follow-up forms, legacy TNS submit) | get a group | ⏳ |
| Legacy crons | out of `CRON_CLASSES` | ⏳ |

## Phase 4: the rest

| Surface | Checks | Status |
|---|---|---|
| Legacy YSE pages | superuser-only | ⏳ |
| Explorer | superuser-only | ⏳ |
| TNS pages | `mutate_tns_metadata`; superusers pass; the select page lists only transients the user can edit | ⏳ |
| Orphaned grid | superusers only; lists every transient with no group; bulk assign | ⏳ |
| "Release to Public" admin action | superuser-only; adds `Public` to the transient and all its photometry, spectra and follow-ups | ⏳ |
| Choosing `Public` for data | refused to curators on upload and on the API; allowed only through release paths and to superusers | ⏳ |
| Navigation | the TNS Integration and Admin submenus show only to the right users | ⏳ |
| **URL sweep, logged in** | every URL as a group-B user: A's name, slug and coordinates in no response; skips listed with reasons | ⏳ |
| **URL sweep, logged out** | every URL: a login redirect or 401/403, except the listed exceptions | ⏳ |
| ETL on the production restore | queries run; groups assigned; the checks above pass on that copy | 🧪 ⏳ |
