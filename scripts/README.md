# ingest_transients_cli.py

Bulk-uploads JWST transients and their light curves via the `/add_transient/` endpoint.

## Run

```bash
python scripts/ingest_transients_cli.py \
    --transient-list scripts/resources/jets_cands_labels.txt \
    --lightcurve-dir scripts/resources/ \
    --tags COSMOS \
    --telescope JWST \
    --instrument NIRCam
```

- The tags, telescope, and instrument must already exist in the DB (the dev seed
  data provides `JWST` with `NIRCam`/`NIRSpec`/`MIRI`/`NIRISS`).
- Multiple tags are passed space-separated: `--tags COSMOS JADES NEXUS`.
- Target/credentials default to `http://localhost:8000` / `djones` / `BossTent1`;
  override with `--url` / `--user` / `--pw` or env vars `URL` / `USER_YSE` / `PW`.

## `--mjdmatchmin` (default `0`)

With the default of `0`, every photometry row is appended as a new measurement —
re-running the script duplicates rows. If set higher (in days), an incoming row
whose band matches an existing row with an MJD within that window **overwrites**
it with the latest values instead of appending.


# ingest_candidates_cli.py

Loads candidate JSON files (one object, or an array, as the diff-imaging pipeline writes) into STZ-PZ through the `/add_candidate/` endpoint. The server does the matching and the create-or-append; this script reads files, posts them in batches, and reports each candidate. Standard library only. Payload format: `agentic_planning/023-add-candidate-endpoint/contract.md`. **To set it up on your own machine (account, folder, `PATH`, environment variables) and for a summary of the JSON payload, see [INSTALL_ingest_candidates_cli.md](INSTALL_ingest_candidates_cli.md).**

## Run

```bash
export YSE_URL=http://localhost:8001 USER_YSE=<your username>   # PW is prompted for if unset
python scripts/ingest_candidates_cli.py candidates.json
python scripts/ingest_candidates_cli.py --dry-run candidates.json   # see what would happen, save nothing
```

```
Target: http://localhost:8001 as dave
candidates.json [0] jwst_5324_trig7_61263_0  created  jwst_5324_trig7_61263_0, 4 points, 0 superseded
candidates.json [1] jwst_5324_trig7_61263_2  FAILED   photometry[0].mjd: required
2 candidates in 1 file: 1 created, 0 appended, 1 failed
```

- **Target and login:** the URL comes from `--url`, else `YSE_URL`, else `URL`, else `http://localhost:8001`. The target and user are printed before anything is sent, so check them. Username from `--user` or `USER_YSE`; password from `PW`, `--pw`, or a hidden prompt. There is no default user or password. The script warns when the URL is plain `http` and not local.
- **Each candidate is independent:** a bad one is reported (by id, field and message) and the rest are still saved.
- **`--dry-run`:** the server runs everything and rolls it back, so it tells you exactly what a real run would do, including problems such as an unknown instrument, and saves nothing.
- **Re-running a file is safe:** earlier points for the same band and epoch are flagged `Superseded` on the server instead of duplicated.
- **Exit code:** `0` all succeeded; `1` a candidate or a file failed; `2` bad usage or the login was rejected.
- `--batch-size` (default 100, max 500) sets how many candidates go in each request; `--timeout` is the per-request wait in seconds.

