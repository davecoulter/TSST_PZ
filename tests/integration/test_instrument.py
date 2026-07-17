"""Integration tests for the Instrument REST entity."""
import pytest

from conftest import unique_name

pytestmark = pytest.mark.integration

ENDPOINT = "/api/instruments/"


def _body(telescope_url):
    return {"name": unique_name("Inst"), "telescope": telescope_url}


def test_create_returns_201(api_post, staged_telescope):
    resp = api_post(ENDPOINT, _body(staged_telescope["url"]))
    assert resp.status_code == 201, resp.text[:500]


def test_created_instrument_values_and_defaults(api_post, api_get, staged_telescope):
    body = _body(staged_telescope["url"])
    resp = api_post(ENDPOINT, body)
    assert resp.status_code == 201, resp.text[:500]

    obj = api_get(resp.json()["url"])

    # --- values we assigned ---
    assert obj["name"] == body["name"]
    # FK resolves to the telescope we staged
    assert api_get(obj["telescope"])["name"] == staged_telescope["name"]
    assert obj["created_date"] and obj["modified_date"]

    # --- field we left unset keeps its model default (null) ---
    assert obj["description"] is None


def test_bad_credentials_are_rejected(api_post, staged_telescope):
    resp = api_post(
        ENDPOINT, _body(staged_telescope["url"]), user="djones", pw="definitely-wrong"
    )
    assert resp.status_code in (401, 403)


def test_delete_as_admin_succeeds(api_post, api_delete, staged_telescope):
    url = api_post(ENDPOINT, _body(staged_telescope["url"])).json()["url"]
    assert api_delete(url).status_code == 204
    assert api_delete(url).status_code == 404  # already gone


def test_delete_as_non_admin_forbidden(
    api_post, api_delete, staged_telescope, nonadmin_credentials
):
    url = api_post(ENDPOINT, _body(staged_telescope["url"])).json()["url"]
    user, pw = nonadmin_credentials
    assert api_delete(url, user=user, pw=pw).status_code == 403
    api_delete(url)  # cleanup as admin
