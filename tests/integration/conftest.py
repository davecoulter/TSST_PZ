"""Fixtures for the YSE_PZ live-service integration tests.

Target and credentials are configurable via environment variables:
    YSE_URL           (default http://localhost:8000)
    YSE_USER          (default djones)          -- an admin (is_staff) user
    YSE_PW            (default BossTent1)
    YSE_WEB_CONTAINER (default tsstpz_web_container)  -- only used to provision
                       the non-admin test user (no user-create REST endpoint)

The whole suite fails when the target is unreachable, so a missing or
unreachable deployment is reported as an error rather than silently passing.

Assets are torn down over HTTP DELETE (admin-only) by each fixture that
created them, so no database access is required for cleanup.
"""
import json
import os
import random
import subprocess
import uuid

import pytest
import requests
from requests.auth import HTTPBasicAuth

DEFAULT_URL = os.environ.get("YSE_URL", "http://localhost:8000")
DEFAULT_USER = os.environ.get("YSE_USER", "djones")
DEFAULT_PW = os.environ.get("YSE_PW", "BossTent1")

# All entities created by these tests share this name prefix so they are easy
# to recognize and never collide with real/seeded data.
TEST_PREFIX = "ITEST_"

# Deletes are admin-only, so the "non-admin is forbidden" tests need a real
# authenticated non-admin user.
WEB_CONTAINER = os.environ.get("YSE_WEB_CONTAINER", "tsstpz_web_container")
NONADMIN_USER = "itest_nonadmin"
NONADMIN_PW = "itest_nonadmin_pw"


def unique_name(kind):
    """A collision-proof, teardown-targetable name for a test asset."""
    return f"{TEST_PREFIX}{kind}_{uuid.uuid4().hex[:8]}"


