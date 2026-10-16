"""Integration tests for the dashboard catch-all and the Archived state (#40).

A transient is always somewhere: a tag box, the Needs review grid (no transient-kind tag yet), the
candidate list, or the Archived page. The grids are searched by name with the dashboard's own
search box, so the tests don't depend on how many rows the grid has.
"""
import json

import pytest
import requests
from requests.auth import HTTPBasicAuth

from conftest import _delete_quietly, unique_name
from payloads import minimal_transient
from test_add_candidate import candidate_payload
from test_candidate_pages import _set_status, browser  # noqa: F401  (a logged-in session fixture)

pytestmark = pytest.mark.integration


def _grid(browser, base_url, path, prefix, name):
    """The page's HTML with its grid filtered to this name."""
    resp = browser.get(base_url + path, params={f"{prefix}-ex": name}, timeout=120)
    assert resp.status_code == 200, resp.text[:300]
    return resp.text


def _row_link(name):
    # a grid row links to the transient page; the search box echoes the typed name, so the name alone
    # would match even when there is no row
    return f"/transient_detail/{name.lower()}/"


def _in_needs_review(browser, base_url, name):
    html = _grid(browser, base_url, "/dashboard/", "needsreview", name)
    return 'id="needsreview"' in html and _row_link(name) in html.split('id="needsreview"')[1].split('class="box"')[0]


def _in_archived(browser, base_url, name):
    return _row_link(name) in _grid(browser, base_url, "/archived/", "archived", name)


def test_an_untagged_transient_is_in_needs_review(browser, base_url, post_transient, new_transient):
    assert post_transient(minimal_transient(new_transient)).status_code == 200
    assert _in_needs_review(browser, base_url, new_transient["name"])
    assert not _in_archived(browser, base_url, new_transient["name"])


def test_a_tagged_transient_is_not_in_needs_review(
        browser, base_url, post_transient, new_transient, staged_tag):
    payload = minimal_transient(new_transient)
    payload[new_transient["name"]]["tags"] = [staged_tag["name"]]
    assert post_transient(payload).status_code == 200
    assert not _in_needs_review(browser, base_url, new_transient["name"])


def test_archiving_moves_a_transient_and_changing_the_status_brings_it_back(
        browser, base_url, credentials, post_transient, new_transient):
    name = new_transient["name"]
    assert post_transient(minimal_transient(new_transient)).status_code == 200
    _set_status(base_url, credentials, name, "Archived")
    assert _in_archived(browser, base_url, name)
    assert not _in_needs_review(browser, base_url, name)
    _set_status(base_url, credentials, name, "New")
    assert not _in_archived(browser, base_url, name)
    assert _in_needs_review(browser, base_url, name)


def test_a_candidate_is_not_in_needs_review(browser, base_url, credentials, new_transient):
    payload = candidate_payload(**new_transient)
    resp = requests.post(base_url + "/add_candidate/", data=json.dumps(payload),
                         auth=HTTPBasicAuth(*credentials), timeout=60)
    assert resp.status_code == 201, resp.text[:300]
    assert not _in_needs_review(browser, base_url, new_transient["name"])


def test_a_candidate_tag_is_not_a_home_and_gets_no_box(browser, base_url, credentials, new_transient):
    """After promotion a candidate with only a candidate-kind tag sits in Needs review, and the
    candidate tag does not become a box on the main dashboard."""
    tag = unique_name("ctag")
    payload = candidate_payload(**new_transient)
    payload["tags"] = [tag]
    auth = HTTPBasicAuth(*credentials)
    try:
        resp = requests.post(base_url + "/add_candidate/", data=json.dumps(payload), auth=auth, timeout=60)
        assert resp.status_code == 201, resp.text[:300]
        _set_status(base_url, credentials, new_transient["name"], "New")
        assert _in_needs_review(browser, base_url, new_transient["name"])
        dashboard = browser.get(base_url + "/dashboard/", timeout=120).text
        assert f'<h3 class="box-title">{tag}</h3>' not in dashboard
    finally:
        rows = requests.get(base_url + "/api/transienttags/?format=json&limit=5000", auth=auth,
                            timeout=60).json()["results"]
        for row in rows:
            if row["name"] == tag:
                _delete_quietly(base_url, credentials, row["url"].split("?")[0])
