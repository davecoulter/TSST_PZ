"""Integration tests for the Candidates page sub-grids and the New call to action (#40), and the archive
split by tag.

A created candidate gets the candidate-kind tag New and sits in the New grid (the backlog, always first).
Removing New moves it to one grid per candidate tag it has, or to No tag, so nothing disappears; the grids
are exclusive. The sidebar badge counts new candidates. The Archived page is split by tag too.
"""
import json
import re

import pytest
import requests
from requests.auth import HTTPBasicAuth

from conftest import _delete_quietly, unique_name
from payloads import minimal_transient
from test_add_candidate import candidate_payload
from test_candidate_pages import _page_post, _set_status, _transient_id, browser  # noqa: F401

pytestmark = pytest.mark.integration


def _post(base_url, credentials, payload):
    return requests.post(base_url + "/add_candidate/", data=json.dumps(payload),
                         auth=HTTPBasicAuth(*credentials), timeout=60)


def _grids_holding(browser, base_url, name):
    """The ids (grid_<slug>) of the Candidates grids that list this candidate."""
    html = browser.get(base_url + "/candidates/", params={"q": name}, timeout=60).text
    link = f"/candidate/{name.lower()}/"
    found = set()
    for chunk in html.split('id="grid_')[1:]:
        if link in chunk.split('</table>')[0]:
            found.add(chunk.split('"')[0])
    return found


def _new_badge(browser, base_url):
    html = browser.get(base_url + "/candidates/", timeout=60).text
    match = re.search(r'bg-yellow" title="(\d+) new candidate', html)
    return int(match.group(1)) if match else 0


def _remove_new(browser, base_url, tid):
    return _page_post(browser, base_url, f"/candidate_tag/{tid}/", {"action": "remove", "name": "New"})


def test_a_new_candidate_is_in_the_new_grid_only(browser, base_url, credentials, new_transient):
    assert _post(base_url, credentials, candidate_payload(**new_transient)).status_code == 201
    assert _grids_holding(browser, base_url, new_transient["name"]) == {"new"}


def test_triaging_moves_it_to_no_tag_then_to_a_tag_grid(browser, base_url, credentials, new_transient):
    name = new_transient["name"]
    assert _post(base_url, credentials, candidate_payload(**new_transient)).status_code == 201
    tid = _transient_id(base_url, credentials, name)
    tag = unique_name("grid")
    try:
        _remove_new(browser, base_url, tid)
        assert _grids_holding(browser, base_url, name) == {"notag"}            # nothing disappears
        _page_post(browser, base_url, f"/candidate_tag/{tid}/", {"action": "add", "name": tag})
        slug = "".join(ch for ch in tag.lower() if ch.isalnum())
        assert _grids_holding(browser, base_url, name) == {slug}                # exclusive: not No tag
    finally:
        rows = requests.get(base_url + "/api/transienttags/?format=json&limit=5000",
                            auth=HTTPBasicAuth(*credentials), timeout=60).json()["results"]
        for row in rows:
            if row["name"] == tag:
                _delete_quietly(base_url, credentials, row["url"].split("?")[0])


def test_new_wins_while_it_is_there(browser, base_url, credentials, new_transient):
    """Tagged New and something else, it is only in the New grid until it is triaged."""
    name = new_transient["name"]
    payload = candidate_payload(**new_transient)
    tag = unique_name("grid")
    payload["tags"] = [tag]
    try:
        assert _post(base_url, credentials, payload).status_code == 201
        assert _grids_holding(browser, base_url, name) == {"new"}
        _remove_new(browser, base_url, _transient_id(base_url, credentials, name))
        assert _grids_holding(browser, base_url, name) == {"".join(ch for ch in tag.lower() if ch.isalnum())}
    finally:
        rows = requests.get(base_url + "/api/transienttags/?format=json&limit=5000",
                            auth=HTTPBasicAuth(*credentials), timeout=60).json()["results"]
        for row in rows:
            if row["name"] == tag:
                _delete_quietly(base_url, credentials, row["url"].split("?")[0])


def test_a_later_post_does_not_bring_new_back(browser, base_url, credentials, new_transient):
    name = new_transient["name"]
    payload = candidate_payload(**new_transient)
    assert _post(base_url, credentials, payload).status_code == 201
    _remove_new(browser, base_url, _transient_id(base_url, credentials, name))
    assert _post(base_url, credentials, payload).status_code == 200             # appended to the same candidate
    assert _grids_holding(browser, base_url, name) == {"notag"}


def test_the_sidebar_badge_counts_new_candidates(browser, base_url, credentials, new_transient):
    before = _new_badge(browser, base_url)
    assert _post(base_url, credentials, candidate_payload(**new_transient)).status_code == 201
    assert _new_badge(browser, base_url) == before + 1
    _remove_new(browser, base_url, _transient_id(base_url, credentials, new_transient["name"]))
    assert _new_badge(browser, base_url) == before                               # classifying clears it


