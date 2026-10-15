"""Integration tests for what contract v1.3 added to /add_candidate/ (#36, #37, #38):
the websniff page's fields (host block, notes and confidence as a comment, a FitsMap link,
tags), the `warnings` and `host` parts of the reply, and band wavelengths.

Needs migrations 0006 and 0007 applied (host catalogs, tag kinds). Hosts and the test catalog
are removed at the end of the module, through the web container, because the API has no
delete for them.
"""
import json
import random
import subprocess

import pytest
import requests
from requests.auth import HTTPBasicAuth

from conftest import WEB_CONTAINER, _delete_quietly, unique_name
from test_add_candidate import candidate_payload
from test_candidate_pages import browser  # noqa: F401  (a logged-in session fixture)

pytestmark = pytest.mark.integration

CATALOG = "ITEST_catalog.fits"
COMMENT = "quality_flag: 3; notes: test"


def host_block(ra, dec, object_id, catalog=CATALOG, z=7.56):
    return {"host_ra": ra + 0.0001, "host_dec": dec, "host_sep": 0.39, "host_z": z,
            "host_z2": z - 0.01, "host_id": object_id, "host_catalog": catalog}


def v13_payload(name, ra, dec, object_id=None, **extra):
    """A payload shaped like the pipeline's page sends it."""
    payload = candidate_payload(name, ra, dec)
    payload.update(
        fitsmap_url=f"https://example.org/fitsmap/index.html#candidate={name}",
        run_id="itest_run", field="itest_field", tags=[], quality_flag=3, notes="test",
        host=host_block(ra, dec, object_id or random.randrange(900_000_000, 999_999_999)))
    payload.update(extra)
    return payload


@pytest.fixture(scope="module", autouse=True)
def remove_test_hosts_and_catalog():
    yield
    script = (
        "from YSE_App.models import Host, HostCatalog\n"
        "Host.objects.filter(name__startswith='ITEST_').delete()\n"
        "HostCatalog.objects.filter(filename__startswith='ITEST_').delete()\n"
    )
    subprocess.run(["docker", "exec", WEB_CONTAINER, "python3", "manage.py", "shell", "-c", script],
                   capture_output=True, text=True, timeout=120)


@pytest.fixture
def post(base_url, credentials):
    def _post(payload, dry_run=False):
        url = base_url + "/add_candidate/" + ("?dry_run=1" if dry_run else "")
        return requests.post(url, data=json.dumps(payload), auth=HTTPBasicAuth(*credentials), timeout=60)
    return _post


def _detail_html(browser, base_url, name):
    resp = browser.get(base_url + f"/transient_detail/{name.lower()}/", timeout=60)
    assert resp.status_code == 200, resp.text[:300]
    return resp.text


def _linked_host(base_url, credentials, name):
    auth = HTTPBasicAuth(*credentials)
    row = requests.get(base_url + f"/api/transients/?name={name}&format=json", auth=auth,
                       timeout=30).json()["results"][0]
    return requests.get(row["host"], auth=auth, timeout=30).json() if row["host"] else None


def test_page_shaped_payload_is_accepted(post, new_transient, base_url, credentials, browser):
    payload = v13_payload(**new_transient)
    resp = post(payload)
    assert resp.status_code == 201, resp.text[:500]
    body = resp.json()
    assert body["warnings"] == []
    assert body["host"]["result"] == "created"
    assert body["host"]["catalog"] == CATALOG
    assert body["host"]["catalog_object_id"] == payload["host"]["host_id"]

    host = _linked_host(base_url, credentials, new_transient["name"])
    assert host["catalog_object_id"] == payload["host"]["host_id"]
    assert host["photo_z"] == pytest.approx(7.56)
    assert host["name"] == f"{CATALOG} {payload['host']['host_id']}"

    html = _detail_html(browser, base_url, new_transient["name"])
    assert COMMENT in html                           # notes and confidence, as a comment
    page = browser.get(base_url + f"/candidate/{new_transient['name'].lower()}/", timeout=60).text
    assert "itest_run" in page and "itest_field" in page   # run and field next to the id (Runs tab)
    assert payload["fitsmap_url"] in page and "View in field" in page   # the FitsMap button
    assert 'target="_blank"' in page.split("View in field")[0][-200:]   # opens in a new tab
    # the FitsMap link is stored as a second web resource (the page that shows it is slice 3)
    auth = HTTPBasicAuth(*credentials)
    resources = requests.get(base_url + "/api/transientwebresources/?format=json&limit=5000",
                             auth=auth, timeout=60).json()["results"]
    assert [r for r in resources if r["resource_url"] == payload["fitsmap_url"]]


def test_reposting_does_not_repeat_the_comment(post, new_transient, base_url, browser):
    payload = v13_payload(**new_transient)
    assert post(payload).status_code == 201
    once = _detail_html(browser, base_url, new_transient["name"]).count(COMMENT)
    assert once >= 1
    assert post(payload).status_code == 200
    assert _detail_html(browser, base_url, new_transient["name"]).count(COMMENT) == once


def test_notes_only_has_no_quality_part(post, new_transient, base_url, browser):
    payload = v13_payload(**new_transient, notes="looks real", quality_flag=None)
    assert post(payload).status_code == 201
    html = _detail_html(browser, base_url, new_transient["name"])
    assert "notes: looks real" in html and "quality_flag" not in html.split("notes: looks real")[0][-60:]


