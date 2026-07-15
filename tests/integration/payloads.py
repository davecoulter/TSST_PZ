"""Request payloads for the add_transient integration tests.

All FK values referenced here (`Unknown` obs_group, `New` status, the
`ZTF-Cam` instrument, `ZTF` obs_group and the `g-ZTF` band) exist in the
seeded reference data, so a freshly initialized yse_db can satisfy them.
"""


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


def transient_with_photometry(t, clobber=True):
    """Minimal transient plus a single ZTF photometry point."""
    payload = minimal_transient(t)
    payload[t["name"]]["transientphotometry"] = {
        "mjdmatchmin": 0.01,
        "clobber": clobber,
        "ZTF": {
            "instrument": "ZTF-Cam",  # seeded Instrument
            "obs_group": "ZTF",        # seeded ObservationGroup
            "photdata": {
                "0": {
                    "obs_date": "2019-01-10T00:00:00",
                    "band": "g-ZTF",   # seeded PhotometricBand for ZTF-Cam
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
