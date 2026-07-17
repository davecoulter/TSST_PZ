"""Integration tests for the YSE_PZ /add_transient/ ingest endpoint."""
import pytest

from conftest import unique_name
from payloads import (
    minimal_transient,
    transient_with_photometry,
    build_photometry,
    load_rows,
    filters_in,
    detections,
)

pytestmark = pytest.mark.integration


def test_minimal_transient_returns_success(post_transient, new_transient):
    """A brand-new transient with only the required fields is accepted."""
    resp = post_transient(minimal_transient(new_transient))
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["message"] == "success"


def test_transient_with_photometry_returns_success(post_transient, new_transient):
    """A transient carrying one photometry point ingests cleanly."""
    resp = post_transient(transient_with_photometry(new_transient))
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["message"] == "success"


def test_photometry_reupload_is_idempotent(post_transient, new_transient):
    """Re-posting the same photometry with clobber must not 500."""
    payload = transient_with_photometry(new_transient, clobber=True)
    first = post_transient(payload)
    second = post_transient(payload)
    assert first.status_code == 200, first.text[:500]
    assert second.status_code == 200, second.text[:500]
    assert second.json()["message"] == "success"


def test_bad_credentials_are_rejected(post_transient, new_transient):
    """Basic-auth with a wrong password is forbidden."""
    resp = post_transient(
        minimal_transient(new_transient), user="djones", pw="definitely-wrong"
    )
    assert resp.status_code == 403


def test_created_transient_values_and_defaults(
    post_transient, fetch_transient, api_get, new_transient
):
    """Read a created transient back and assert its stored fields."""
    resp = post_transient(minimal_transient(new_transient))
    assert resp.status_code == 200, resp.text[:500]

    obj = fetch_transient(new_transient["name"])

    # --- values we assigned ---
    assert obj["name"] == new_transient["name"]
    assert obj["ra"] == pytest.approx(new_transient["ra"])
    assert obj["dec"] == pytest.approx(new_transient["dec"])
    assert obj["slug"] == new_transient["name"].lower()  # AutoSlugField slugifies (lowercases) the name
    # foreign keys are hyperlinks that resolve to the reference rows we named
    assert api_get(obj["status"])["name"] == "New"
    assert api_get(obj["obs_group"])["name"] == "Unknown"
    # audit fields are auto-populated
    assert obj["created_date"]
    assert obj["modified_date"]

    # --- fields we left unset keep their model defaults (null / empty) ---
    unset_null_fields = [
        "ra_err", "dec_err", "disc_date", "candidate_hosts",
        "redshift", "redshift_err", "redshift_source",
        "non_detect_date", "non_detect_limit", "non_detect_band",
        "mw_ebv", "abs_mag_peak", "abs_mag_peak_date", "abs_mag_peak_band",
        "host", "best_spec_class", "photo_class", "context_class",
        "best_spectrum", "antares_classification", "internal_survey",
        "point_source_probability", "real_bogus_score",
        "has_hst", "has_spitzer", "has_chandra",
    ]
    for field in unset_null_fields:
        assert obj[field] is None, f"expected {field} to default to null, got {obj[field]!r}"
    assert obj["tags"] == []


def test_delete_as_admin_succeeds(post_transient, fetch_transient, api_delete, new_transient):
    """An admin can delete a transient over HTTP."""
    post_transient(minimal_transient(new_transient))
    url = fetch_transient(new_transient["name"])["url"].split("?")[0]
    assert api_delete(url).status_code == 204
    assert api_delete(url).status_code == 404  # already gone


def test_delete_as_non_admin_forbidden(
    post_transient, fetch_transient, api_delete, nonadmin_credentials, new_transient
):
    """A non-admin authenticated user cannot delete a transient."""
    post_transient(minimal_transient(new_transient))
    url = fetch_transient(new_transient["name"])["url"].split("?")[0]
    user, pw = nonadmin_credentials
    assert api_delete(url, user=user, pw=pw).status_code == 403
    # the new_transient fixture removes the row as admin on teardown


def test_transient_with_jwst_lightcurve(
    post_transient, new_transient, staged_jwst_lightcurve, download_photometry
):
    """Ingest a real JWST NIRCam light curve (resources/lc_0.txt) and verify it
    bound to the staged JWST instrument/bands, not the 'Unknown' fallback."""
    rows = staged_jwst_lightcurve["rows"]
    inst = staged_jwst_lightcurve["instrument"]

    payload = minimal_transient(new_transient)
    payload[new_transient["name"]]["transientphotometry"] = build_photometry(rows, inst)
    resp = post_transient(payload)
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["message"] == "success"

    # strong read-back: SNANA columns are
    #   OBS: mjd band flux fluxerr mag magerr magsys telescope instrument dq
    obs = [
        line.split()
        for line in download_photometry(new_transient["name"]).splitlines()
        if line.startswith("OBS:")
    ]
    assert len(obs) == len(detections(rows))                     # every detection landed
    assert all(parts[9] == inst for parts in obs)                # bound to our instrument
    assert {parts[2] for parts in obs} <= set(filters_in(rows))  # JWST filters, not Unknown


