# 025: Candidate ingest CLI

- **Issue:** #25 (part of #16; uses #23's endpoint)
- **Branch:** `25-ingest-candidates-cli`
- **Status:** Approved by Dave (with the changes in the Log); building

## Why

The `/add_candidate/` endpoint (#23, contract v1.1) works, but the only client is a small demo script. Until the web-sniff page can POST to the API itself (CORS and login are #26), a user needs a proper command to load a reduction run's candidate JSON files from their own machine. The endpoint does the matching, so the CLI is a thin, careful client: read files, post, report clearly.

## Scope

| # | Deliverable | Notes |
|---|---|---|
| 0 | Server-side dry run | `/add_candidate/?dry_run=1` runs the whole ingest and **rolls the transaction back**, so the reply says exactly what would happen (created/appended, counts, or the errors) and nothing is saved. Contract v1.2. One copy of the rules, on the server. |
| 1 | `scripts/ingest_candidates_cli.py` | Sibling of `ingest_transients_cli.py`, standard library only. |
| 2 | Remove `scripts/examples/add_candidate.py` | The CLI replaces it, so the name `add_candidate` means only the endpoint. |
| 3 | `scripts/README.md` section | How to run it, flags, exit codes, the dry run. |
| 4 | Tests | `tests/integration/test_ingest_candidates_cli.py`: runs the CLI as a subprocess against the local stack (like the other integration tests), plus offline dry-run cases. |

Out of scope: any change to the endpoint or contract, CORS, login and the web page (#26), the grid and detail pages (#27), promotion (#28), changing `ingest_transients_cli.py` (its default password is #18).

## Design notes

**Usage**

```bash
export URL=http://localhost:8001 USER_YSE=<user>      # PW is prompted for if unset
python scripts/ingest_candidates_cli.py FILE [FILE ...] [--dry-run] [--batch-size N]
python scripts/ingest_candidates_cli.py collab_scratch/jwst_5324_trig7_candidates.json
```

- **Input:** one or more JSON files. A file holds one candidate object or an array of them (the pipeline writes one array file).
- **Requests:** candidates are posted with the array form (contract v1.1), `--batch-size` per request (default 100, never above the endpoint's cap of 500). The endpoint saves each candidate independently and says which failed, so one bad candidate never blocks the rest.
- **Credentials:** `URL`, `USER_YSE`, `PW` from the environment (same names as `ingest_transients_cli.py`), overridden by `--url`, `--user`, `--pw`. **No default user or password.** A missing password is prompted for without echo; a missing user is an error. The default URL is `http://localhost:8001` (the compose default for `LOCAL_WEB_PORT`).
- **Clear text:** if the URL is `http://` and not `localhost`/`127.0.0.1`, print one warning that credentials and data travel unencrypted (see #17). It doesn't block.
- **Dry run:** `--dry-run` sends the same requests with `?dry_run=1`. The server validates and runs the full create-or-append logic inside a transaction that is rolled back, so it reports exactly what a real run would do (including an unknown instrument or tag) and saves nothing. The CLI contains no copy of the contract rules, only JSON parsing. It needs the server and a login, like a real run.
- **Output:** one line per candidate, then a summary:

  ```
  jwst_5324_trig7_candidates.json  [0] jwst_5324_trig7_61263_0  created   4 points, 0 superseded
  jwst_5324_trig7_candidates.json  [1] jwst_5324_trig7_61263_2  FAILED    photometry[0].mjd: required
  2 files-or-batches, 1 created, 0 appended, 1 failed
  ```

- **Exit codes:** `0` everything succeeded; `1` at least one candidate or file failed; `2` bad usage, or a login failure (401/403), which stops at once instead of retrying every file.
- **Errors per file, not per run:** an unreadable or invalid JSON file, or a network error on one request, is reported and the run continues with the next; those count as failures in the exit code. The CLI always sends a list, so the reply shape is always the per-candidate one.
- **Re-running is safe:** the endpoint supersedes identical band-and-epoch points, so posting a file twice flags the earlier points `Superseded` and doesn't duplicate what is shown. The `--help` text says so.

## Acceptance criteria

- [ ] One command ingests every candidate from a run's output (a file, several files, or a directory).
- [ ] Credentials come from the environment or flags; there is no default user or password, and a missing password is prompted for.
- [ ] Output shows created / appended / failed per candidate and a summary; the exit code reflects failures.
- [ ] `--dry-run` reports what would happen and saves nothing (no new rows in the DB).
- [ ] `/add_candidate/?dry_run=1` works for a single object and for a list, and rolls back (tests).
- [ ] Tested against the local stack with the pipeline's real test file (`jwst_5324_trig7_candidates.json`): created, then appended with superseded points on re-run.
- [ ] A bad candidate in a file is reported by name and field and doesn't stop the good ones.
- [ ] `scripts/examples/add_candidate.py` is removed and `scripts/README.md` documents the CLI.
- [ ] `ruff check .` passes; no dependency or image change.

## Verification

Local Claude, against the local stack (an admin test user, as for #23):

```bash
export URL=http://localhost:8001 USER_YSE=test4 PW=...
python scripts/ingest_candidates_cli.py --dry-run collab_scratch/jwst_5324_trig7_candidates.json
python scripts/ingest_candidates_cli.py collab_scratch/jwst_5324_trig7_candidates.json   # 2 created or appended
python scripts/ingest_candidates_cli.py collab_scratch/jwst_5324_trig7_candidates.json   # re-run: appended, 4 superseded each
python -m pytest tests/integration/test_ingest_candidates_cli.py
```

Then check the detail pages in the browser (4 current points per candidate).

## Open questions

1. ~~Sibling script or a mode of `ingest_transients_cli.py`?~~ **Sibling** (Dave).
2. ~~Dry-run validation~~ **Server-side** (Dave): no duplicate rules in the client.
3. Default batch size 100 (fine for ~25 to 30 candidates per field); `--batch-size` overrides.
4. ~~Directory input~~ Dropped (Dave): the pipeline writes one JSON array file and the user passes it as an argument.

## Log

- **2026-10-14:** Plan drafted from Dave's request for a user-driven loader to use before the page can POST (#26). Dave agreed the example script `scripts/examples/add_candidate.py` should be removed once the CLI exists.
- **2026-10-14:** Dave approved the plan with three changes: sibling script; **dry run on the server** (`?dry_run=1`, full logic then rollback) instead of a client-side copy of the rules, which adds a small endpoint feature (contract v1.2); and no directory input, since the pipeline writes a single JSON array file passed as an argument.
