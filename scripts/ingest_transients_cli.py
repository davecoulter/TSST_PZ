#!/usr/bin/env python3
"""CLI tool to bulk-upload JWST transients and their light curves.

Given a transient list, a directory of per-transient light-curve files and one
or more (pre-existing) tags, this walks the list and, for every entry:

  * looks for an existing transient within 0.2" of the row's RA/Dec;
  * if none exists, creates a new transient named after the row's ``cid``;
  * if one exists, appends the light curve to that transient instead;

in both cases the photometry is read from ``<index>_lc.txt`` and ingested via
the normal ``/add_transient/`` endpoint. PhotometricBand rows are created lazily
-- each light-curve band is looked up and stored the first time it is seen.

The telescope and instrument must already exist in the database (the dev seed
data provides Space L2 -> JWST -> NIRCam/NIRSpec/MIRI/NIRISS); the script only
looks them up and hard-fails if they are missing, like it does for tags.

Usage:
    python scripts/ingest_transients_cli.py \\
        --transient-list scripts/resources/jets_cands_labels.txt \\
        --lightcurve-dir scripts/resources/ \\
        --tags COSMOS JADES \\
        --telescope JWST --instrument NIRCam

    # target / credentials come from the environment (or --url/--user/--pw):
    URL=http://localhost:8000 USER_YSE=djones PW=BossTent1 \\
        python scripts/ingest_transients_cli.py --transient-list <list> ...

Credentials authenticate against Django's auth_user table and must belong to an
admin/active user (the seeded `djones` works on a fresh dev DB).
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
from typing import NoReturn

import requests
from requests.auth import HTTPBasicAuth

# --- configuration --------------------------------------------------------

DEFAULT_URL = os.environ.get("URL", "http://localhost:8000")
DEFAULT_USER = os.environ.get("USER_YSE", "djones")
DEFAULT_PW = os.environ.get("PW", "BossTent1")

# Positional match radius for the "does this transient already exist?" check.
MATCH_RADIUS_ARCSEC = 0.2

# MJD day 0 is 1858-11-17 00:00:00 UTC.
_MJD_EPOCH = datetime(1858, 11, 17)


# --- light-curve helpers --------------------------------------------------

def mjd_to_isot(mjd):
    return (_MJD_EPOCH + timedelta(days=float(mjd))).isoformat()


def _num_or_none(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def load_table(path):
    """Read a whitespace-delimited table with a header row into dicts."""
    with open(path) as fh:
        header = fh.readline().split()
        return [dict(zip(header, line.split())) for line in fh if line.strip()]


def angsep_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation between two sky positions, in arcseconds."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    hav = (
        math.sin((dec2 - dec1) / 2) ** 2
        + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2
    )
    return math.degrees(2 * math.asin(math.sqrt(hav))) * 3600.0


# --- REST helpers ---------------------------------------------------------

class Client:
    def __init__(self, base_url, auth):
        self.base = base_url.rstrip("/")
        self.auth = auth

    def _url(self, path):
        return path if path.startswith("http") else self.base + path

    def get(self, path):
        resp = requests.get(self._url(path), auth=self.auth, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def post(self, path, body):
        return requests.post(self._url(path), json=body, auth=self.auth, timeout=60)


def die(message) -> NoReturn:
    """Print an error and hard-fail the whole run."""
    sys.exit(f"error: {message}")


# --- ingest steps ---------------------------------------------------------

def resolve_instrument(client, telescope_name, instrument_name):
    """Return the instrument named `instrument_name` on `telescope_name`.

    Both must already exist in the database (e.g. from the seed data);
    hard-fails otherwise.
    """
    telescopes = client.get("/api/telescopes/?limit=5000").get("results", [])
    telescope = next((t for t in telescopes if t["name"] == telescope_name), None)
    if telescope is None:
        die(f"telescope does not exist in the database: {telescope_name!r}")
    instruments = client.get("/api/instruments/?limit=5000").get("results", [])
    instrument = next(
        (i for i in instruments
         if i["name"] == instrument_name and i["telescope"] == telescope["url"]),
        None,
    )
    if instrument is None:
        die(f"instrument {instrument_name!r} does not exist on telescope {telescope_name!r}")
    return instrument


def load_known_bands(client, instrument):
    """Names of PhotometricBands already stored under `instrument`."""
    page = client.get("/api/photometricbands/?limit=5000")
    return {
        b["name"]
        for b in page.get("results", [])
        if b["instrument"] == instrument["url"]
    }


def ensure_band(client, instrument, band_name, known_bands):
    """Create the band under `instrument` the first time it is seen."""
    if band_name in known_bands:
        return
    resp = client.post(
        "/api/photometricbands/",
        {"name": band_name, "instrument": instrument["url"]},
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"failed to create band {band_name}: HTTP {resp.status_code}\n{resp.text[:500]}"
        )
    known_bands.add(band_name)


def build_photometry(client, instrument, rows, known_bands, mjdmatchmin):
    """Build an /add_transient/ photometry block, storing bands as they appear."""
    photdata = {}
    for i, row in enumerate(rows):
        ensure_band(client, instrument, row["filter"], known_bands)
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
            "diffim": 0,
            "forced": 1,
            "discovery_point": 0,
        }
    return {
        # With the default mjdmatchmin of 0 the server never matches an
        # incoming row to an existing one, so every row is appended as-is.
        # A larger mjdmatchmin makes rows with the same band and an MJD within
        # that window overwrite the stored values (clobber) instead.
        "mjdmatchmin": mjdmatchmin,
        "clobber": True,
        "photometry": {
            "instrument": instrument["name"],
            "obs_group": "Unknown",
            "photdata": photdata,
        },
    }


def find_existing_transient(client, ra, dec, radius_arcsec):
    """Return the nearest transient within `radius_arcsec` of ra/dec, or None."""
    dec_half = radius_arcsec / 3600.0
    cos_dec = max(math.cos(math.radians(dec)), 1e-6)
    ra_half = dec_half / cos_dec
    query = (
        f"/api/transients/?ra_gte={ra - ra_half}&ra_lte={ra + ra_half}"
        f"&dec_gte={dec - dec_half}&dec_lte={dec + dec_half}"
        "&limit=5000&format=json"
    )
    candidates = client.get(query).get("results", [])
    nearest, nearest_sep = None, None
    for cand in candidates:
        sep = angsep_arcsec(ra, dec, cand["ra"], cand["dec"])
        if sep <= radius_arcsec and (nearest_sep is None or sep < nearest_sep):
            nearest, nearest_sep = cand, sep
    return nearest


def ensure_tags_exist(client, tags):
    """Hard-fail unless every TransientTag in `tags` already exists in the DB."""
    page = client.get("/api/transienttags/?limit=5000")
    existing = {t["name"] for t in page.get("results", [])}
    missing = [tag for tag in tags if tag not in existing]
    if missing:
        die(f"tag(s) do not exist in the database: {', '.join(map(repr, missing))}")


# --- main -----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--transient-list", required=True, help="path to the transient list (cid ra dec index)")
    parser.add_argument("--lightcurve-dir", required=True, help="directory holding the <index>_lc.txt files")
    parser.add_argument("--tags", nargs="+", required=True, help="one or more TransientTag names that must already exist in the DB")
    parser.add_argument("--telescope", required=True, help="pre-existing Telescope name (e.g. JWST)")
    parser.add_argument("--instrument", required=True, help="pre-existing Instrument name on that telescope (e.g. NIRCam)")
    parser.add_argument("--mjdmatchmin", type=float, default=0,
                        help="MJD window (days) for matching incoming photometry to "
                             "existing rows; 0 (default) appends everything, >0 "
                             "overwrites matching rows (same band, MJD within window) "
                             "with the latest values")
    parser.add_argument("--url", default=DEFAULT_URL, help="base URL of the app")
    parser.add_argument("--user", default=DEFAULT_USER, help="admin Django username")
    parser.add_argument("--pw", default=DEFAULT_PW, help="Django password")
    args = parser.parse_args()

    # --- validate inputs (hard-fail on any missing precondition) ----------
    if not os.path.isfile(args.transient_list):
        die(f"transient list not found: {args.transient_list}")
    if not os.path.isdir(args.lightcurve_dir):
        die(f"light-curve directory not found: {args.lightcurve_dir}")

    client = Client(args.url, HTTPBasicAuth(args.user, args.pw))
    ensure_tags_exist(client, args.tags)

    instrument = resolve_instrument(client, args.telescope, args.instrument)
    known_bands = load_known_bands(client, instrument)
    print(f"[setup] instrument={instrument['name']}  "
          f"known bands={sorted(known_bands) or 'none'}  tags={', '.join(args.tags)}")

    transients = load_table(args.transient_list)
    created = appended = 0

    for row in transients:
        cid = row["cid"]
        ra, dec = float(row["ra"]), float(row["dec"])
        lc_path = os.path.join(args.lightcurve_dir, f"{row['index']}_lc.txt")
        if not os.path.isfile(lc_path):
            die(f"light-curve file not found for {cid}: {lc_path}")

        lc_rows = load_table(lc_path)
        photometry = build_photometry(client, instrument, lc_rows, known_bands,
                                      args.mjdmatchmin)

        existing = find_existing_transient(client, ra, dec, MATCH_RADIUS_ARCSEC)
        if existing is None:
            name, action = cid, "created"
            created += 1
        else:
            print(f"[match] {cid}: found pre-existing transient "
                  f"{existing['name']!r} within {MATCH_RADIUS_ARCSEC}\" of "
                  f"ra={ra}, dec={dec}")
            name, action = existing["name"], "appended"
            appended += 1

        payload = {
            "noupdatestatus": True,
            name: {
                "name": name,
                "ra": ra,
                "dec": dec,
                "obs_group": "Unknown",
                "status": "New",
                "tags": list(args.tags),
                "transientphotometry": photometry,
            },
        }
        resp = requests.post(
            client.base + "/add_transient/",
            data=json.dumps(payload),
            auth=client.auth,
            timeout=120,
        )
        resp.raise_for_status()
        message = resp.json().get("message", resp.text[:200])
        print(f"[{action}] {cid} -> {name}  ({len(lc_rows)} rows, {message})")

    print(f"\nDone. {created} created, {appended} appended "
          f"({len(transients)} transients processed).")


if __name__ == "__main__":
    main()
