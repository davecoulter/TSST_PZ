# 029: Internal name plus IAU name

- **Issue:** #29 (part of #16; #52 builds on it)
- **Branch:** `29-iau-name`
- **Status:** Built (2026-10-17); tested 2026-10-19 on Dave's local MySQL stack (11 integration tests, and Dave in the browser); ready for PR

## Why

A candidate starts with our internal name and may later get an IAU name from TNS. `Transient` has one `name`, and its slug (the URL) is an `AutoSlugField` filled from `name` on create only. We want the IAU name to lead everywhere once it exists, without breaking ingest, the API, or any URL already handed out under the internal name. Separately, a detail URL for a transient that doesn't exist crashes with a 500.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | **`Transient.iau_name`** | `CharField(max_length=64, null=True, blank=True, unique=True)` plus its migration. Null means "no IAU name yet", so existing rows need no backfill; MySQL allows many NULLs under a unique index. `name` stays the internal name, unchanged. |
| 2 | **`display_name`** | Model property `iau_name or name`, and a queryset helper that annotates `display_name=Coalesce('iau_name', 'name')` so sorting and filtering in the DB follow the same rule. |
| 3 | **Slug follows the IAU name** | In `Transient.save()`: when `iau_name` is newly set or changed, add the current slug as an `AlternateTransientNames` alias (name = internal name, slug set explicitly to the old slug), then set `slug` from `iau_name`. The detail and candidate views already redirect an alias slug to the transient's current slug (`views.py` `transient_detail`, `candidate_views.candidate_detail`), so old URLs keep working with no new routing. |
| 4 | **Internal name always resolves** | Belt and braces for 3: if a slug matches neither a transient nor an alias, try `Transient.name` (internal) and `iau_name` case-insensitively, then redirect to the current slug. |
| 5 | **Friendly not-found page** | `transient_detail` (and the other slug views in `views.py` that index `transient[0]`) return a 404 page instead of an `IndexError`: "No transient named X in STZ-PZ", plus a link to search TNS for X (`https://www.wis-tns.org/search?name=X`) and a link back to search. One small template. |
| 6 | **Grids show the display name** | The name column in `table_utils.py` tables, the candidate dashboard cards, and the detail-page header show the display name, with the internal name underneath in small text when the two differ. Sorting on name uses the annotated `display_name`. |
| 7 | **Search by either name** | The main search (`views.py` simple name search) and the candidate dashboard filter match `name` or `iau_name`. |
| 8 | **API** | `iau_name` is in the transient serializer (it uses `fields = "__all__"`, so it appears automatically) and is writable. |
| 8b | **Edit link on the detail page** (Dave) | For staff only, a small "(edit name)" link right after the title on the detail and candidate pages (first built as "Edit in admin" under the title) opens the stock Django admin change form for that transient (already registered in `admin.py`) in a popup window via `?_popup=1`, so the user never leaves the detail page. A few lines of JS on the detail page define `dismissChangeRelatedObjectPopup`, which admin calls after save: it closes the popup and reloads the page, landing on the new slug if the IAU name changed. No custom form. |
| 9 | **Tests** | Unit tests for 1 to 4 and 7: slug change, alias creation, old URL redirect, internal-name redirect, unknown name gives 404, search by both names. |

