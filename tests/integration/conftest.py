"""Fixtures for the YSE_PZ live-service integration tests.

Target and credentials are configurable via environment variables:
    YSE_URL   (default http://localhost:8000)
    YSE_USER  (default djones)
    YSE_PW    (default BossTent1)

The whole suite fails when the target is unreachable, so a missing or
unreachable deployment is reported as an error rather than silently passing.
"""
import json
import os
import random
import uuid

import pytest
import requests
from requests.auth import HTTPBasicAuth

DEFAULT_URL = os.environ.get("YSE_URL", "http://localhost:8000")
DEFAULT_USER = os.environ.get("YSE_USER", "djones")
DEFAULT_PW = os.environ.get("YSE_PW", "BossTent1")


@pytest.fixture(scope="session")
def base_url():
    return DEFAULT_URL.rstrip("/")


@pytest.fixture(scope="session")
def credentials():
    return (DEFAULT_USER, DEFAULT_PW)


@pytest.fixture(scope="session", autouse=True)
def require_server(base_url):
    """Fail the whole suite when the deployed app is unreachable.

    Reachability of the target is treated as a hard precondition: if the app
    cannot be contacted the tests error out rather than being silently skipped.
    """
    try:
        requests.get(base_url + "/", timeout=5)
    except requests.exceptions.RequestException as exc:
        pytest.fail(f"YSE_PZ not reachable at {base_url}: {exc}", pytrace=False)


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



@pytest.fixture
def new_transient():
    """A unique, spatially-distinct transient descriptor per test.

    A per-test name and randomized sky position keep test objects from
    colliding with each other (or with prior runs) via the endpoint's
    positional de-duplication.
    """
    suffix = uuid.uuid4().hex[:8]
    rng = random.Random(suffix)
    return {
        "name": f"ITEST{suffix}",
        "ra": round(rng.uniform(120.0, 240.0), 6),
        "dec": round(rng.uniform(-10.0, 60.0), 6),
    }
