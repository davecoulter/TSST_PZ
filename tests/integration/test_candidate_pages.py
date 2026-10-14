"""Integration tests for the candidate pages (#27).

Plan: agentic_planning/027-candidate-pages/plan.md. Needs what
test_add_candidate.py needs (migration 0005 and the JWST/NIRCam instrument).
The pages use session login, so these tests log in through /login/ first.
"""
import pytest
import requests
from requests.auth import HTTPBasicAuth

from test_add_candidate import candidate_payload

pytestmark = pytest.mark.integration


@pytest.fixture
def browser(base_url, credentials):
    """A logged-in session, as a person in a browser would have."""
    session = requests.Session()
    session.get(base_url + "/login/", timeout=30)
    token = session.cookies.get("csrftoken", "")
    resp = session.post(base_url + "/login/",
                        data={"username": credentials[0], "password": credentials[1],
                              "csrfmiddlewaretoken": token},
                        headers={"Referer": base_url + "/login/"}, timeout=60)
    assert resp.ok and "/login/" not in resp.url, "login failed"
    return session


@pytest.fixture
def candidate(base_url, credentials, new_transient):
    payload = candidate_payload(**new_transient)
    resp = requests.post(base_url + "/add_candidate/", json=payload,
                         auth=HTTPBasicAuth(*credentials), timeout=60)
    assert resp.status_code == 201, resp.text[:500]
    return payload


def _candidate_pages(browser, base_url):
    """HTML of every page of /candidates/, sorted by name."""
    pages, n = [], 1
    while True:
        resp = browser.get(base_url + f"/candidates/?sort=name&page={n}", timeout=60)
        assert resp.status_code == 200, resp.text[:500]
        pages.append(resp.text)
        if f"page={n + 1}" not in resp.text:
            return "".join(pages)
        n += 1


def _set_status(base_url, credentials, name, status_name):
    auth = HTTPBasicAuth(*credentials)
    statuses = requests.get(base_url + "/api/transientstatuses/?format=json&limit=1000",
                            auth=auth, timeout=30).json()["results"]
    status_url = next(s["url"] for s in statuses if s["name"] == status_name)
    row = requests.get(base_url + f"/api/transients/?name={name}&format=json",
                       auth=auth, timeout=30).json()["results"][0]
    resp = requests.patch(row["url"].split("?")[0], json={"status": status_url},
                          auth=auth, timeout=60)
    assert resp.ok, resp.text[:500]


def test_candidate_dashboard_lists_candidate(browser, base_url, candidate):
    html = _candidate_pages(browser, base_url)
    assert candidate["candidate_id"] in html
    assert candidate["photometry"][0]["stamps"]["diff"] in html or \
        candidate["photometry"][1]["stamps"]["diff"] in html


def test_detail_page_shows_candidate_data(browser, base_url, candidate):
    resp = browser.get(base_url + f"/transient_detail/{candidate['candidate_id'].lower()}/",
                       timeout=60)
    assert resp.status_code == 200, resp.text[:500]
    assert "Candidate data" in resp.text
    assert candidate["permalink"] in resp.text
    for point in candidate["photometry"]:
        for url in point["stamps"].values():
            assert url in resp.text


def test_promoted_candidate_leaves_dashboard_keeps_data(browser, base_url, credentials, candidate):
    _set_status(base_url, credentials, candidate["candidate_id"], "New")
    assert candidate["candidate_id"] not in _candidate_pages(browser, base_url)
    detail = browser.get(base_url + f"/transient_detail/{candidate['candidate_id'].lower()}/",
                         timeout=60)
    assert "Candidate data" in detail.text
    assert candidate["permalink"] in detail.text


def test_candidate_not_on_main_dashboard(browser, base_url, candidate):
    resp = browser.get(base_url + "/dashboard/", timeout=120)
    assert resp.status_code == 200
    assert candidate["candidate_id"] not in resp.text


def test_candidates_page_needs_login(base_url):
    resp = requests.get(base_url + "/candidates/", allow_redirects=False, timeout=30)
    assert resp.status_code in (301, 302)
