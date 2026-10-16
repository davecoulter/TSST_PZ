"""Band wavelengths for JWST NIRCam filters, used when /add_candidate/ creates a band.

Pivot wavelengths in microns from the JWST User Documentation, "NIRCam Filters",
Tables 2 and 3 ("Pivot lambda (um)"; the page says the values are based on
commissioning flight data):
https://jwst-docs.stsci.edu/jwst-near-infrared-camera/nircam-instrumentation/nircam-filters
(read 2026-10-15). Approximate by design: real filter curves are a later issue (#42).
Migration 0007 carries its own frozen copy of this table.
"""

NIRCAM_PIVOT_UM = {
    'F070W': 0.705, 'F090W': 0.902, 'F115W': 1.154, 'F140M': 1.405, 'F150W': 1.501,
    'F162M': 1.627, 'F164N': 1.645, 'F150W2': 1.672, 'F182M': 1.845, 'F187N': 1.874,
    'F200W': 1.988, 'F210M': 2.096, 'F212N': 2.121, 'F250M': 2.503, 'F277W': 2.776,
    'F300M': 2.996, 'F322W2': 3.247, 'F323N': 3.237, 'F335M': 3.362, 'F356W': 3.565,
    'F360M': 3.623, 'F405N': 4.053, 'F410M': 4.083, 'F430M': 4.281, 'F444W': 4.402,
    'F460M': 4.630, 'F466N': 4.654, 'F470N': 4.708, 'F480M': 4.817,
}


def nircam_lambda_eff(band_name):
    """`PhotometricBand.lambda_eff` text (Angstroms, like the existing values) for a
    NIRCam filter name, or None when the filter is not in the table."""
    microns = NIRCAM_PIVOT_UM.get((band_name or '').strip().upper())
    return None if microns is None else '%.1f' % (microns * 10000)
