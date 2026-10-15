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
| `quality_flag` | The reviewer's confidence: **1 definite, 2 probable, 3 possible**, one per candidate (the page shows it as "Saved · Q1"). Who posts is the reviewer: each user posts their own choices with their own login, so the posting user is the reviewer. Stored as **text in a comment**, `quality_flag: 3; notes: <notes>` (a part is left out when empty); not an enum. |
| `notes` | Free text from the Save dialog. Becomes a **comment by the posting user**; an identical comment by that user on that object is not added twice. |
| `fitsmap_url` | URL of the FitsMap view. Stored as a second web resource (source "FitsMap"). |
| `tags` | Strings from the Save dialog (a drop-down or radio choice for consistent names). Matched (ignoring case and whitespace) to existing **candidate tags**, or created. |
| `host` | `null`, or `{host_id, host_ra, host_dec, host_z, host_z2, host_sep, host_catalog}`. See below. |
| `fits` values | Stored as given. A URL is shown as a link. A plain path (the pipeline's `/astro/...` paths, meaningful only on the network) is shown as **copyable text** (for DS9 and the like) unless it falls under a configured path-to-URL prefix map on the server (`path prefix -> URL prefix`), in which case it is shown as a link too. PNG stamps are already URLs. |

`host`: `host_id` (integer) and `host_ra`, `host_dec` (degrees) are required. `host_catalog` is the catalog's **file name**, as the pipeline knows it (agreed with Justin 2026-10-15; a nickname such as "JADES" is set on the server side, not sent); until the pipeline sends it, the server assumes the **JADES** catalog and says so in `warnings`. `host_z` is the median of the photo-z PDF and is stored as the host's photo-z. No error or PDF is sent yet. `host_z2` (the maximum likelihood estimate) and `host_sep` are accepted and not stored, and produce no warning (the separation is worked out from the positions). A host is matched by catalog and ID, then by position, else created.

Reply additions: `host` (`{"result": "created" | "matched" | "kept", "name", "catalog", "catalog_object_id", "matched_by" ("catalog id" or "position"), "separation_arcsec"}`; `kept` means the object already had a different host, which was **not** replaced and the offered one was **not** stored, with its separation) and `warnings` (list of strings; also per result in the array form). The `diffpype` web resource's text is `candidate id · run_id · field` when the run and field are sent.

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

## Notes on the photometry (v1.3)

- `flux`, `flux_err`, `mag` and `mag_err` are **measurements at the candidate's position**. `upper_limit: true` is the pipeline's interpretation. STZ-PZ also treats a point with S/N < 3 as a limit, and shows the limit as the 3-sigma limiting magnitude worked out from `flux_err` (`flux_zero_point - 2.5 log10(3 flux_err)`), not as the measured magnitude.
- `mjd` is the mid-exposure time in UTC. A `null` stamp or FITS entry means no such image exists (the page shows "NOT PROVIDED").
- Candidate IDs are salted per run and runs know nothing of each other; STZ-PZ links them by position (0.2 arcsec).
- If a detection has `flux` but no `mag`, STZ-PZ works the magnitude out the way the pipeline does: AB from the zero point (`flux_zero_point - 2.5 log10(flux)`, flux in uJy with zero point 23.9) and `mag_err = 2.5 log10(1 + flux_err/flux)`, and says so in `warnings`. Limits are never given a magnitude. (Checked against the pipeline's own numbers: they match to the last digit.)

