"""Integration tests for group access through the API (#86, API parity).

Run against the live stack after `migrate` (0016-0020) and a restart of the web container. YSE_USER
must be a superuser: only a superuser may change who can see a transient, or put 'Public' on it.
The unit tests in YSE_App/test_visibility.py (ApiTests) cover the rules for every kind of user; these
check that `groups` is written and read back through the real API on MySQL.
"""
import pytest
import requests
from requests.auth import HTTPBasicAuth

from test_candidate_pages import _transient_id, candidate  # noqa: F401

pytestmark = pytest.mark.integration


def _api(base_url, credentials, method, path, **kwargs):
    return requests.request(method, base_url + path, auth=HTTPBasicAuth(*credentials), timeout=60, **kwargs)


def test_transient_groups_are_written_and_read_back(base_url, credentials, candidate):
    tid = _transient_id(base_url, credentials, candidate["candidate_id"])
    resp = _api(base_url, credentials, "PATCH", f"/api/transients/{tid}/", json={"groups": ["Public"]})
    assert resp.status_code == 200, resp.text[:500]
    row = _api(base_url, credentials, "GET", f"/api/transients/{tid}/?format=json").json()
    assert row["groups"] == ["Public"]
    rows = _api(base_url, credentials, "GET", "/api/transients/?group_in=Public&limit=1000&format=json").json()
    assert tid in {r["url"].rstrip("/").split("/")[-1] for r in rows["results"]}


def test_comment_groups_are_written_and_read_back(base_url, credentials, candidate):
    tid = _transient_id(base_url, credentials, candidate["candidate_id"])
    resp = _api(base_url, credentials, "POST", "/api/logs/", json={
        "comment": "ITEST group access", "groups": ["Public"],
        "transient": f"{base_url}/api/transients/{tid}/"})
    assert resp.status_code == 201, resp.text[:500]
    log = _api(base_url, credentials, "GET", resp.json()["url"].replace(base_url, "") + "?format=json").json()
    assert log["groups"] == ["Public"]
    assert _api(base_url, credentials, "DELETE", resp.json()["url"].replace(base_url, "")).status_code in (204, 405)


def test_a_comment_without_groups_is_refused(base_url, credentials, candidate):
    tid = _transient_id(base_url, credentials, candidate["candidate_id"])
    resp = _api(base_url, credentials, "POST", "/api/logs/", json={
        "comment": "ITEST no groups", "groups": [], "transient": f"{base_url}/api/transients/{tid}/"})
    assert resp.status_code == 400, resp.text[:500]


def test_the_schema_is_open_and_data_needs_credentials(base_url):
    assert requests.get(base_url + "/api/schema/", timeout=30).status_code == 200
    assert requests.get(base_url + "/api/transients/", timeout=30).status_code in (401, 403)


def test_resource_groups_are_written_and_read_back(base_url, credentials):
    """#91: an observing resource takes `groups` by name, at least one, and reads them back."""
    telescopes = _api(base_url, credentials, "GET", "/api/telescopes/?limit=1&format=json").json()["results"]
    if not telescopes:
        pytest.skip("no telescope on this deployment")
    groups = _api(base_url, credentials, "GET", "/api/groups/?limit=100&format=json").json()["results"]
    data_group = next((g["name"] for g in groups if g["name"] not in ("Public", "TNS Reporters", "Transient Curators")), None)
    if data_group is None:
        pytest.skip("no data group on this deployment")
    body = {"telescope": telescopes[0]["url"], "begin_date_valid": "2026-01-01T00:00:00Z",
            "end_date_valid": "2026-01-02T00:00:00Z", "description": "ITEST resource", "groups": [data_group]}
    resp = _api(base_url, credentials, "POST", "/api/tooresources/", json=body)
    assert resp.status_code == 201, resp.text[:500]
    row = _api(base_url, credentials, "GET", resp.json()["url"].replace(base_url, "") + "?format=json").json()
    assert row["groups"] == [data_group]
    assert _api(base_url, credentials, "POST", "/api/tooresources/", json=dict(body, groups=[])).status_code == 400