def _archive_grids_holding(browser, base_url, name):
    html = browser.get(base_url + "/archived/", timeout=120).text
    link = f"/transient_detail/{name.lower()}/"
    found = set()
    for chunk in html.split('<div class="box" id="')[1:]:
        if link in chunk.split("</table>")[0]:
            found.add(chunk.split('"')[0])
    return found


def test_the_archive_is_split_by_tag_with_a_no_tag_grid(
        browser, base_url, credentials, post_transient, new_transient, staged_tag):
    tagged = dict(new_transient, name=new_transient["name"] + "_t")
    plain = dict(new_transient, name=new_transient["name"] + "_p", ra=new_transient["ra"] + 1.0)
    payload = minimal_transient(tagged)
    payload[tagged["name"]]["tags"] = [staged_tag["name"]]
    assert post_transient(payload).status_code == 200
    assert post_transient(minimal_transient(plain)).status_code == 200
    try:
        _set_status(base_url, credentials, tagged["name"], "Archived")
        _set_status(base_url, credentials, plain["name"], "Archived")
        assert _archive_grids_holding(browser, base_url, tagged["name"]) == {staged_tag["name"]}
        assert _archive_grids_holding(browser, base_url, plain["name"]) == {"Archived"}   # the No tag grid
    finally:
        for name in (tagged["name"], plain["name"]):
            for row in requests.get(base_url + f"/api/transients/?name={name}&format=json",
                                    auth=HTTPBasicAuth(*credentials), timeout=30).json()["results"]:
                _delete_quietly(base_url, credentials, row["url"].split("?")[0])


def test_an_archived_candidate_only_tagged_new_is_in_no_tag_and_is_badged(
        browser, base_url, credentials, new_transient):
    name = new_transient["name"]
    assert _post(base_url, credentials, candidate_payload(**new_transient)).status_code == 201
    _set_status(base_url, credentials, name, "Archived")
    assert _archive_grids_holding(browser, base_url, name) == {"Archived"}        # New is not an archive grid
    html = browser.get(base_url + "/archived/", timeout=120).text
    assert f"/candidate/{name.lower()}/" in html                                  # the candidate badge


def _candidate_page_html(browser, base_url, name):
    resp = browser.get(base_url + f"/candidate/{name.lower()}/", timeout=60)
    assert resp.status_code == 200, resp.text[:300]
    return resp.text


def test_mark_triaged_and_next_appear_only_while_the_candidate_is_new(
        browser, base_url, credentials, new_transient):
    first = new_transient
    second = dict(new_transient, name=new_transient["name"] + "_b", ra=new_transient["ra"] + 1.0)
    try:
        assert _post(base_url, credentials, candidate_payload(**first)).status_code == 201
        assert _post(base_url, credentials, candidate_payload(**second)).status_code == 201
        html = _candidate_page_html(browser, base_url, first["name"])
        assert 'id="cand_triaged"' in html and "Mark triaged &amp; next" in html
        # with other new candidates around, it leads to the next one, not back to the list
        assert re.search(r'id="cand_triaged"[^>]*data-next="/candidate/[^"]+/"', html)
        assert 'id="cand_skip"' in html
        _remove_new(browser, base_url, _transient_id(base_url, credentials, first["name"]))
        assert 'id="cand_triaged"' not in _candidate_page_html(browser, base_url, first["name"])
    finally:
        for row in requests.get(base_url + f"/api/transients/?name={second['name']}&format=json",
                                auth=HTTPBasicAuth(*credentials), timeout=30).json()["results"]:
            _delete_quietly(base_url, credentials, row["url"].split("?")[0])


def test_the_score_is_each_reporters_latest_quality_flag(browser, base_url, credentials, new_transient):
    name = new_transient["name"]
    payload = candidate_payload(**new_transient)
    payload["quality_flag"] = 3
    assert _post(base_url, credentials, payload).status_code == 201

    def row_and_badge():
        listing = browser.get(base_url + "/candidates/", params={"q": name}, timeout=60).text
        row = next(r for r in listing.split("<tr>") if f"/candidate/{name.lower()}/" in r)
        page = _candidate_page_html(browser, base_url, name)
        return row, page

    row, page = row_and_badge()
    assert "3.0" in row and "(1)" in row and "score 3.0 (1)" in page
    # the same reporter changes their mind: the latest counts, once
    _page_post(browser, base_url, "/add_transient_comment/",
               {"comment": "quality_flag: 1; notes: on a second look", "transient": _transient_id(base_url, credentials, name)},
               ajax=True)
    row, page = row_and_badge()
    assert "1.0" in row and "(1)" in row and "score 1.0 (1)" in page
