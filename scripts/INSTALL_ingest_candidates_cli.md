# Posting candidates to STZ-PZ: install `ingest_candidates_cli.py`

`ingest_candidates_cli.py` reads candidate JSON files and posts them to STZ-PZ. The server does the matching and the create-or-append; the script reads your files, sends them in batches and tells you what happened to each candidate. It uses only the Python standard library, so there is nothing to `pip install`.

This page covers:

1. [What you need](#1-what-you-need)
2. [Install it](#2-install-it)
3. [Check it, then post](#3-check-it-then-post)
4. [If something goes wrong](#4-if-something-goes-wrong)
5. [Talking to the API without the script](#5-talking-to-the-api-without-the-script)
6. [The JSON payload (contract v1.3)](#6-the-json-payload-contract-v13)

The steps are for macOS and Linux (zsh or bash).

## 1. What you need

- **Python 3.** Any recent `python3` on your `PATH`. (It runs on the 3.8 in the project's image and on current releases.)
- **An STZ-PZ account of your own.** Ask an admin to create one (admin site, *Users*). Any active account can post. The account that posts is recorded as the creator of what is added and as the reviewer behind the `quality_flag` and `notes`, so do not share one login between people.
- **The address of the STZ-PZ you are posting to**, for example `https://<your STZ-PZ host>`, or `http://localhost:8001` for a local copy.
- **The script**, from a checkout of this repository: `scripts/ingest_candidates_cli.py`.

## 2. Install it

### 2.1 Put the script in an `STZPZ` folder

Any folder works. This page uses `~/STZPZ/bin`.

```bash
mkdir -p ~/STZPZ/bin
cp /path/to/TSST_PZ/scripts/ingest_candidates_cli.py ~/STZPZ/bin/
chmod +x ~/STZPZ/bin/ingest_candidates_cli.py
```

If you keep a checkout and want `git pull` to update the script, link it instead of copying:

```bash
ln -s /path/to/TSST_PZ/scripts/ingest_candidates_cli.py ~/STZPZ/bin/ingest_candidates_cli.py
```

### 2.2 Add the folder to your `PATH`

Add this line to `~/.zshrc` (macOS default), or `~/.bashrc` (Linux bash) or `~/.bash_profile` (macOS bash):

```bash
export PATH="$HOME/STZPZ/bin:$PATH"
```

Open a new terminal, or run `source ~/.zshrc` (use your own file).

### 2.3 Set your credentials in environment variables

The script reads three variables:

| Variable | Meaning |
|---|---|
| `YSE_URL` | The address of STZ-PZ, no trailing path. If unset the script uses `http://localhost:8001`. |
| `USER_YSE` | Your STZ-PZ username. There is no default. |
| `PW` | Your password. Optional: if it is not set the script asks for it, with the typing hidden. |

Add the first two to the same file as the `PATH` line:

```bash
export YSE_URL="https://<your STZ-PZ host>"
export USER_YSE="<your username>"
```

**Think before you store the password.** A `PW` line in `~/.zshrc` is your password in a plain text file that every program you run can read. The safer choices, in order:

1. Leave `PW` unset and type the password when asked. Best for hand use.
2. For a script or a cron job, keep it in its own file only you can read, and load it only when needed:

   ```bash
   install -m 600 /dev/null ~/STZPZ/credentials.sh
   echo 'export PW="<your password>"' >> ~/STZPZ/credentials.sh
   source ~/STZPZ/credentials.sh      # in the shell or script that posts
   ```

Never put the password in a file that is committed to git, and don't pass it with `--pw` on a shared machine (it shows in the process list).

## 3. Check it, then post

```bash
which ingest_candidates_cli.py          # should print ~/STZPZ/bin/ingest_candidates_cli.py
ingest_candidates_cli.py --help
```

**Always do a dry run first.** `--dry-run` makes the server run everything and then roll it back, so you see exactly what a real run would do (including problems such as an unknown instrument) and nothing is saved:

```bash
ingest_candidates_cli.py --dry-run candidates.json
```

```
Target: https://<your STZ-PZ host> as <your username> (dry run)
candidates.json [0] mytest_run1_cand_001  would create  mytest_run1_cand_001, 1 points, 0 superseded
    warning: mag worked out from flux for photometry[0]
1 candidate in 1 file: 1 would create, 0 would append, 0 failed, 1 warning (dry run, nothing saved)
```

Look at the `Target:` line before anything is sent: it names the server and the user. Then post for real:

```bash
ingest_candidates_cli.py candidates.json
```

Things to know:

- **A file holds one candidate object or an array of them** (the diff-imaging pipeline writes one array per run). See [section 6](#6-the-json-payload-contract-v13) if you need to write your own.
- **Each candidate is independent.** A bad one is reported by id, field and message, and the others are still saved.
- **Re-running a file is safe.** Points for the same band and epoch are marked `Superseded` on the server and not duplicated.
- **A real run creates real objects.** Don't use it to test; use `--dry-run`. If you do create a test object, ask an admin to delete it.
- **Where to look afterwards:** a new candidate appears on the *Candidates* page, in the **New** grid, and opens on its own candidate page from there. The `New` tag is its call to action: it stays until someone triages it.
- **Exit code:** `0` everything succeeded; `1` at least one candidate or file failed; `2` bad usage or the login was rejected. So it can sit in a shell script.
- Options: `--url`, `--user`, `--pw` (override the variables); `--batch-size` (candidates per request, default 100, at most 500); `--timeout` (seconds per request, default 120).

## 4. If something goes wrong

| You see | It means |
|---|---|
| `error: no username; set USER_YSE or pass --user` | `USER_YSE` is not set in this shell. Open a new terminal or `source` your profile. |
| `error: the server rejected the login (HTTP 401/403)` | Wrong username or password, or the account is inactive. Nothing was sent. Check the `Target:` line too: the account exists on that server only. |
| `could not reach the server: ...` | Wrong `YSE_URL`, no network or VPN, or the server is down. |
| `warning: ... is plain http, so your password and the data travel unencrypted` | The address starts with `http://` and is not your own machine. Use `https://` if the server has it. |
| `FAILED  photometry[0].mjd: required` (any `FAILED` line) | The payload is wrong at that field. See [section 6](#6-the-json-payload-contract-v13). |
| `FAILED  instrument: unknown instrument "X" on telescope "Y"` | STZ-PZ must already know the instrument. Ask an admin to add it. |
| `warning: host_catalog not given; assumed 'JADES'` | Your host block has no `host_catalog`. It was saved against JADES. Send the catalog's file name to avoid the assumption. |
| `warning: ignored unknown field '...'` | The payload has a top-level field STZ-PZ does not read. Usually a typo. |
| `warning: mag worked out from flux for photometry[N]` | A detection had `flux` but no `mag`; the server computed it (AB, zero point 23.9 for µJy). |
| `command not found: ingest_candidates_cli.py` | The `PATH` line is missing, the folder name is wrong, or the file is not executable (`chmod +x`). |

## 5. Talking to the API without the script

You can post from a notebook, a pipeline or `curl` with no websniff page involved, as long as the payload follows [section 6](#6-the-json-payload-contract-v13).

- **Request:** `POST {YSE_URL}/add_candidate/` with `Content-Type: application/json` and HTTP basic auth (your STZ-PZ username and password).
- **Dry run:** add `?dry_run=1`. Everything is evaluated and rolled back; the reply says what would have happened and has `"dry_run": true`.
- **Body:** one candidate object, or a JSON array of up to 500.
- **Use `https`.** Basic auth sends the password with every request.

```bash
curl -u "$USER_YSE" -H 'Content-Type: application/json' \
     -d @candidate.json "$YSE_URL/add_candidate/?dry_run=1"
```

(`-u "$USER_YSE"` makes curl ask for the password.)

```python
import requests
reply = requests.post(f"{url}/add_candidate/", params={"dry_run": 1},
                      json=payload, auth=(user, password), timeout=120)
print(reply.status_code, reply.json())
```

### Replies

**One object:**

| Status | Meaning | Body |
|---|---|---|
| `201` | A new candidate was created | `{"result": "created", "transient": "<name>", "url": "/transient_detail/<slug>/", "match_separation_arcsec": null, "photometry_added": 4, "photometry_superseded": 0, "host": {...}, "warnings": [...]}` |
| `200` | Appended to an existing candidate | the same with `"result": "appended"` and the separation of the match |
| `400` | Bad payload; **nothing is saved** | `{"errors": {"photometry[0].mjd": "required"}}` |
| `401` / `403` | No credentials / wrong credentials | |
| `405` | Not a POST | |

**An array:** the status is `200` for a well-formed request, and the body says what happened to each candidate (each has the status a single POST would have had):

```json
{"summary": {"created": 2, "appended": 0, "failed": 1},
 "results": [
   {"index": 0, "candidate_id": "x_0", "status": 201, "result": "created", "transient": "x_0", "...": "..."},
   {"index": 1, "candidate_id": "x_1", "status": 400, "errors": {"ra": "required"}}]}
```

An empty array, or more than 500, is a `400` for the whole request.

### How STZ-PZ treats a post

- **Matching:** a candidate is matched to an existing object with the same `candidate_id` (as its name or as an alias), otherwise to any object within **0.2 arcsec**. A match is appended to; no match creates a new object. Later runs have their own `candidate_id`s, and are linked by position.
- **Same epoch again:** a point for the same band within a second of an existing one replaces it. The old point is kept and flagged `Superseded`.
- **Never send** `created_by`, `status` or a `name`; STZ-PZ sets them.
- **Nothing is dropped silently.** Anything ignored or assumed comes back in `warnings`.

## 6. The JSON payload (contract v1.3)

This is a working summary. The authoritative version, with its history, is `agentic_planning/023-add-candidate-endpoint/contract.md`, and a complete example is `agentic_planning/023-add-candidate-endpoint/add_candidate_example.json`. Field names are those of the diff-imaging pipeline.

### A minimal candidate

```json
{
  "candidate_id": "mytest_run1_cand_001",
  "ra": 189.21972548,
  "dec": 62.16717944,
  "permalink": "https://example.org/my_candidates/page.html#mytest_run1_cand_001",
  "instrument": "NIRCam",
  "photometry": [
    {"band": "F150W", "mjd": 61102.41532, "flux": 0.0305, "flux_err": 0.002,
     "flux_unit": "uJy", "upper_limit": false}
  ]
}
```

### A fuller candidate (everything the websniff page sends)

```json
{
  "candidate_id": "mytest_run1_cand_002",
  "ra": 189.21972548,
  "dec": 62.16717944,
  "permalink": "https://example.org/my_candidates/page.html#mytest_run1_cand_002",
  "fitsmap_url": "https://example.org/fitsmap/?ra=189.2197&dec=62.1672",
  "source": "diffpype",
  "run_id": "mytest_run1",
  "field": "jw05324-o017_t014_nircam_clear",
  "telescope": "JWST",
  "instrument": "NIRCam",
  "tags": ["Young?"],
  "quality_flag": 2,
  "notes": "Compact, offset from the host nucleus.",
  "host": {"host_id": 12345, "host_ra": 189.21961, "host_dec": 62.16722, "host_z": 0.81,
           "host_catalog": "jades_dr3_nircam.fits"},
  "photometry": [
    {"band": "F150W", "mjd": 61102.41532, "flux": 0.0305, "flux_err": 0.002,
     "flux_unit": "uJy", "flux_zero_point": 23.9, "mag": 27.69, "mag_err": 0.07,
     "upper_limit": false, "limit_sigma": null,
     "stamps": {"sci": "https://example.org/s_sci.png", "ref": "https://example.org/s_ref.png",
                "diff": "https://example.org/s_diff.png"},
     "fits": {"sci": "/path/to/sci.fits", "ref": "/path/to/ref.fits", "diff": "/path/to/diff.fits"}},
    {"band": "F444W", "mjd": 61102.41532, "flux": null, "flux_err": 0.0010, "flux_unit": "uJy",
     "flux_zero_point": 23.9, "mag": 29.80, "mag_err": null,
     "upper_limit": true, "limit_sigma": 3, "stamps": null, "fits": null}
  ]
}
```

### Top-level fields

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `candidate_id` | string, up to 64 | yes | Your ID for this detection. It becomes the object's name the first time; later IDs for the same source are kept as aliases. |
| `ra`, `dec` | float, degrees (ICRS) | yes | Position. `ra` in [0, 360), `dec` in [-90, 90]. |
| `permalink` | string | yes | URL of the page that shows the candidate. Must be `http://` or `https://`. |
| `instrument` | string | yes | e.g. `"NIRCam"`, `"MIRI"`. Must already exist in STZ-PZ (with its telescope). |
| `photometry` | list | yes, at least 1 | One entry per band per epoch. See below. |
| `telescope` | string | no | Default `"JWST"`. |
| `source` | string | no | Name of your pipeline, recorded as the source of the permalink. Default `"diffpype"`. |
| `run_id`, `field` | string | no | The reduction run and the field or visit. |
| `fitsmap_url` | string | no | A FitsMap view of the candidate (`http(s)`); saved as a web resource named FitsMap. |
| `tags` | list of strings | no | Candidate tags. Matched to existing ones (ignoring case and spaces) or created. A new candidate also gets the tag `New` automatically. |
| `quality_flag` | 1, 2 or 3 | no | The reviewer's confidence: **1 definite, 2 probable, 3 possible**. The posting user is the reviewer. Saved as a comment, `quality_flag: 2; notes: ...` (the range is not checked: whatever you send is saved as text). |
| `notes` | string, up to 4000 | no | Free text. Saved as a comment by the posting user (an identical comment is not added twice). |
| `host` | object or `null` | no | The host galaxy. See below. |

Any other top-level field is ignored, with a warning.

### `host`

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `host_id` | integer | yes | The host's ID in its catalog. |
| `host_ra`, `host_dec` | float, degrees | yes | Host position. |
| `host_z` | float | no | Median of the photo-z PDF; saved as the host's photo-z. |
| `host_catalog` | string | no | The catalog's **file name**. If missing, STZ-PZ assumes JADES and warns. |
| `host_z2`, `host_sep` | float | no | Accepted and not stored. |

A host is matched by catalog and ID, then by position, else created. The first host of an object stays: a different host sent later is reported as `kept`, not swapped in. The reply's `host` says `created`, `matched` or `kept`.

### `photometry[]`

| Field | Type | Req. | Meaning |
|---|---|---|---|
| `band` | string | yes | Filter, e.g. `"F200W"`. Unknown bands are created for a known instrument. |
| `mjd` | float | yes | Mid-exposure MJD, UTC. |
| `flux`, `flux_err` | float | see below | Difference-image flux and 1-sigma error, in `flux_unit`. |
| `flux_unit` | string | yes | `"uJy"` preferred (`"nJy"` is also understood). |
| `flux_zero_point` | float | no | AB zero point for `flux_unit`. If missing: 23.9 for `uJy`, 31.4 for `nJy`. |
| `mag`, `mag_err` | float | no | AB magnitude and error. If a detection has `flux` but no `mag`, STZ-PZ computes them (and warns). |
| `upper_limit` | `true` / `false` | yes | `true` for a non-detection. |
| `limit_sigma` | number | if `upper_limit` | The sigma level of the limit (e.g. 3). |
| `stamps` | object or `null` | no | PNG URLs `{"sci", "ref", "diff"}` for this band and epoch. |
| `fits` | object or `null` | no | URLs or paths `{"sci", "ref", "diff"}` of the FITS images. A path (meaningful only on your network) is shown as copyable text. |

- A **detection** needs `flux` (with `flux_err`) or `mag` (with `mag_err`).
- An **upper limit** needs `limit_sigma`, and `flux_err` or a limiting `mag`. Send `mag` as the limiting magnitude and leave `flux` as `null` if there isn't one.
- STZ-PZ also treats any point with S/N below 3 as a limit when it displays it, whatever `upper_limit` says; the limit is drawn as the 3-sigma limiting magnitude from `flux_err`.
- A `null` stamp or FITS entry means that image does not exist.
- All numbers must be finite (no `NaN` or `Infinity`); send `null` instead.

### Versions

`v1.0` (2026-10-14) first frozen; `v1.1` adds the array form; `v1.2` adds `?dry_run=1`; `v1.3` (2026-10-15) adds what the websniff page sends (`quality_flag`, `notes`, `fitsmap_url`, `tags`, the new `host` block, `warnings`). Further changes are a new version, agreed by both sides and recorded in `contract.md`.
