# Integration tests

Live-service integration tests for the YSE_PZ `/add_transient/` ingest endpoint.
They run against a **running** deployment and will error out (non-zero exit) if
the target is unreachable.

## Configuration

| Env var    | Default                 | Description       |
| ---------- | ----------------------- | ----------------- |
| `YSE_URL`  | `http://localhost:8000` | Base URL of app   |
| `YSE_USER` | `djones`                | Django username   |
| `YSE_PW`   | `BossTent1`             | Django password   |

## Running

From the repository root:

```bash
# run the full suite
python -m pytest

# verbose
python -m pytest tests/integration -v

# a single test
python -m pytest tests/integration/test_add_transient.py::test_minimal_transient_returns_success

# against a different deployment / credentials
YSE_URL=http://localhost:8000 YSE_USER=djones YSE_PW=BossTent1 python -m pytest
```
