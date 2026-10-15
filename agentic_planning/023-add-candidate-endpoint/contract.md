# STZ-PZ `/add_candidate/` payload (v1.3)

This is what the websniff **Save candidate** button (or a notebook or script) POSTs to STZ-PZ for one candidate. It is one JSON object per candidate. A full example is in `add_candidate_example.json`; it uses the real candidate `jwst_5324_trig2_jw05324-o017_t014_nircam_clear_1`, with its diff-image magnitudes from the page. The MJD, stamp URLs and FITS paths are placeholders.

- **Request:** `POST /add_candidate/`, `Content-Type: application/json`, HTTP basic auth (the user's STZ-PZ login).
- **Response:** `201` created a new candidate, or `200` appended to an existing one, as JSON: `{"result": "created"|"appended", "transient": "<name>", "url": "/transient_detail/<slug>/", "match_separation_arcsec": <float|null>, "photometry_added": <int>, "photometry_superseded": <int>}`. `400` with `{"errors": {...}}` for a bad payload (nothing is saved). `401`/`403` for a bad login.

STZ-PZ matches each POST to existing objects within **0.2″**. A later run that detects the same source under a new `candidate_id` is appended to the same object. The client doesn't need to know what STZ-PZ already holds.

## Several candidates in one request (v1.1)

The body may also be a **JSON array** of candidate objects (the objects above). Each candidate is independent: it is validated and saved in its own transaction, in order (a later one can match an earlier one), and one that fails does not stop or undo the others. The reply is always `200` (for a well-formed request) and says what happened to each:

```json
{"summary": {"created": 2, "appended": 0, "failed": 1},
 "results": [
   {"index": 0, "candidate_id": "…_0", "status": 201, "result": "created", "transient": "…_0",
    "url": "/transient_detail/…_0/", "match_separation_arcsec": null,
    "photometry_added": 4, "photometry_superseded": 0},
   {"index": 1, "candidate_id": "…_1", "status": 400, "errors": {"ra": "required"}},
   {"index": 2, "candidate_id": "…_2", "status": 200, "result": "appended", "…": "…"}]}
```

Each result carries the HTTP status that a single POST of that candidate would have returned, plus the same fields. An empty array, or more than 500 candidates, is a `400` for the whole request. A single object behaves exactly as in v1.0.

## Dry run (v1.2)

Add `?dry_run=1` to the URL (`POST /add_candidate/?dry_run=1`, single object or array). The server runs the whole request, including the match and the create-or-append logic, and then rolls it back. The reply is exactly what a real run would return, plus `"dry_run": true` (and in the array form, `"dry_run": true` in `summary`), but **nothing is saved**: no transient, photometry, tags or aliases. Use it to find out whether a file would be accepted, and what it would create or append to.

## v1.3 (2026-10-15): what the websniff page sends

The contract follows what the pipeline's page actually emits; the field names below are Justin's. Nothing is accepted silently: the reply carries a `warnings` list for anything ignored or assumed.

| Field | Meaning and handling |
|---|---|
| `quality_flag` | The reviewer's confidence (e.g. 1 real, 2 maybe, 3 not real). Stored as **text in a comment**, `quality_flag: 3; notes: <notes>` (a part is left out when empty); not an enum. |
| `notes` | Free text from the Save dialog. Becomes a **comment by the posting user**; an identical comment by that user on that object is not added twice. |
| `fitsmap_url` | URL of the FitsMap view. Stored as a second web resource (source "FitsMap"). |
| `tags` | Strings from the Save dialog. Matched (ignoring case and whitespace) to existing **candidate tags**, or created. |
| `host` | `null`, or `{host_id, host_ra, host_dec, host_z, host_z2, host_sep, host_catalog}`. See below. |
| `fits` values | URLs preferred (files go to the central store, linked from the web). A plain path is still stored as given. |

`host`: `host_id` (integer) and `host_ra`, `host_dec` (degrees) are required. `host_catalog` names the catalog (e.g. `"JADES"`); until the pipeline sends it, the server assumes **JADES** and says so in `warnings`. `host_z` is stored as the host's photo-z. `host_z2` and `host_sep` are accepted and not stored, and produce no warning (the separation is worked out from the positions). A host is matched by catalog and ID, then by position, else created.

Reply additions: `host` (`{"result": "created" | "matched" | "kept", ...}`; `kept` means the object already had a different host, which was **not** replaced, with the separation of the one that was offered) and `warnings` (list of strings; also per result in the array form).

The v1.0 to v1.2 host fields (`name`, `ra`, `dec`, `photo_z`, ...) are replaced; no client used them.

## Top level

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `candidate_id` | string | yes | The pipeline's ID for this detection (unique per run). It becomes the object's name the first time; later IDs are kept as aliases. |
| `ra`, `dec` | float, deg (ICRS) | yes | Candidate position. |
| `permalink` | string (URL) | yes | The websniff page URL with the `#candidate_id` anchor. |
| `source` | string | no | Pipeline name, recorded as the source of the permalink. Default `"diffpype"`. |
| `run_id` | string | no | Reduction run, e.g. `"jwst_5324_trig2"`. |
| `field` | string | no | Field or visit, e.g. `"jw05324-o017_t014_nircam_clear"`. |
| `telescope` | string | no | Default `"JWST"`. |
| `instrument` | string | yes | e.g. `"NIRCam"`, `"MIRI"`. Must already exist in STZ-PZ. |
| `tags` | list of strings | no | Extra STZ-PZ tags (must already exist). `"Candidate"` is added automatically. |
| `host` | object or `null` | no | `null` when there's no host match. See below. |
| `photometry` | list | yes (≥1) | One entry per filter per epoch. See below. |

## `host`

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `name` | string | yes | Host catalog name/ID. |
| `ra`, `dec` | float, deg | yes | Host position. |
| `photo_z`, `photo_z_err` | float | no | Photometric redshift and 1σ error. |
| `redshift`, `redshift_err` | float | no | Spectroscopic redshift and 1σ error. |
| `catalog` | string | no | Source of the redshift(s), e.g. `"JADES"`. |

```json
"host": {"name": "JADES-12345", "ra": 189.21961, "dec": 62.16722,
         "photo_z": 0.81, "photo_z_err": 0.05, "redshift": null, "redshift_err": null,
         "catalog": "JADES"}
```

## `photometry[]`

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `band` | string | yes | Filter, e.g. `"F200W"`. |
| `mjd` | float | yes | Mid-exposure MJD (UTC). |
| `flux`, `flux_err` | float | yes* | Difference-image flux and 1σ error, in `flux_unit`. |
| `flux_unit` | string | yes | `"uJy"` preferred. |
| `flux_zero_point` | float | no | AB zero point for `flux_unit` (23.9 for µJy). |
| `mag`, `mag_err` | float | no | AB magnitude and error, if computed. |
| `upper_limit` | bool | yes | `true` for a non-detection. |
| `limit_sigma` | number | if limit | The σ level of the limit (e.g. 3). |
| `stamps` | object | no | PNG URLs `{"sci", "ref", "diff"}` for this filter and epoch, as shown on the page. |
| `fits` | object or `null` | no | Paths or URLs `{"sci", "ref", "diff"}` of the FITS images this point came from. |

\* For a non-detection, send `upper_limit: true`, `flux` (may be `null`) and `flux_err`, plus `mag` set to the limiting magnitude and `limit_sigma`:

```json
{"band": "F444W", "mjd": 61102.41532, "flux": null, "flux_err": 0.0010, "flux_unit": "uJy",
 "flux_zero_point": 23.9, "mag": 29.80, "mag_err": null, "upper_limit": true, "limit_sigma": 3,
 "stamps": {"sci": "…", "ref": "…", "diff": "…"}, "fits": null}
```

## Notes

- Re-sending the same `band` and `mjd` for an object replaces the earlier point. The old one is kept but flagged "Superseded".
- Never send `created_by`, `status` or a `name`; STZ-PZ sets these.
- v1.0 was frozen 2026-10-14 so diff_pype and STZ-PZ could be built in parallel. v1.1 (2026-10-14, Dave) adds the array form, and v1.2 (2026-10-14, Dave) adds `?dry_run=1`; nothing else changed, and single objects work as before. Any further change is a new version, agreed by both sides and noted here.
