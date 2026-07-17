"""Integration tests for the PhotometricBand REST entity."""
import pytest

from conftest import unique_name

pytestmark = pytest.mark.integration

ENDPOINT = "/api/photometricbands/"


def _body(instrument_url):
    return {"name": unique_name("Band"), "instrument": instrument_url}


def test_create_returns_201(api_post, staged_instrument):
    resp = api_post(ENDPOINT, _body(staged_instrument["url"]))
    assert resp.status_code == 201, resp.text[:500]


def test_created_band_values_and_defaults(api_post, api_get, staged_instrument):
    body = _body(staged_instrument["url"])
    resp = api_post(ENDPOINT, body)
    assert resp.status_code == 201, resp.text[:500]

    obj = api_get(resp.json()["url"])

    # --- values we assigned ---
    assert obj["name"] == body["name"]
    # FK resolves to the instrument we staged
    assert api_get(obj["instrument"])["name"] == staged_instrument["name"]
    assert obj["created_date"] and obj["modified_date"]

    # --- fields we left unset keep their model defaults (null) ---
    for field in ["lambda_eff", "throughput_file", "disp_color", "disp_symbol"]:
        assert obj[field] is None, f"expected {field} null, got {obj[field]!r}"


def test_bad_credentials_are_rejected(api_post, staged_instrument):
    resp = api_post(
        ENDPOINT, _body(staged_instrument["url"]), user="djones", pw="definitely-wrong"
    )
    assert resp.status_code in (401, 403)


def test_delete_as_admin_succeeds(api_post, api_delete, staged_instrument):
    url = api_post(ENDPOINT, _body(staged_instrument["url"])).json()["url"]
    assert api_delete(url).status_code == 204
    assert api_delete(url).status_code == 404  # already gone


def test_delete_as_non_admin_forbidden(
    api_post, api_delete, staged_instrument, nonadmin_credentials
):
    url = api_post(ENDPOINT, _body(staged_instrument["url"])).json()["url"]
    user, pw = nonadmin_credentials
    assert api_delete(url, user=user, pw=pw).status_code == 403
    api_delete(url)  # cleanup as admin
