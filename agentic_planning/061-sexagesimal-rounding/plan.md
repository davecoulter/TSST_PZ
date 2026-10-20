# 061: Fix GetSexigesimalString rounding

- **Issue:** #61 (found during #52; the follow-up sweep of hand-written formatting is #62)
- **Branch:** `61-sexagesimal-rounding`, from `master`
- **Status:** Approved by Dave 2026-10-20, as issue #61 describes; built.

## Why

`YSE_App/common/utilities.GetSexigesimalString` formats every RA/Dec the app shows: 27 call sites, including the transient, host and survey-field models' display methods. TNS reports (#52) send its output too. It formats RA seconds from astropy's `.hms` with `%05.2f`, which never carries, and the Dec sign is wrong when the Dec rounds to zero.

What it printed before the fix:

| Input (deg) | Before | After |
|---|---|---|
| RA 150.24998333 (10:00:59.996) | `10:00:60.00` | `10:01:00.00` |
| RA 359.9999999 | `23:59:60.00` | `00:00:00.00` |
| RA 14.99999999 | `00:59:60.00` | `01:00:00.00` |
| Dec -0.0000001 | `-00:00:00.00` | `+00:00:00.00` |
| Dec +02:26:59.996 | `+02:27:00.00` (already correct) | unchanged |
| Dec 87.81666481559884 (316139.9933") | `+87:49:00.00` | `+87:48:59.99` |

astropy alone is not the fix: astropy 5.0's `to_string(sep=':', pad=True)` prints RA 359.9999999° as `24:00:00.00`.

## Scope

- Round once, in integer hundredths of a second (of time for RA, of arc for Dec), then split into h/m/s. Seconds carry, RA wraps at 24 h, and a Dec that rounds to zero is `+`.
- Same signature and output format (`HH:MM:SS.ss`, `±DD:MM:SS.ss`), so no caller changes. All callers pass degrees as floats.
- Unit tests for the cases above and ordinary values, plus a check that ordinary output is unchanged.

Out of scope: the legacy scripts that format coordinates by hand (#62); the model or API layer.

## Acceptance criteria

- [x] The table's "After" column holds, in unit tests.
- [x] Output for ordinary coordinates is unchanged (same as before the fix for a spread of values away from rounding edges).
- [x] `ruff check .` passes; no dependency change; no migration.

## Log
- **2026-10-20:** Built. The baseline run showed that Dec seconds already carried (astropy's `to_string` rounds the Dec before splitting it), while RA did not.
- **2026-10-20:** Regression check: old and new on 200,000 random coordinates. There were 31 differences, every one a fix, and none larger than 0.01".
  - **RA (14):** all the `60.00` bug.
  - **Dec (17):** a second, smaller bug. Seconds just under a whole minute were rounded up to it by astropy's `to_string(precision=2)` (e.g. `+87:49:00.00` for 87°48'59.993"). That case is now a test.
  - **Tests:** 6 new; all 28 `YSE_App` tests pass on local MySQL; `ruff check .` passes.
