"""Integration tests for the TransientTag REST entity."""
import pytest

from conftest import unique_name

pytestmark = pytest.mark.integration
ENDPOINT = "/api/transienttags/"


def _body():
    return {"name": unique_name("Tag")}


def test_create_returns_201(api_post, cleanup):
    resp = api_post(ENDPOINT, _body())
    assert resp.status_code == 201, resp.text[:500]
    cleanup.append(resp.json()["url"])


def test_created_tag_values_and_defaults(api_post, api_get, cleanup):
    body = _body()
    resp = api_post(ENDPOINT, body)
    assert resp.status_code == 201, resp.text[:500]
    cleanup.append(resp.json()["url"])
    obj = api_get(resp.json()["url"])
    # assigned
    assert obj["name"] == body["name"]
    assert obj["created_by"] and obj["modified_by"]
    assert obj["created_date"] and obj["modified_date"]
    # default (optional color left unset)
    assert obj["color"] is None


def test_bad_credentials_are_rejected(api_post):
    resp = api_post(ENDPOINT, _body(), user="djones", pw="definitely-wrong")
    assert resp.status_code in (401, 403)


def test_delete_as_admin_succeeds(api_post, api_delete):
    url = api_post(ENDPOINT, _body()).json()["url"]
    assert api_delete(url).status_code == 204
    assert api_delete(url).status_code == 404  # already gone


def test_delete_as_non_admin_forbidden(api_post, api_delete, nonadmin_credentials):
    url = api_post(ENDPOINT, _body()).json()["url"]
    user, pw = nonadmin_credentials
    assert api_delete(url, user=user, pw=pw).status_code == 403
    api_delete(url)  # cleanup as admin