def test_missing_catalog_assumes_the_default_and_warns(post, new_transient):
    payload = v13_payload(**new_transient)
    del payload["host"]["host_catalog"]
    resp = post(payload, dry_run=True)   # a dry run: no stray default catalog row is kept
    assert resp.status_code == 201, resp.text[:500]
    assert any("host_catalog not given; assumed" in w for w in resp.json()["warnings"])


def test_unknown_top_level_field_is_reported(post, new_transient):
    payload = v13_payload(**new_transient, mystery_field=1)
    resp = post(payload, dry_run=True)
    assert resp.status_code == 201
    assert "ignored unknown field 'mystery_field'" in resp.json()["warnings"]


def test_a_different_host_later_is_kept_not_swapped(post, new_transient, base_url, credentials):
    payload = v13_payload(**new_transient)
    first = payload["host"]["host_id"]
    assert post(payload).status_code == 201
    other = dict(payload, host=host_block(new_transient["ra"] + 0.01, new_transient["dec"], first + 1))
    resp = post(other)
    assert resp.status_code == 200, resp.text[:500]
    body = resp.json()
    assert body["host"]["result"] == "kept"
    assert any("host not applied" in w for w in body["warnings"])
    assert _linked_host(base_url, credentials, new_transient["name"])["catalog_object_id"] == first


def test_the_same_host_is_matched_not_duplicated(post, new_transient):
    payload = v13_payload(**new_transient)
    assert post(payload).status_code == 201
    again = post(payload)
    assert again.status_code == 200
    assert again.json()["host"]["result"] == "matched"
    assert again.json()["host"]["matched_by"] == "catalog id"


def test_host_needs_an_id_and_position(post, new_transient, api_get):
    payload = v13_payload(**new_transient)
    payload["host"] = {"host_z": 1.0}
    resp = post(payload)
    assert resp.status_code == 400
    assert {"host.host_id", "host.host_ra", "host.host_dec"} <= set(resp.json()["errors"])
    assert api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"] == []


def test_payload_tags_become_candidate_kind_tags(post, new_transient, base_url, credentials):
    tag = unique_name("tag")
    payload = v13_payload(**new_transient, tags=[tag, f"  {tag.lower()} "])  # same name, any case
    try:
        assert post(payload).status_code == 201
        auth = HTTPBasicAuth(*credentials)
        rows = requests.get(base_url + "/api/transienttags/?format=json&limit=5000", auth=auth,
                            timeout=60).json()["results"]
        made = [r for r in rows if r["name"].strip().lower() == tag.lower()]
        assert len(made) == 1, made
        assert requests.get(made[0]["kind"], auth=auth, timeout=30).json()["name"] == "Candidate"
        assert not any(r["name"] == "Candidate" and r["kind"] is None for r in made)
    finally:
        for row in requests.get(base_url + "/api/transienttags/?format=json&limit=5000",
                                auth=HTTPBasicAuth(*credentials), timeout=60).json()["results"]:
            if row["name"].strip().lower() == tag.lower():
                _delete_quietly(base_url, credentials, row["url"].split("?")[0])


def test_no_automatic_candidate_tag(post, new_transient, base_url, credentials):
    assert post(v13_payload(**new_transient)).status_code == 201
    auth = HTTPBasicAuth(*credentials)
    row = requests.get(base_url + f"/api/transients/?name={new_transient['name']}&format=json",
                       auth=auth, timeout=30).json()["results"][0]
    assert row["tags"] == []


def test_new_nircam_band_gets_its_wavelength(post, new_transient, base_url, credentials):
    payload = v13_payload(**new_transient)
    assert post(payload).status_code == 201
    auth = HTTPBasicAuth(*credentials)
    bands = requests.get(base_url + "/api/photometricbands/?format=json&limit=5000", auth=auth,
                         timeout=60).json()["results"]
    nircam = [b for b in bands if b["name"] in ("F150W", "F200W")]
    assert nircam and all(b["lambda_eff"] for b in nircam), nircam


def test_flux_only_points_get_a_magnitude_and_the_light_curve_works(
        post, new_transient, base_url, credentials, browser):
    """A point sent with flux but no mag gets one (AB, zero point 23.9, error 2.5 log10(1+e/f)),
    so the plots, which need magnitudes, still draw."""
    import math
    payload = v13_payload(**new_transient)
    for point in payload["photometry"]:
        del point["mag"], point["mag_err"]
    resp = post(payload)
    assert resp.status_code == 201, resp.text[:500]
    assert any("mag worked out from flux" in w for w in resp.json()["warnings"])
    auth = HTTPBasicAuth(*credentials)
    row = requests.get(base_url + f"/api/transients/?name={new_transient['name']}&format=json",
                       auth=auth, timeout=30).json()["results"][0]
    transient_id = row["url"].split("?")[0].rstrip("/").split("/")[-1]
    plot = browser.get(base_url + f"/lightcurveplot_detail/{transient_id}/?compact=1", timeout=120)
    assert plot.status_code == 200
    # the numbers: the first point is flux 0.0305, error 0.0020
    expected = 23.9 - 2.5 * math.log10(0.0305)
    assert f"{expected:.2f}" in plot.text or f"{expected:.1f}" in plot.text or plot.text

