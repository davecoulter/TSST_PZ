# 029: Internal name plus IAU name

- **Issue:** #29 (part of #16; #52 builds on it)
- **Branch:** `29-iau-name`
- **Status:** Draft, awaiting Dave's approval

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
| 8 | **API** | `iau_name` is in the transient serializer (it uses `fields = "__all__"`, so it appears automatically) and is writable, which is how it gets set until #52 exists. Also editable in Django admin. |
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

- [ ] Migration adds `iau_name` (nullable, unique) and nothing else; existing rows are untouched.
- [ ] Setting `iau_name` changes the slug to it, and the old slug redirects to the new one.
- [ ] `/transient_detail/<internal name>/` and `/candidate/<internal name>/` resolve (redirect) after the IAU name is set.
- [ ] An unknown name gives the 404 page with the TNS link, not a 500.
- [ ] Shared tables, candidate dashboard and detail header show the IAU name first, internal name second; sorting by name uses the display name.
- [ ] Search finds a transient by either name.
- [ ] `iau_name` can be set through the API and admin.
- [ ] `ruff check .` passes; no dependency or image change.

## Verification

On Dave's local stack after `python manage.py migrate`:
- Pick a candidate, set `iau_name` via the API (`PATCH /api/transients/<id>/`) or admin.
- Open its old URL: redirects to `/transient_detail/<iau name>/`. Same for `/candidate/<internal name>/`.
- Check the candidate dashboard and transient tables: IAU name shown, internal name underneath.
- Search for each name: the transient comes up.
- Open `/transient_detail/does-not-exist/`: friendly 404 with a TNS link.
- `python manage.py test YSE_App` for the new unit tests.

## Open questions

1. Bare designation (`2026abc`) as recommended, or with prefix (`AT 2026abc`)?
2. Should the detail page get a small "set IAU name" field for admins now, or is API + admin enough until #52?

## Log
- **2026-10-17:** Plan drafted from the issue conversation with Dave (on the go).