Out of scope:
- Submitting to TNS and the admin reporting page (#52).
- CI that runs these tests against MySQL (#53). Until then they run on Dave's local stack.
- Legacy YSE TNS cron jobs in `data_ingest/TNS_uploads.py`, which rename transients their own way. Not touched; flag if they're still enabled in TSST.
- Templates outside the candidate pages and the shared tables that print `transient.name` (24 template files mention it). They keep showing the internal name for now; follow-up if any matter.

## Design notes

- **Why keep `name` as the internal name** rather than renaming it to `internal_name`: `name` is used by ingest, `/add_candidate/`, the CLI, the serializers, `find_by_name` and dozens of templates. A rename touches all of them for no behavior gain. A nullable `iau_name` is additive and safe.
- **Why reuse `AlternateTransientNames`** for old URLs: it already has its own slug and both detail views already redirect from it, so we add zero routing code. The candidate page already lists aliases as runs, so the internal name will also show there once it's an alias. Deliverable 3 makes sure that doesn't double-list (the internal name is `name`, already first in the runs list).
- **IAU name format.** Store TNS's bare designation (`2026abc`), not `AT 2026abc`/`SN 2026abc`: the prefix flips from AT to SN on classification, and the old YSE code stored bare names too. The slug then becomes `2026abc`.
- **Detecting a change in `save()`.** Compare against the value loaded from the DB (cached in `from_db`/`__init__`), so it costs no extra query and works for both API and admin saves.

## Acceptance criteria

- [x] Migration adds `iau_name` (nullable, unique) and nothing else; existing rows are untouched.
- [x] Setting `iau_name` changes the slug to it, and the old slug redirects to the new one.
- [x] `/transient_detail/<internal name>/` and `/candidate/<internal name>/` resolve (redirect) after the IAU name is set.
- [x] An unknown name gives the 404 page with the TNS link, not a 500.
- [x] Shared tables, candidate dashboard and detail header show the IAU name first, internal name second; sorting by name uses the display name.
- [x] Search finds a transient by either name.
- [x] `iau_name` can be set through the API, and through the admin popup from the detail page (staff only), which reloads the page on save.
- [x] `ruff check .` passes; no dependency or image change.

## Verification

On Dave's local stack after `python manage.py migrate`:
- Pick a candidate, set `iau_name` via the API (`PATCH /api/transients/<id>/`) or admin.
- Open its old URL: redirects to `/transient_detail/<iau name>/`. Same for `/candidate/<internal name>/`.
- Check the candidate dashboard and transient tables: IAU name shown, internal name underneath.
- Search for each name: the transient comes up.
- Open `/transient_detail/does-not-exist/`: friendly 404 with a TNS link.
- `python manage.py test YSE_App` for the new unit tests. On a fresh test DB this stops at import time because `forms.py` reads `FollowupStatus 'Requested'` while the URLs load (#22); see the Log.
- On the detail page, as staff: "Edit in admin" opens a popup; set the IAU name and save; the popup closes and the page reloads at the new URL.

## Decisions

1. **Bare designation** (`2026abc`), as TNS stores it (Dave).
2. **No custom form:** a staff-only link to the stock admin change form in a popup (Dave).

## Log
- **2026-10-17:** Plan drafted from the issue conversation with Dave (on the go).
- **2026-10-17:** Dave settled the open questions: bare IAU designation; admin popup link instead of a custom form (8b).
- **2026-10-17:** Approved; built with Opus at high effort (Dave's OK).
- **2026-10-17:** How it was checked, without the Docker stack: a throwaway Python 3.8 venv in Claude's scratch space with the image's pins (Django 4.0, autoslug 1.9.8, tables2 2.4.0, ...) and the image's site-package patches, on SQLite. All migrations including 0009 apply; `makemigrations --check` reports no changes; the 12 new tests pass; the real pages were exercised (old URL, `AT 2026abc`, candidate URL, search, downloads, 404); and the "Edit in admin" popup was driven in headless Chromium: save closes the popup and the page reloads at the new slug. MySQL itself was not exercised.
- **2026-10-17 (finding):** `manage.py test` can't start on a fresh test DB: `forms.py` indexes `FollowupStatus.objects.filter(name='Requested')[0]` at import (#22), and the test DB has no rows. The scratch run used a local runner that seeds the row first (not committed). Fixing #22 is a prerequisite for running these tests anywhere, including CI (#53).
- **2026-10-17:** Also routed through `find_transient`: the download views, `ztf_forced_phot` and the `get_transient` API, so a renamed transient's old slug or internal name still works there (and a missing one is a 404, not a 500).
- **2026-10-17:** Transient is now registered with a `TransientAdmin` that uses raw ID widgets for `host` and `best_spectrum`, so the popup doesn't render every host in a dropdown, and searches both names.
- **2026-10-17:** Known edge, not handled: if another transient already has the slug `2026abc` (e.g. a legacy one named after the IAU designation), the renamed one gets `2026abc-2` and `/transient_detail/2026abc/` shows the other. Merging duplicates is out of scope.
- **2026-10-17 (inferred):** The 404 page's TNS link searches by `name=` for IAU-looking names and `internal_name=` otherwise; those parameter names are from TNS's search form as I know it, not checked against the live site.
- **2026-10-19 (finding, fixed):** Dave migrated his local MySQL (0009) and restarted web. Integration tests written against the live stack (`tests/integration/test_iau_name.py`, 11 tests; they use the API to set the name, as the admin popup's save does through the model) found that **`iau_name` could not be set through the API**: `TransientSerializer.update()` copies a fixed list of fields by hand, so a PATCH with `iau_name` returned 200 and wrote nothing. The Log entry above, and deliverable 8, were wrong to say `fields = "__all__"` made it writable: that only makes it appear in responses. Fixed with one line in `update()` (null still clears the name). After the fix all 11 pass on MySQL, including: a second transient taking the same IAU name gets a 400, also when the letter case differs (MySQL's collation is case-insensitive); a renamed transient can be deleted (its alias row goes with it); clearing the name restores the internal slug and the IAU slug then redirects to it. The SQLite check did not catch this because it never went through the API.
- **2026-10-19 (finding, not fixed here):** the same pattern exists in two serializers from #50: `HostSerializer.update()` never writes `catalog` or `catalog_object_id`, and `TransientTagSerializer.update()` never writes `kind`. Proposed to Dave as a separate issue and branch, not part of #29.
- **2026-10-19:** Dave tested in the browser on the local stack: "Edit in admin" popup saves, closes and reloads at the new URL, and the new name shows on the page and in the grid in real time. All acceptance criteria are met (the API one after the serializer fix above). Follow-ups filed, not part of this PR: #54 (the same API bug for Host.catalog, Host.catalog_object_id and TransientTag.kind) and #55 (tech debt: generate serializer updates). Dave found the "Edit in admin" link under the title easy to miss.
- **2026-10-19:** Link moved and renamed at Dave's request: a small "(edit name)" directly to the right of the title on both the transient detail page and the candidate page (the old link under the title is gone). Same popup, same behavior. Checked by rendering both pages as a staff user and by Dave in the browser ("things look great"); the 11 integration tests still pass.

