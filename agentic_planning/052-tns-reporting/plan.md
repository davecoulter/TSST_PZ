# 052: Report candidates to TNS in bulk

- **Issue:** #52 (part of #16)
- **Branch:** `52-tns-reporting`, built off `29-iau-name` (needs `Transient.iau_name`); rebase onto `master` once #29 merges
- **Status:** Draft, awaiting Dave's approval and the decisions below

## Why

Discoveries are reported to TNS one at a time today, by hand or with the legacy `YSE_App/util/submit_to_tns.py` (hardcoded DECam payload, author lists, group 83). TSST needs to report a batch of JWST candidates from the app, get back their IAU names, and see what failed.

## Flow

1. **Select** (`/tns/report/`): "Report to TNS" in the left nav, visible only to TNS reporters (decision 1). A grid of candidates with no `iau_name`, filterable by candidate tag and status, with a checkbox per row and "select all in this group".
2. **Details** (`/tns/report/details/`): one form for the shared fields, then one row per selected transient with its prefilled, editable values (decision 3 for which fields).
3. **Confirm:** a modal lists what will be sent: count, names, sandbox or production, reporting group.
4. **Submit:** one TNS bulk report for the whole batch (TNS accepts several AT reports in one submission and returns one report ID).
5. **Results** (`/tns/report/<attempt batch>/`): each transient as reported (with its new IAU name), pending, or failed (with TNS's message). Pending ones resolve on their own (decision 4).

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 1 | **Payload builder** `YSE_App/tns_report.py` | Pure function: transient + shared fields → one `at_report` entry. RA/Dec (sexagesimal), discovery date, discovery photometry, last non-detection (or "archival" when there is none), reporter list, group, AT type, internal name (`Transient.name`), host name and z, remarks. Unit-tested on its own; no hardcoded authors or groups. Replaces nothing yet: the legacy `submit_to_tns.py` stays untouched. |
| 2 | **TNS client** | Reuse `YSE_App/util/tnsAPI.py` (`addBulkReport`, `getBulkReportReply`) as is, with the bot name, ID and key from settings (`tns_bot_name`, `tns_bot_id`, `tnsapikey`, already read from the server ini). A new `tns_base_url` ini setting chooses sandbox or production; default sandbox. |
| 3 | **`TNSReportAttempt` model** + migration | transient, created_by, created_date, base URL used, report ID, status (pending / reported / failed), payload sent, response received (both as JSON text, so no jsonfield dependency), error message, IAU name returned. One row per transient per submission. |
| 4 | **Writing back** | On "reported": set `transient.iau_name` through `save()`, which moves the slug and keeps the old URL working (#29). |
| 5 | **Failure flag** | The detail page and candidate page show a "TNS report failed" label while the latest attempt failed, and a "TNS reports" box listing every attempt (time, who, status, report ID, TNS's message, payload on click). |
| 6 | **Pages and nav** | Select, details, confirm modal, results. Same look as the candidate pages. |
| 7 | **Tests** | Payload builder (dates, photometry choice, non-detection fallback, remarks), the TNS reply parser (success, per-entry error, still processing) with recorded responses, permission checks on the pages, write-back of `iau_name`. No live TNS calls in unit tests. |

Out of scope:
- Classification reports (TNS "classification" type) and FRBs: AT reports only.
- Retiring the legacy `submit_to_tns.py` and its URL. Separate cleanup issue once this is in use.
- The CI job against the TNS sandbox (#53). Until then, the sandbox test is manual.

## Design notes

- **Credentials.** Reports go out as a TSST bot account. The key stays in the server ini (never the DB or the UI); hashing can't work because TNS needs the raw key with each request. Sandbox and production need separate bot accounts.
- **Discovery photometry.** Default: the first detection at S/N ≥ 5 (superseded points excluded), reported as AB magnitude, with the band mapped to TNS's filter ID. The last point before it below the detection threshold is the non-detection, with its limiting magnitude. Both are editable on the details form.
- **Dates.** TNS takes `YYYY-MM-DD.ddddd` (fractional day). This is a tested helper. The legacy code pads the fraction wrongly: 0.05 of a day becomes `.50`. Inferred from `submit_to_tns.py`, not verified against TNS's records.
- **Remarks.** Prefilled from the candidate's comments on its detail page (the newest first, trimmed to TNS's length limit) and editable per transient.
- **Asynchronous reply.** TNS returns a report ID right away and the outcome later. After submitting, the page polls the reply for up to ~20 s; anything still pending is picked up by a `django_cron` job every few minutes (django_cron is already installed and used), and the results page has a "check again" button.

## Decisions (recommendation first)

1. **Who can report.** A Django group "TNS Reporters" (plus superusers), so collaborators can report without full admin rights. The alternative is staff only.
2. **Enumerations** (groups, AT types, filters, instruments, units). A committed JSON snapshot of the values we use, plus a `manage.py sync_tns_values` command that refreshes it from TNS. The form reads the snapshot, so a page load never calls TNS. **Needs from Dave:** the TNS getting-started guide or values list (offered earlier), and our group ID.
3. **Per-transient vs shared fields.** Shared: reporting group, reporters, AT type, instrument, proprietary period, units. Per transient: discovery and non-detection photometry, host, remarks.
4. **Pending replies.** A cron job plus a manual "check again" button, as above. The alternative is button only.
5. **Default target.** Sandbox, until `tns_base_url` in the ini points at production. The confirm modal says which one in red when it's production.

## Acceptance criteria

- [ ] Only TNS reporters see the nav entry and can open the pages; others get 403.
- [ ] Selecting several candidates, filling the form, confirming and submitting sends one bulk report to the configured TNS (sandbox by default).
- [ ] Each reported transient gets its `iau_name` (and its URL moves); each failure is recorded with TNS's message and flagged on the detail page.
- [ ] Pending reports resolve without a page reload or a restart.
- [ ] Dropdowns use the TNS values snapshot; nothing hardcodes our group or authors.
- [ ] No TNS credential in the DB, UI or repo.
- [ ] End-to-end test on the TNS sandbox: report two candidates, one valid and one deliberately broken, and see one IAU name and one flagged failure.
- [ ] Migration ships in the PR; `ruff check .` passes; no dependency or image change.

## Verification

- Unit tests: `python manage.py test YSE_App` (needs #22 merged to run on a fresh DB).
- Sandbox run on the local stack with the sandbox bot in `settings.ini`, as in the last acceptance criterion.

## Log
- **2026-10-18:** Plan drafted, so it's ready for Dave's session tonight with the AZ collaborators.
