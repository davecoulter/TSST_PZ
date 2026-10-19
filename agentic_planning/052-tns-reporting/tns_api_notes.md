# TNS API notes for #52

Distilled on 2026-10-19 from Dave's local TNS bot code: `tns_api_bulk_report.py`, adapted from TNS's own example by Nikola Knezevic, 2021, and `make_json_dave_edit.py`. The code itself wasn't kept because it held bot credentials. Nothing here is secret: the bot ID and name show up on every report.

References: TNS bulk report manual, https://www.wis-tns.org/sites/default/files/api/tns2_manuals/TNS2.0_bulk_reports_manual.pdf; group IDs, https://www.wis-tns.org/groups.

## Hosts and bot

| | Host | Bot |
|---|---|---|
| Sandbox | `https://sandbox.wis-tns.org` | `TSST_COSMOS_bot` (ID 193638); own sandbox key |
| Production | `https://www.wis-tns.org` | `TSST_COSMOS_bot` (ID 193638); own production key |

Keys live only in the server ini. The keys that were in the shared script should be regenerated (2026-10-19).

## Requests

Every request is a form POST (`application/x-www-form-urlencoded`, or multipart for files) with this header:

```
User-Agent: tns_marker{"tns_id": "193638", "type": "bot", "name": "TSST_COSMOS_bot"}
```

| What | Endpoint | Form fields | Success |
|---|---|---|---|
| Send AT report(s) | `POST /api/set/bulk-report` | `api_key`, `data` = the report JSON as a string | 200; `data.report_id` |
| Get the outcome | `POST /api/get/bulk-report-reply` | `api_key`, `report_id` | 200; `data.feedback` per entry. **404 = not processed yet**: retry. |
| Enumerations | `POST /api/get/values` | `api_key` | 200; `data.{at_types, units, groups, instruments, filters, archives, ...}` as `{id: label}` |
| Attach files | `POST /api/set/file-upload` | `api_key`, `files[i]` | not needed for #52 |

The script read failures as follows. If the response body is JSON, it has `id_code` and `id_message`. Otherwise the HTTP status: 403 Forbidden, 500 server error, 503 unavailable. The script polled the reply every 5 s, with a 30 s total.

Note: the repo's legacy `YSE_App/util/tnsAPI.py` builds `<base>/api/bulk-report`, an older URL shape. The script needed `set` → `get` for the reply endpoint ("Dave HACK").

## Report JSON (`data` field)

```json
{
  "at_report": {
    "0": {
      "ra":  {"value": "10:00:43.24"},
      "dec": {"value": "+02:26:43.05"},
      "reporting_groupid": "170",
      "data_source_groupid": "170",
      "reporter": "D. A. Coulter, on behalf of the TSST and COSMOS 3D teams.",
      "discovery_datetime": "2023-12-24",
      "at_type": "1",
      "host_name": "optional",
      "host_redshift": "optional, only if > 0",
      "internal_name": "optional: our Transient.name",
      "remarks": "optional",
      "non_detection": {"archiveid": "0", "archival_remarks": "..."},
      "photometry": {
        "0": {"obsdate": "2023-12-24", "flux": "26.6", "flux_error": "0.1",
              "flux_unitid": "1", "filterid": "102", "instrumentid": "185"},
        "1": {"obsdate": "2023-12-24", "flux": "27.9", "flux_error": "0.3",
              "flux_unitid": "1", "filterid": "0", "instrumentid": "185",
              "comments": "Filter is JWST-NIRCam-F090W. "}
      }
    },
    "1": { "...": "next transient" }
  }
}
```

- RA and Dec are sexagesimal strings, zero-padded (`HH:MM:SS.ss`, `±DD:MM:SS.ss`).
- `non_detection` takes one of two forms:
  - **Observation:** `{obsdate, flux_unitid, filterid, instrumentid}`, optionally with a limiting flux.
  - **Archive:** `{archiveid, archival_remarks}`. Archives are 0 Other, 1 SDSS, 2 DSS. The script's remark: "This source was not detected in Public Release IMaging for Extragalactic Research images (PRIMER; Cycle 1, GO 1837; https://primer-jwst.github.io/observations.html)."
- `photometry`:
  - Entry `"0"` is the discovery band.
  - The other bands measured at the same epoch follow, with the same units and instrument.
  - Dates were whole days in the script. TNS also accepts fractional days or times; check the manual.
- **Filter not in TNS's list:** send `filterid` "0" (Other), plus a `comments` value naming the instrument and filter.
- **IDs:** the script resolved every ID from the values list by matching labels (`'PSN'` matches `'PSN - Possible SN'`), and hardcoded none.

## IDs we use (from the 2025-06-18 values snapshot, `tns_values_2025-06-18.json`)

| Field | ID | Label |
|---|---|---|
| Group (reporting and data source) | 170 | TSST_COSMOS_3D |
| AT type | 1 | PSN - Possible SN |
| Units | 1 | ABMag |
| Instrument | 185 / 186 / 187 / 188 | JWST - NIRCam / NIRSpec / NIRISS / MIRI |
| Filters | 102 F115W, 103 F150W, 100 F200W, 104 F277W, 106 F335M, 105 F356W, 107 F410M, 101 F444W | `<band>-JWST` |
| Filter not listed (e.g. F090W) | 0 | Other, plus a comment |
| Archive | 0 | Other |
