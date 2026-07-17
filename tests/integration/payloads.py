"""Request payloads and light-curve helpers for the integration tests."""
import math
import os
from datetime import datetime, timedelta

RESOURCES = os.path.join(os.path.dirname(__file__), "resources")

# MJD day 0 is 1858-11-17 00:00:00 UTC.
_MJD_EPOCH = datetime(1858, 11, 17)


def minimal_transient(t):
    """Smallest valid payload for a brand-new transient.

    `t` is a descriptor dict with ``name``, ``ra`` and ``dec`` keys.
    """
    return {
        "noupdatestatus": True,
        t["name"]: {
            "name": t["name"],
            "ra": t["ra"],
            "dec": t["dec"],
            "obs_group": "Unknown",  # seeded reference row
            "status": "New",         # seeded reference row
        },
    }


def transient_with_photometry(t, instrument="ZTF-Cam", obs_group="ZTF",
                              band="g-ZTF", clobber=True):
    """Minimal transient plus a single photometry point.

    Instrument/obs_group/band default to seeded ZTF reference rows, but can be
    overridden to reference freshly-staged custom assets.
    """
    payload = minimal_transient(t)
    payload[t["name"]]["transientphotometry"] = {
        "mjdmatchmin": 0.01,
        "clobber": clobber,
        "PHOT": {
            "instrument": instrument,
            "obs_group": obs_group,
            "photdata": {
                "0": {
                    "obs_date": "2019-01-10T00:00:00",
                    "band": band,
                    "mag": 18.5,
                    "mag_err": 0.05,
                    "data_quality": 0,
                    "diffim": 1,
                    "flux": None,
                    "flux_err": None,
                    "flux_zero_point": None,
                    "forced": 0,
                    "discovery_point": 0,
                }
            },
        },
    }
    return payload


def mjd_to_isot(mjd):
    """Convert an MJD string/number to an ISOT timestamp the ingest accepts."""
    return (_MJD_EPOCH + timedelta(days=float(mjd))).isoformat()


def _num_or_none(value):
    """Parse a float, mapping 'nan'/unparseable values to None (JSON-safe)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def load_rows(path=None):
    """Return the light curve as a list of {column: str} dicts."""
    path = path or os.path.join(RESOURCES, "lc_0.txt")
    with open(path) as fh:
        header = fh.readline().split()
        return [dict(zip(header, line.split())) for line in fh if line.strip()]


def filters_in(rows):
    """Unique filter (band) names present in the light curve."""
    return sorted({r["filter"] for r in rows})


def detections(rows):
    """Rows that carry a real magnitude (i.e. not a non-detection)."""
    return [r for r in rows if _num_or_none(r["mag"]) is not None]


def build_photometry(rows, instrument_name, obs_group="Unknown", clobber=True):
    """Build an /add_transient/ `transientphotometry` block from the rows.

    Bands are referenced by the file's filter names, so the target instrument
    must have matching PhotometricBand rows for the ingest to bind them.
    """
    photdata = {}
    for i, row in enumerate(rows):
        mag = _num_or_none(row["mag"])
        photdata[str(i)] = {
            "obs_date": mjd_to_isot(row["mjd"]),
            "band": row["filter"],
            "mag": mag,
            "mag_err": _num_or_none(row["magerr"]) if mag is not None else None,
            "flux": _num_or_none(row["flux"]),
            "flux_err": _num_or_none(row["fluxerr"]),
            "flux_zero_point": _num_or_none(row["zp"]),
            "data_quality": 0,
            "diffim": 0,      # JWST mosaic forced photometry, not difference imaging
            "forced": 1,
            "discovery_point": 0,
        }
    return {
        "mjdmatchmin": 0.01,
        "clobber": clobber,
        "JWST": {
            "instrument": instrument_name,
            "obs_group": obs_group,
            "photdata": photdata,
        },
    }