def test_full_upload_chain_end_to_end(
    api_post, api_get, post_transient, fetch_transient,
    download_photometry, new_transient, cleanup,
):
    """Prod-like walkthrough of the entire upload chain, built from scratch."""
    # 1) Observatory -- the root of the chain (no FK dependencies).
    resp = api_post(
        "/api/observatories/",
        {"name": unique_name("Obs"), "utc_offset": -7, "tz_name": "UTC"},
    )
    assert resp.status_code == 201, resp.text[:500]
    observatory = resp.json()
    cleanup.append(observatory["url"])
    print(f"\n[1] Observatory   -> {observatory['name']}  ({observatory['url']})")

    # 2) Telescope -> Observatory.
    resp = api_post("/api/telescopes/", {
        "name": unique_name("Tel"), "latitude": 19.826, "longitude": -155.478,
        "elevation": 4205.0, "observatory": observatory["url"],
    })
    assert resp.status_code == 201, resp.text[:500]
    telescope = resp.json()
    cleanup.append(telescope["url"])
    assert api_get(telescope["observatory"])["name"] == observatory["name"]
    print(f"[2] Telescope     -> {telescope['name']}  (observatory={observatory['name']})")

    # 3) Instrument -> Telescope.
    resp = api_post(
        "/api/instruments/",
        {"name": unique_name("NIRCam"), "telescope": telescope["url"]},
    )
    assert resp.status_code == 201, resp.text[:500]
    instrument = resp.json()
    cleanup.append(instrument["url"])
    assert api_get(instrument["telescope"])["name"] == telescope["name"]
    print(f"[3] Instrument    -> {instrument['name']}  (telescope={telescope['name']})")

    # 4) PhotometricBand(s) -> Instrument, one per JWST filter in the file.
    rows = load_rows()
    for band_name in filters_in(rows):
        resp = api_post(
            "/api/photometricbands/",
            {"name": band_name, "instrument": instrument["url"]},
        )
        assert resp.status_code == 201, resp.text[:500]
        band = resp.json()
        cleanup.append(band["url"])
        assert api_get(band["instrument"])["name"] == instrument["name"]
        print(f"[4] Band          -> {band['name']}  (instrument={instrument['name']})")

    # 5) TransientTag -- an independent label the ingest binds by name.
    resp = api_post("/api/transienttags/", {"name": unique_name("Tag")})
    assert resp.status_code == 201, resp.text[:500]
    tag = resp.json()
    cleanup.append(tag["url"])
    print(f"[5] Tag           -> {tag['name']}  ({tag['url']})")

    # 6) Ingest the transient + real JWST light curve against the new assets,
    #    labelled with the tag we just created.
    payload = minimal_transient(new_transient)
    payload[new_transient["name"]]["tags"] = [tag["name"]]
    payload[new_transient["name"]]["transientphotometry"] = build_photometry(
        rows, instrument["name"]
    )
    resp = post_transient(payload)
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["message"] == "success"
    print(f"[6] Transient     -> {new_transient['name']}  "
          f"(+{len(rows)} photometry rows, {len(detections(rows))} detections)")

    # 7) The transient landed, bound to the reference enums and tag we named.
    transient = fetch_transient(new_transient["name"])
    assert api_get(transient["status"])["name"] == "New"
    assert api_get(transient["obs_group"])["name"] == "Unknown"
    assert [api_get(t)["name"] for t in transient["tags"]] == [tag["name"]]
    print(f"[7] Read transient-> status=New, obs_group=Unknown, tag={tag['name']}, "
          f"ra={transient['ra']}, dec={transient['dec']}")

    # 8) The photometry read back, bound to our freshly-created instrument/bands.
    obs = [
        line.split()
        for line in download_photometry(new_transient["name"]).splitlines()
        if line.startswith("OBS:")
    ]
    assert len(obs) == len(detections(rows))
    assert all(parts[9] == instrument["name"] for parts in obs)
    assert {parts[2] for parts in obs} == set(filters_in(detections(rows)))
    print(f"[8] Read photometry-> {len(obs)} OBS lines, "
          f"instrument={instrument['name']}, bands={sorted({parts[2] for parts in obs})}")

