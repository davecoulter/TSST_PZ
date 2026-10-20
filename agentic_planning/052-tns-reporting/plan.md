# 052: Report candidates to TNS in bulk

- **Issue:** #52 (part of #16)
- **Branch:** `52-tns-reporting` (merged with `master` 2026-10-20, which has #29's `Transient.iau_name` and #22's forms fix). Local Claude is the writer from 2026-10-20.
- **Status:** Approved by Dave 2026-10-20 with the amendments below; building in stages (one PR)

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
| 2 | **TNS client** `YSE_App/tns_client.py` | Small, tested client for the TNS 2.0 API as Dave's bot script uses it: `POST /api/set/bulk-report` (form fields `api_key`, `data` = the JSON), `POST /api/get/bulk-report-reply` (`api_key`, `report_id`; 404 means not ready yet), `POST /api/get/values`, all with the `User-Agent: tns_marker{"tns_id": ..., "type": "bot", "name": ...}` header. The legacy `YSE_App/util/tnsAPI.py` posts to the older URL shapes, so it isn't reused. Two targets, each with its own bot ID, name and key in the server ini: `[tns_sandbox]` and `[tns_production]`. |
| 3 | **`TNSReportAttempt` model** + migration | transient, created_by, created_date, base URL used, report ID, status (pending / reported / failed), payload sent, response received (both as JSON text, so no jsonfield dependency), error message, IAU name returned. One row per transient per submission. |
| 4 | **Writing back** | On "reported": set `transient.iau_name` through `save()`, which moves the slug and keeps the old URL working (#29). |
| 5 | **Failure flag** | The detail page and candidate page show a "TNS report failed" label while the latest attempt failed, and a "TNS reports" box listing every attempt (time, who, status, report ID, TNS's message, payload on click). |
| 6 | **Pages and nav** | Select, details, confirm modal, results. Same look as the candidate pages. |
| 6b | **TNS values** | `manage.py sync_tns_values [--target sandbox\|production]` calls `/api/get/values` and writes `YSE_App/data/tns_values.json` (committed; starts from Dave's 2025-06-18 download). Forms read the file, so page loads never call TNS. |
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
- **Asynchronous reply, handled synchronously.** TNS returns a report ID right away and the outcome later. After submitting, the request asks for the reply every 5 s for up to 30 s (Dave's script's values; a 404 means "not ready"), and stops early on a rate-limit response. Anything still pending shows a "Check again" button. Nothing runs on a timer (Dave: TNS throttles strictly).
- **Defaults from Dave's bot code.** Reporting and data-source group: `TSST_COSMOS_3D` (TNS group 170). AT type: PSN. Instrument: `JWST - NIRCam` (185). Units: ABMag. Filters are looked up by name (`F200W-JWST`, ...); a band TNS doesn't list (e.g. F090W) is sent as filter "Other" (0) with the comment `Filter is JWST-NIRCam-F090W`, as his script does. Non-detection is either an observation (date, filter, instrument, limiting mag) or archival (archive "Other" plus a remark, e.g. the PRIMER sentence his script used). All IDs come from the values snapshot, not from code.
- **Photometry.** Like his script, the report carries every band measured at the discovery epoch, with the discovery band first.

## Decisions

1. **Reporters** (Dave): a free-text reporters field on the form, prefilled with `D. A. Coulter, on behalf of the TSST and COSMOS 3D teams.` (from his script) and editable. **Who can open the page** (Dave): a "TNS Reporters" group plus superusers.
2. **Enumerations** (resolved): TNS publishes them at `/api/get/values`, so a sync command refreshes a committed snapshot, as in 6b.
3. **Shared vs per-transient fields** (Dave): shared are reporting group, data-source group, reporters, AT type, instrument, units, and the non-detection method with its default archival remark. Per transient: discovery date and photometry (prefilled from our data, editable), non-detection details when it's an observation, host name and z, and remarks. The internal name is always `Transient.name`.
4. **Pending replies** (Dave): synchronous polling plus a "Check again" button; no cron.
5. **Target** (Dave, revised 2026-10-20): each deployment decides. A setting `TNS_TARGET = sandbox | production` (default sandbox) selects which `[tns_sandbox]` or `[tns_production]` keys are used; there is no dropdown. A local stack and any test site post to the sandbox; only the production server is set to production, once, at setup. Every TNS page shows a prominent SANDBOX or PRODUCTION banner, and the confirmation modal repeats it (red for production). A dropdown fed by the configured sections can come later if needed.

## Amendments (2026-10-20, after review with Dave)

1. **A report in flight blocks a second one.** The select grid leaves out transients whose latest attempt is pending. Submitting re-checks and locks the selected rows inside one transaction, so two reporters at once cannot send the same transient twice.
2. **While an attempt is pending, `iau_name` cannot be changed by hand.** The admin "(edit name)" form shows it read-only with the reason, and the API refuses a change (serializer validation). The write-back never overwrites a name that was set meanwhile: it marks the attempt "reported, name differs" (TNS's name and ours both shown) for a person to resolve.
3. **"Check again"** asks TNS for the reply of one pending attempt, any number of times. It is rate-limited on the server (`last_checked` on the attempt; a minimum gap between checks, so repeated clicks do nothing and TNS is not hammered). An attempt that never resolves can be marked **abandoned** by a superuser (admin action), and a pending attempt older than a day shows a "pending for more than a day" label. Status values: pending, reported, failed, abandoned.
4. **The key is sent, never stored.** TNS takes two form fields: `api_key` and `data`. What we store as "payload sent" is the `data` JSON (no key in it) and the reply TNS returned. The whole request is never logged.
5. **Not an API.** This is a workflow for people. `TNSReportAttempt` gets no serializer and no `/api/` route (the "API parity" rule in `CLAUDE.md`: not exposed, on purpose), so we do not shadow TNS's own API.
6. **Live payload preview.** The details form shows, beside the fields, exactly what will be sent: a table with the TNS enumeration labels (not just ids) and the raw JSON, built by the same function that builds the real submission, with missing required fields flagged. The confirmation modal shows it again.
7. **Build in stages, one PR.** Commits in this order, so a reviewer can read them one at a time:
   1. The TNS values snapshot and its loader (the enumerations), then the payload builder as a tested pure function.
   2. The select grid and the details form with the live preview, and the page permission ("TNS Reporters" group plus superusers). **No submit yet:** Dave looks at the payload and says which fields are wrong or missing.
   3. The TNS client, sandbox submit, `TNSReportAttempt`, polling, "Check again", and the IAU write-back.
   4. The failure flag and attempt history on the detail pages, and the nav entry.
8. **Integration tests, not only unit tests.** A small fake TNS server (started by the tests, replaying real sandbox responses, including "not ready" 404s, per-entry errors and a rate limit) lets the whole flow run in `tests/integration` against the live stack with no internet or credentials: select, preview, submit, poll, write back, lock. The base URL is configurable for this. A manual run against the real sandbox, from Dave's local stack, confirms the fake matches reality; the recorded responses come from that run. (The automated sandbox job is #53.)

## Acceptance criteria

- [ ] Only TNS reporters see the nav entry and can open the pages; others get 403.
- [ ] Selecting several candidates, filling the form, confirming and submitting sends one bulk report to the configured TNS (sandbox by default).
- [ ] Each reported transient gets its `iau_name` (and its URL moves); each failure is recorded with TNS's message and flagged on the detail page.
- [ ] Pending reports resolve without a page reload or a restart.
- [ ] Dropdowns use the TNS values snapshot; nothing hardcodes our group or authors.
- [ ] No TNS credential in the DB, UI or repo.
- [ ] End-to-end test on the TNS sandbox: report two candidates, one valid and one deliberately broken, and see one IAU name and one flagged failure.
- [ ] A transient with a pending attempt cannot be selected, and cannot have its IAU name changed from the admin or the API; two simultaneous submissions send it once.
- [ ] "Check again" cannot be hammered (server-enforced gap); an unresolved attempt can be abandoned; the TNS key never appears in the DB, the logs or a stored payload.
- [ ] The details form previews the exact payload, with enumeration labels, before anything is sent; every TNS page shows the sandbox or production banner.
- [ ] The whole flow passes in `tests/integration` against the fake TNS server, and once by hand against the real sandbox.
- [ ] `TNSReportAttempt` is not exposed through the API.
- [ ] Migration ships in the PR; `ruff check .` passes; no dependency or image change.

## Verification

- Unit tests: `python manage.py test YSE_App` (#22 is merged; locally this needs the one-time test-database grant in `docker/README.md`), and the integration tests in `tests/integration` against the fake TNS server.
- Sandbox run on the local stack with the sandbox bot in `settings.ini`, as in the last acceptance criterion.

## Log
- **2026-10-18:** Plan drafted, so it's ready for Dave's session tonight with the AZ collaborators.
- **2026-10-19:** Revised from Dave's answers and his TNS bot code (`tns_api_bulk_report.py`, `make_json_dave_edit.py`, `values.json`): TNS 2.0 endpoints, the values endpoint, group 170, JWST IDs, the filter-"Other" convention, and 5 s / 30 s reply polling. Cron dropped.
- **2026-10-19:** Dave confirmed decision 3 (shared vs per-transient split as proposed) and page access ("TNS Reporters" group plus superusers). Dave will regenerate the TNS bot keys that were in his shared script.
- **2026-10-20:** Dave approved the plan with amendments (the section above): a pending-report guard and row lock that also covers the manual and API name edits, a rate-limited "Check again" with an abandon action, the key sent but never stored, no API exposure, the target chosen by the deployment (`TNS_TARGET`), a live payload preview, one PR built in four stages with a checkpoint where Dave reviews the payload before anything can be sent, and integration tests against a fake TNS server plus a manual sandbox run. Project Claude is not needed for the build (it needs Dave's local stack and sandbox bot); it can review the PR at the end. Model and effort for the build: Opus 5.5 at high (a report to TNS cannot be unsent).

