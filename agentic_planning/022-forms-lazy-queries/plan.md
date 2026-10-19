# 022: No database queries at import time in forms.py

- **Issue:** #22 (tech-debt)
- **Branch:** `22-forms-lazy-queries`
- **Status:** Draft, awaiting Dave's approval

## Why

Several form classes in `YSE_App/forms.py` query the database in their class body, so the queries run once, when Django first imports the URLs (`urls.py` → `views.py` → `forms.py`). This has two effects:

1. **Crash on an empty database.** `TransientFollowupForm` evaluates `FollowupStatus.objects.filter(name='Requested')[0]`. A fresh test DB or a new install has no such row, so the import raises `IndexError` and nothing loads, including `manage.py test`. Found while building #29, and it blocks the CI in #53.
2. **Frozen choices.** Values computed at import never change until gunicorn restarts. Inferred from the code, not observed on the server:
   - `TransientFollowupForm`: the "valid since yesterday" cutoff for classical resources is fixed at startup, so resources keep showing after they expire. The default resource and its dates are those of startup.
   - `SurveyFieldForm`, `OncallForm`: the `instrument` / `user` field only exists if matching rows existed at startup, and its default is fixed.
   - `SurveyObsForm`: the ZTF field ID choices are a list built at startup.
   - `SpectrumUploadForm`: the group choices are a list built at startup.

Plain querysets passed to a field (e.g. `FollowupStatus.objects.all()`) are fine: Django re-evaluates them for each form. Only evaluated values (`[0]`, `len()`, lists, `timezone.now()`) are the problem.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | **Move evaluated queries into `__init__`** | For the five forms above, declare the fields statically and fill `queryset`, `choices` and `initial` in `__init__`, so they're computed per form instance. A missing "Requested" status leaves `initial` empty instead of crashing. The two fields that exist only when matching rows exist (`instrument` in `SurveyFieldForm`, `user` in `OncallForm`) keep that rule, but decide it per form instance in `__init__` instead of at import: when there are matching rows, replace the field as the class body does today (same position); when there are none, do nothing. With no matching rows the form is then exactly what it is today. For `SurveyFieldForm` that means Django's auto-generated `instrument` field (every instrument, required, because `SurveyField.instrument` is a required foreign key listed in `Meta.fields`), not an empty optional dropdown. |
| 2 | **Same rendered forms** | Same field names, order, widgets, `required` flags and defaults as today when the data is the same. No template, view, model or dependency change. |
| 3 | **Tests** | In `YSE_App/tests.py`: importing `YSE_App.urls` on an empty test DB works; `TransientFollowupForm()` defaults to "Requested" when it exists and to nothing when it doesn't; a classical resource created after import shows up in a new form. Removes the need for the seeding runner used for #29. |

Out of scope:
- The hardcoded lists in `SpectrumUploadForm` / `AutomatedSpectrumRequest` (`spec_instruments`, the obs group names). They are lazy querysets already.
- Other import-time work elsewhere in the app (e.g. astroplan `Observer.at_site` downloading site data). Separate issue if wanted.

## Acceptance criteria

- [ ] `python manage.py test YSE_App` runs on a fresh test DB with no seeded rows (and so do the #29 tests once both branches are merged).
- [ ] With the same data, the follow-up, survey field, survey obs, on-call and spectrum upload forms render as before.
- [ ] A classical resource added while the server runs appears in the follow-up form without a restart.
- [ ] `ruff check .` passes; no model, migration, dependency or image change.

## Verification

- `python manage.py test YSE_App` on the local stack.
- On the detail page, open the follow-up form: status defaults to Requested, and the classical resource list and dates match today's.
- Add a classical resource in the admin, reload the detail page without restarting: it's in the list.

## Log
- **2026-10-17:** Plan drafted after #29 found that `manage.py test` can't start on a fresh DB.
- **2026-10-19:** Plan corrected in review (before approval). The draft said the conditional fields would always exist with an empty queryset, "matching today". That is wrong for `SurveyFieldForm`: with no `GPC` instrument the declared field is absent and Django auto-generates a required dropdown of all instruments (the model field is a required FK and is in `Meta.fields`), so an always-declared, optional, empty field would break the Add Survey Field page. Deliverable 1 now keeps the rule but applies it per form instance.
