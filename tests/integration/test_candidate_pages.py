"""Integration tests for the candidate pages (#27).

Plan: agentic_planning/027-candidate-pages/plan.md. Needs what
test_add_candidate.py needs (migration 0005 and the JWST/NIRCam instrument).
The pages use session login, so these tests log in through /login/ first.
"""
import pytest
import requests
from requests.auth import HTTPBasicAuth

from payloads import minimal_transient
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


def _candidate_page(browser, base_url, name):
    resp = browser.get(base_url + f"/candidate/{name.lower()}/", timeout=60)
    assert resp.status_code == 200, resp.text[:500]
    return resp.text


def test_candidate_page_shows_the_candidate(browser, base_url, candidate):
    html = _candidate_page(browser, base_url, candidate["candidate_id"])
    assert candidate["permalink"] in html
    for point in candidate["photometry"]:
        for url in point["stamps"].values():
            assert url in html
    assert "Highest S/N" in html and "most recent" in html.lower()
    assert "All cutouts" in html


def test_candidate_and_transient_pages_link_to_each_other(browser, base_url, candidate):
    slug = candidate["candidate_id"].lower()
    transient_html = browser.get(base_url + f"/transient_detail/{slug}/", timeout=60).text
    assert f"/candidate/{slug}/" in transient_html and "Candidate page" in transient_html
    assert f"/transient_detail/{slug}/" in _candidate_page(browser, base_url, slug)


def test_a_regular_transient_has_no_candidate_page(browser, base_url, post_transient, new_transient):
    assert post_transient(minimal_transient(new_transient)).status_code == 200
    resp = browser.get(base_url + f"/candidate/{new_transient['name'].lower()}/",
                       allow_redirects=False, timeout=60)
    assert resp.status_code in (301, 302)
    assert f"/transient_detail/{new_transient['name'].lower()}/" in resp.headers["Location"]


def test_unknown_candidate_is_a_404(browser, base_url):
    assert browser.get(base_url + "/candidate/no-such-candidate-xyz/", timeout=60).status_code == 404


def test_candidate_cards_open_the_candidate_page(browser, base_url, candidate):
    html = _candidate_pages(browser, base_url)
    assert f"/candidate/{candidate['candidate_id'].lower()}/" in html


def test_promoted_candidate_leaves_dashboard_keeps_data(browser, base_url, credentials, candidate):
    _set_status(base_url, credentials, candidate["candidate_id"], "New")
    assert candidate["candidate_id"] not in _candidate_pages(browser, base_url)
    assert candidate["permalink"] in _candidate_page(browser, base_url, candidate["candidate_id"])


def test_candidate_not_on_main_dashboard(browser, base_url, candidate):
    resp = browser.get(base_url + "/dashboard/", timeout=120)
    assert resp.status_code == 200
    assert candidate["candidate_id"] not in resp.text


def test_candidates_page_needs_login(base_url):
    resp = requests.get(base_url + "/candidates/", allow_redirects=False, timeout=30)
    assert resp.status_code in (301, 302)


def test_status_buttons_start_with_new(browser, base_url, candidate):
    import re
    html = _candidate_page(browser, base_url, candidate["candidate_id"])
    names = re.findall(r'data-status_name="([^"]+)" class="transientStatusChange btn', html)
    assert names == ["New", "Watch", "Archived", "Ignore"]
    # a session-authenticated PATCH is rejected without the CSRF header, so the page must send it
    assert "X-CSRFToken" in html


def test_default_light_curve_size_is_unchanged(browser, base_url, credentials, candidate):
    """The compact switch is for the candidate page only; the transient page's plot keeps its size."""
    import re
    auth = HTTPBasicAuth(*credentials)
    row = requests.get(base_url + f"/api/transients/?name={candidate['candidate_id']}&format=json",
                       auth=auth, timeout=30).json()["results"][0]
    transient_id = row["url"].split("?")[0].rstrip("/").split("/")[-1]

    def width(query):
        html = browser.get(base_url + f"/lightcurveplot_detail/{transient_id}/{query}", timeout=120).text
        return int(re.findall(r'"(?:width|height)":(\d+)', html)[1])   # height is listed first

    assert width("") == 400 and width("?compact=1") == 600

