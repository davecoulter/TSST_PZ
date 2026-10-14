# STZ-PZ `/add_candidate/` payload (draft v0.1)

This is what the websniff **Save candidate** button (or a notebook or script) POSTs to STZ-PZ for one candidate. It is one JSON object per candidate. A full example is in `add_candidate_example.json`; it uses the real candidate `jwst_5324_trig2_jw05324-o017_t014_nircam_clear_1`, with its diff-image magnitudes from the page. The MJD, stamp URLs and FITS paths are placeholders.

- **Request:** `POST /add_candidate/`, `Content-Type: application/json`, HTTP basic auth (the user's STZ-PZ login).
- **Response:** `201` created a new candidate, or `200` appended to an existing one, as JSON: `{"result": "created"|"appended", "transient": "<name>", "url": "/transient_detail/<slug>/", "match_separation_arcsec": <float|null>, "photometry_added": <int>, "photometry_superseded": <int>}`. `400` with `{"errors": {...}}` for a bad payload (nothing is saved). `401`/`403` for a bad login.

STZ-PZ matches each POST to existing objects within **0.2″**. A later run that detects the same source under a new `candidate_id` is appended to the same object. The client doesn't need to know what STZ-PZ already holds.

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
- Field names may still change before v1.0; feedback welcome.