def _provision_nonadmin_user():
    """Provision (idempotently) the non-admin user used by the delete tests.

    There is no user-create REST endpoint, so the single non-admin user needed
    by the "delete is forbidden" tests is created via the web container. This
    runs once per session, not per test.
    """
    script = (
        "from django.contrib.auth.models import User\n"
        f"u, _ = User.objects.get_or_create(username='{NONADMIN_USER}')\n"
        "u.is_staff = False\n"
        "u.is_superuser = False\n"
        "u.is_active = True\n"
        f"u.set_password('{NONADMIN_PW}')\n"
        "u.save()\n"
    )
    result = subprocess.run(
        ["docker", "exec", WEB_CONTAINER, "python3", "manage.py", "shell", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "could not provision the non-admin test user (is the web container "
            f"named '{WEB_CONTAINER}'? set YSE_WEB_CONTAINER to override):\n"
            f"{result.stderr or result.stdout}"
        )


@pytest.fixture(scope="session")
def base_url():
    return DEFAULT_URL.rstrip("/")


@pytest.fixture(scope="session")
def credentials():
    return (DEFAULT_USER, DEFAULT_PW)


@pytest.fixture(scope="session", autouse=True)
def require_server(base_url):
    """Fail test suite when the deployed app is unreachable."""
    try:
        requests.get(base_url + "/", timeout=5)
    except requests.exceptions.RequestException as exc:
        pytest.fail(f"YSE_PZ not reachable at {base_url}: {exc}", pytrace=False)


@pytest.fixture(scope="session")
def nonadmin_credentials():
    """Provision (once) and return credentials for an authenticated non-admin."""
    _provision_nonadmin_user()
    return (NONADMIN_USER, NONADMIN_PW)


@pytest.fixture
def api_post(base_url, credentials):
    """Return a helper that POSTs a JSON body to a REST API create endpoint."""

    def _post(path, body, user=None, pw=None):
        url = path if path.startswith("http") else base_url + path
        auth = HTTPBasicAuth(user or credentials[0], pw or credentials[1])
        return requests.post(url, json=body, auth=auth, timeout=30)

    return _post


@pytest.fixture
def api_delete(base_url, credentials):
    """Return a helper that DELETEs a REST API path (or absolute URL)."""

    def _delete(path, user=None, pw=None):
        url = path if path.startswith("http") else base_url + path
        auth = HTTPBasicAuth(user or credentials[0], pw or credentials[1])
        return requests.delete(url, auth=auth, timeout=30)

    return _delete


@pytest.fixture
def cleanup(base_url, credentials):
    """Collect created object URLs and DELETE them (reverse order) on teardown."""
    urls = []
    yield urls
    for url in reversed(urls):
        _delete_quietly(base_url, credentials, url)


@pytest.fixture
def post_transient(base_url, credentials):
    """Return a helper that POSTs a payload dict to /add_transient/."""
    endpoint = base_url + "/add_transient/"

    def _post(payload, user=None, pw=None):
        auth = HTTPBasicAuth(user or credentials[0], pw or credentials[1])
        return requests.post(endpoint, data=json.dumps(payload), auth=auth, timeout=60)

    return _post


@pytest.fixture
def api_get(base_url, credentials):
    """Return a helper that GETs a REST API path (or absolute URL) as JSON."""

    def _get(path):
        url = path if path.startswith("http") else base_url + path
        resp = requests.get(url, auth=HTTPBasicAuth(*credentials), timeout=30)
        resp.raise_for_status()
        return resp.json()

    return _get


@pytest.fixture
def fetch_transient(api_get):
    """Return a helper that reads a single transient back by name."""

    def _fetch(name):
        results = api_get(f"/api/transients/?name={name}&format=json")["results"]
        assert len(results) == 1, f"expected exactly one transient named {name}, got {len(results)}"
        return results[0]

    return _fetch


# --- asset staging (create prerequisites via the API, delete on teardown) --

def _delete_quietly(base_url, credentials, url):
    """Best-effort DELETE used by fixture teardown; ignores already-gone rows."""
    try:
        requests.delete(url, auth=HTTPBasicAuth(*credentials), timeout=30)
    except requests.exceptions.RequestException:
        pass


@pytest.fixture
def staged_observatory(base_url, credentials, api_post):
    body = {"name": unique_name("Obs"), "utc_offset": 0, "tz_name": "UTC"}
    resp = api_post("/api/observatories/", body)
    assert resp.status_code == 201, resp.text[:500]
    obj = resp.json()
    yield obj
    _delete_quietly(base_url, credentials, obj["url"])


@pytest.fixture
def staged_telescope(base_url, credentials, api_post, staged_observatory):
    body = {
        "name": unique_name("Tel"), "latitude": 0.0, "longitude": 0.0,
        "elevation": 0.0, "observatory": staged_observatory["url"],
    }
    resp = api_post("/api/telescopes/", body)
    assert resp.status_code == 201, resp.text[:500]
    obj = resp.json()
    yield obj
    _delete_quietly(base_url, credentials, obj["url"])


@pytest.fixture
def staged_instrument(base_url, credentials, api_post, staged_telescope):
    body = {"name": unique_name("Inst"), "telescope": staged_telescope["url"]}
    resp = api_post("/api/instruments/", body)
    assert resp.status_code == 201, resp.text[:500]
    obj = resp.json()
    yield obj
    _delete_quietly(base_url, credentials, obj["url"])


@pytest.fixture
def staged_tag(base_url, credentials, api_post):
    body = {"name": unique_name("Tag")}
    resp = api_post("/api/transienttags/", body)
    assert resp.status_code == 201, resp.text[:500]
    obj = resp.json()
    yield obj
    _delete_quietly(base_url, credentials, obj["url"])


@pytest.fixture
def staged_jwst_lightcurve(api_post, staged_instrument):
    """Stage the JWST bands from resources/lc_0.txt under a fresh instrument.

    The band rows are cascade-deleted when staged_instrument is torn down.
    """
    from payloads import load_rows, filters_in
    rows = load_rows()
    for band in filters_in(rows):
        resp = api_post(
            "/api/photometricbands/",
            {"name": band, "instrument": staged_instrument["url"]},
        )
        assert resp.status_code == 201, resp.text[:500]
    return {"instrument": staged_instrument["name"], "rows": rows}


@pytest.fixture
def download_photometry(base_url, credentials):
    """Return a helper that fetches a transient's SNANA-style photometry text."""

    def _dl(name):
        resp = requests.get(
            base_url + f"/download_photometry/{name.lower()}/",
            auth=HTTPBasicAuth(*credentials), timeout=60,
        )
        resp.raise_for_status()
        return resp.text

    return _dl


@pytest.fixture
def new_transient(base_url, credentials):
    """A unique, spatially-distinct transient descriptor per test.

    A per-test name and randomized sky position keep test objects from
    colliding with each other (or with prior runs) via the endpoint's
    positional de-duplication. Any transient created under this name is
    deleted on teardown.
    """
    suffix = uuid.uuid4().hex[:8]
    rng = random.Random(suffix)
    descriptor = {
        "name": f"{TEST_PREFIX}{suffix}",
        "ra": round(rng.uniform(120.0, 240.0), 6),
        "dec": round(rng.uniform(-10.0, 60.0), 6),
    }
    yield descriptor
    lookup = requests.get(
        base_url + f"/api/transients/?name={descriptor['name']}&format=json",
        auth=HTTPBasicAuth(*credentials), timeout=30,
    )
    if lookup.ok:
        for row in lookup.json().get("results", []):
            _delete_quietly(base_url, credentials, row["url"].split("?")[0])
