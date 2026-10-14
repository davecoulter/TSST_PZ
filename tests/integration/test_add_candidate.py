"""Integration tests for the /add_candidate/ endpoint (#23).

Payload contract: agentic_planning/023-add-candidate-endpoint/contract.md.
Needs migration 0005 (Candidate status/tag, Superseded DataQuality) applied and
the seeded JWST/NIRCam instrument.
"""
import copy
import json
import math

import pytest
import requests
from requests.auth import HTTPBasicAuth

from conftest import TEST_PREFIX, _delete_quietly, unique_name

pytestmark = pytest.mark.integration


def _offset(ra, dec, arcsec):
    """ra shifted east by `arcsec` at this dec."""
    return ra + arcsec / 3600.0 / math.cos(math.radians(dec))


def candidate_payload(name, ra, dec, mjd=61102.41532):
    bands = [("F150W", 0.0305, 0.0020), ("F200W", 0.0525, 0.0044)]
    return {
        "candidate_id": name,
        "ra": ra,
        "dec": dec,
        "permalink": f"https://example.org/websniff/#{name}",
        "instrument": "NIRCam",
        "photometry": [
            {
                "band": band, "mjd": mjd, "flux": flux, "flux_err": err,
                "flux_unit": "uJy", "upper_limit": False, "limit_sigma": None,
                "stamps": {"sci": f"https://example.org/{name}_{band}_sci.png",
                           "ref": f"https://example.org/{name}_{band}_ref.png",
                           "diff": f"https://example.org/{name}_{band}_diff.png"},
            }
            for band, flux, err in bands
        ],
    }


@pytest.fixture
def post_candidate(base_url, credentials):
    endpoint = base_url + "/add_candidate/"

    def _post(payload):
        return requests.post(endpoint, data=json.dumps(payload),
                             auth=HTTPBasicAuth(*credentials), timeout=60)

    return _post


@pytest.fixture
def delete_transient_named(base_url, credentials):
    def _delete(name):
        lookup = requests.get(base_url + f"/api/transients/?name={name}&format=json",
                              auth=HTTPBasicAuth(*credentials), timeout=30)
        if lookup.ok:
            for row in lookup.json().get("results", []):
                _delete_quietly(base_url, credentials, row["url"].split("?")[0])

    return _delete


def test_new_candidate_is_created(post_candidate, new_transient):
    resp = post_candidate(candidate_payload(**new_transient))
    assert resp.status_code == 201, resp.text[:500]
    body = resp.json()
    assert body["result"] == "created"
    assert body["transient"] == new_transient["name"]
    assert body["photometry_added"] == 2
    assert body["photometry_superseded"] == 0


def test_new_id_within_radius_appends(post_candidate, new_transient):
    first = post_candidate(candidate_payload(**new_transient))
    assert first.status_code == 201, first.text[:500]

    ra2 = _offset(new_transient["ra"], new_transient["dec"], 0.1)
    second = post_candidate(candidate_payload(new_transient["name"] + "_run2", ra2,
                                              new_transient["dec"], mjd=61130.5))
    assert second.status_code == 200, second.text[:500]
    body = second.json()
    assert body["result"] == "appended"
    assert body["transient"] == new_transient["name"]
    assert body["match_separation_arcsec"] < 0.2


def test_new_id_outside_radius_is_separate(post_candidate, new_transient, delete_transient_named):
    post_candidate(candidate_payload(**new_transient))
    other = new_transient["name"] + "_far"
    ra2 = _offset(new_transient["ra"], new_transient["dec"], 0.3)
    try:
        resp = post_candidate(candidate_payload(other, ra2, new_transient["dec"]))
        assert resp.status_code == 201, resp.text[:500]
        assert resp.json()["transient"] == other
    finally:
        delete_transient_named(other)


def test_repost_supersedes_same_epoch(post_candidate, new_transient):
    payload = candidate_payload(**new_transient)
    assert post_candidate(payload).status_code == 201
    again = post_candidate(payload)
    assert again.status_code == 200, again.text[:500]
    assert again.json()["photometry_superseded"] == 2


def test_upper_limit_is_accepted(post_candidate, new_transient):
    payload = candidate_payload(**new_transient)
    payload["photometry"][1].update(flux=None, flux_err=None, mag=29.8, mag_err=None,
                                    upper_limit=True, limit_sigma=3)
    resp = post_candidate(payload)
    assert resp.status_code == 201, resp.text[:500]


def test_invalid_payload_writes_nothing(post_candidate, new_transient, api_get):
    payload = candidate_payload(**new_transient)
    del payload["ra"]
    resp = post_candidate(payload)
    assert resp.status_code == 400
    assert "ra" in resp.json()["errors"]
    found = api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"]
    assert found == []


def test_unknown_instrument_is_rejected(post_candidate, new_transient):
    payload = copy.deepcopy(candidate_payload(**new_transient))
    payload["instrument"] = TEST_PREFIX + "NoSuchCam"
    resp = post_candidate(payload)
    assert resp.status_code == 400
    assert "instrument" in resp.json()["errors"]


def test_get_is_not_allowed(base_url, credentials):
    resp = requests.get(base_url + "/add_candidate/", auth=HTTPBasicAuth(*credentials), timeout=30)
    assert resp.status_code == 405


# --- a list of candidates (contract v1.1) ------------------------------------

def test_batch_items_are_independent(post_candidate, new_transient, delete_transient_named, api_get):
    good = candidate_payload(**new_transient)
    bad = candidate_payload(unique_name("bad"), new_transient["ra"], new_transient["dec"])
    del bad["ra"]
    other = unique_name("other")
    far = candidate_payload(other, _offset(new_transient["ra"], new_transient["dec"], 120),
                            new_transient["dec"])
    try:
        resp = post_candidate([good, bad, far])
        assert resp.status_code == 200, resp.text[:500]
        body = resp.json()
        assert [r["status"] for r in body["results"]] == [201, 400, 201]
        assert body["summary"] == {"created": 2, "appended": 0, "failed": 1}
        assert body["results"][1]["candidate_id"] == bad["candidate_id"]
        assert "ra" in body["results"][1]["errors"]
        found = api_get(f"/api/transients/?name={bad['candidate_id']}&format=json")["results"]
        assert found == []  # the failed one wrote nothing; the others still landed
    finally:
        delete_transient_named(other)


def test_batch_repost_supersedes(post_candidate, new_transient):
    payload = candidate_payload(**new_transient)
    assert post_candidate([payload]).json()["results"][0]["status"] == 201
    again = post_candidate([payload]).json()
    assert again["results"][0]["status"] == 200
    assert again["results"][0]["photometry_superseded"] == 2
    assert again["summary"] == {"created": 0, "appended": 1, "failed": 0}


def test_batch_empty_list_is_rejected(post_candidate):
    assert post_candidate([]).status_code == 400
