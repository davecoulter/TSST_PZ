"""Integration tests for the YSE_PZ /add_transient/ ingest endpoint.

These run against a *live* deployment (default http://localhost:8000) and are
skipped automatically if it is unreachable. Override the target with the
YSE_URL, YSE_USER and YSE_PW environment variables.

Run with:
    pytest tests/integration
"""
import pytest

from payloads import minimal_transient, transient_with_photometry

pytestmark = pytest.mark.integration


def test_minimal_transient_returns_success(post_transient, new_transient):
    """A brand-new transient with only the required fields is accepted."""
    resp = post_transient(minimal_transient(new_transient))
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["message"] == "success"


def test_transient_with_photometry_returns_success(post_transient, new_transient):
    """A transient carrying one photometry point ingests cleanly.

    Exercises the TransientPhotometry / TransientPhotData path (regression for
    the missing data_quality M2M join table).
    """
    resp = post_transient(transient_with_photometry(new_transient))
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["message"] == "success"


def test_photometry_reupload_is_idempotent(post_transient, new_transient):
    """Re-posting the same photometry with clobber must not 500.

    Regression: the clobber branch reads/writes
    YSE_App_transientphotdata_data_quality, which used to be missing from the
    deployed schema and returned HTTP 500 on the second upload.
    """
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
    """Read a created transient back and assert its stored fields.

    Documents the object shape: the values we supplied are persisted, the
    foreign keys resolve to the reference rows we named, and every field we
    left unset falls back to its model default (null / empty).
    """
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

