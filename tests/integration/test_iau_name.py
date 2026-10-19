"""Integration tests for the internal name plus IAU name (#29).

Run against the live stack after `migrate` (0009) and a restart of the web container. The unit
tests in YSE_App/tests.py cover the same rules but can't start until #22 is fixed, and they ran
on SQLite; these run on the real MySQL and the real pages. The IAU name is set through the API,
as the admin popup's save does (both go through Transient.save()).
"""
import random
import string

import pytest
import requests
from requests.auth import HTTPBasicAuth

from conftest import unique_name
from test_add_candidate import candidate_payload
from test_candidate_pages import _candidate_pages, _set_status, _transient_id, browser, candidate  # noqa: F401
from test_dashboard_grids import _grid, _row_link

pytestmark = pytest.mark.integration


def _iau():
    """A bare TNS-style designation, e.g. 2026abcd (lowercase, so it is its own slug)."""
    return "2026" + "".join(random.choices(string.ascii_lowercase, k=4))


def _patch(base_url, credentials, name, data):
    tid = _transient_id(base_url, credentials, name)
    return requests.patch(f"{base_url}/api/transients/{tid}/", json=data,
                          auth=HTTPBasicAuth(*credentials), timeout=60)


def _set_iau(base_url, credentials, name, iau):
    resp = _patch(base_url, credentials, name, {"iau_name": iau})
    assert resp.ok, resp.text[:500]


def _redirect(browser, base_url, path):
    resp = browser.get(base_url + path, allow_redirects=False, timeout=60)
    return resp.status_code, resp.headers.get("Location", "")


def test_iau_name_is_in_the_api(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    tid = _transient_id(base_url, credentials, name)
    row = requests.get(f"{base_url}/api/transients/{tid}/?format=json",
                       auth=HTTPBasicAuth(*credentials), timeout=30).json()
    assert row["iau_name"] == iau
    assert row["name"] == name  # the internal name is unchanged


def test_old_urls_redirect_to_the_iau_name(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    for prefix in ("/transient_detail/", "/candidate/"):
        status, location = _redirect(browser, base_url, f"{prefix}{name.lower()}/")
        assert status in (301, 302), f"{prefix}: expected a redirect, got {status}"
        assert location.endswith(f"{prefix}{iau}/"), location
        assert browser.get(base_url + f"{prefix}{iau}/", timeout=60).status_code == 200


def test_the_name_typed_with_an_at_or_sn_prefix_resolves(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    for typed in (f"AT{iau}", f"SN{iau}"):
        status, location = _redirect(browser, base_url, f"/transient_detail/{typed}/")
        assert status in (301, 302), f"{typed}: expected a redirect, got {status}"
        assert location.endswith(f"/transient_detail/{iau}/"), location


@pytest.mark.parametrize("prefix", ["/transient_detail/", "/candidate/"])
def test_an_unknown_name_is_a_friendly_404(browser, base_url, prefix):
    resp = browser.get(base_url + f"{prefix}nope{random.randint(1000, 9999)}/", timeout=60)
    assert resp.status_code == 404, f"{prefix}: expected 404, got {resp.status_code}"
    assert "wis-tns.org" in resp.text  # the page offers a TNS search


def test_candidate_dashboard_shows_the_iau_name_and_finds_either(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    by_iau = _candidate_pages(browser, base_url, iau)
    assert f"/candidate/{iau}/" in by_iau
    assert name in by_iau  # the internal name, underneath
    assert f"/candidate/{iau}/" in _candidate_pages(browser, base_url, name)


def test_search_finds_a_transient_by_either_name(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    for term in (iau, name):
        resp = browser.get(base_url + "/search/", params={"q": term}, timeout=60)
        assert resp.status_code == 200, resp.text[:300]
        assert _row_link(iau) in resp.text, f"search for {term} did not find it"


def test_transient_grids_show_the_iau_name_and_search_by_either(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    _set_status(base_url, credentials, name, "New")  # out of the candidate list, into Needs review
    by_iau = _grid(browser, base_url, "/dashboard/", "needsreview", iau)
    assert _row_link(iau) in by_iau
    assert name in by_iau  # the search box echoed the IAU name, so this is the small internal name
    assert _row_link(iau) in _grid(browser, base_url, "/dashboard/", "needsreview", name)


def test_clearing_the_iau_name_restores_the_internal_slug(base_url, credentials, candidate, browser):
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    assert _patch(base_url, credentials, name, {"iau_name": None}).ok
    assert browser.get(base_url + f"/transient_detail/{name.lower()}/", allow_redirects=False,
                       timeout=60).status_code == 200
    status, location = _redirect(browser, base_url, f"/transient_detail/{iau}/")
    assert status in (301, 302) and location.endswith(f"/transient_detail/{name.lower()}/"), (status, location)


def test_a_second_transient_cannot_take_the_same_iau_name(base_url, credentials, candidate, new_transient):
    """The unique index, including MySQL's case-insensitive collation: a clean 400, not a 500."""
    first, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, first, iau)
    other = unique_name("iau2")
    payload = candidate_payload(other, round(new_transient["ra"] + 5, 6), new_transient["dec"])
    auth = HTTPBasicAuth(*credentials)
    created = requests.post(base_url + "/add_candidate/", json=payload, auth=auth, timeout=60)
    assert created.status_code == 201, created.text[:300]
    try:
        for attempt in (iau, iau.upper()):
            resp = _patch(base_url, credentials, other, {"iau_name": attempt})
            assert resp.status_code == 400, f"{attempt}: expected 400, got {resp.status_code} {resp.text[:200]}"
    finally:
        requests.delete(f"{base_url}/api/transients/{_transient_id(base_url, credentials, other)}/",
                        auth=auth, timeout=60)


def test_a_renamed_transient_can_be_deleted(base_url, credentials, candidate, browser):
    """Renaming leaves an alias row pointing at the transient; deleting must take it along."""
    name, iau = candidate["candidate_id"], _iau()
    _set_iau(base_url, credentials, name, iau)
    tid = _transient_id(base_url, credentials, name)
    resp = requests.delete(f"{base_url}/api/transients/{tid}/", auth=HTTPBasicAuth(*credentials), timeout=60)
    assert resp.status_code in (200, 204), f"delete failed: {resp.status_code} {resp.text[:300]}"
    assert browser.get(base_url + f"/transient_detail/{iau}/", timeout=60).status_code == 404
