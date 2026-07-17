"""Integration tests for the Telescope REST entity."""
import pytest

from conftest import unique_name

pytestmark = pytest.mark.integration

ENDPOINT = "/api/telescopes/"


def _body(observatory_url):
    return {
        "name": unique_name("Tel"),
        "latitude": 19.8,
        "longitude": -155.5,
        "elevation": 4200.0,
        "observatory": observatory_url,
    }


def test_create_returns_201(api_post, staged_observatory):
    resp = api_post(ENDPOINT, _body(staged_observatory["url"]))
    assert resp.status_code == 201, resp.text[:500]


def test_created_telescope_values_and_links(api_post, api_get, staged_observatory):
    body = _body(staged_observatory["url"])
    resp = api_post(ENDPOINT, body)
    assert resp.status_code == 201, resp.text[:500]

    obj = api_get(resp.json()["url"])

    # --- values we assigned ---
    assert obj["name"] == body["name"]
    assert obj["latitude"] == body["latitude"]
    assert obj["longitude"] == body["longitude"]
    assert obj["elevation"] == body["elevation"]
    # FK resolves to the observatory we staged
    assert api_get(obj["observatory"])["name"] == staged_observatory["name"]
    assert obj["created_date"] and obj["modified_date"]


def test_bad_credentials_are_rejected(api_post, staged_observatory):
    resp = api_post(
        ENDPOINT, _body(staged_observatory["url"]), user="djones", pw="definitely-wrong"
    )
    assert resp.status_code in (401, 403)


def test_delete_as_admin_succeeds(api_post, api_delete, staged_observatory):
    url = api_post(ENDPOINT, _body(staged_observatory["url"])).json()["url"]
    assert api_delete(url).status_code == 204
    assert api_delete(url).status_code == 404  # already gone


def test_delete_as_non_admin_forbidden(
    api_post, api_delete, staged_observatory, nonadmin_credentials
):
    url = api_post(ENDPOINT, _body(staged_observatory["url"])).json()["url"]
    user, pw = nonadmin_credentials
    assert api_delete(url, user=user, pw=pw).status_code == 403
    api_delete(url)  # cleanup as admin
