# ingest_transients_cli.py

Bulk-uploads JWST transients and their light curves via the `/add_transient/` endpoint.

## Run

```sh
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
