"""Reporting candidates to TNS (#52): the AT report payload.

- `transient_fields(transient)` reads what one report entry needs from our data (the discovery
  point and the other measured points to pick from, host redshift). These are the per-transient
  values the details form prefills and a reporter may edit. Remarks are left for the reporter:
  our comments judge whether a candidate is real, which is not what a TNS remark is for.
- `default_shared()` gives the batch-wide values the form starts with.
- `at_report_entry(fields, shared)` turns both into one TNS `at_report` entry. It reads no
  database; the preview and the submission both call it.
- `problems(entry)` lists what TNS would reject, before anything is sent.

Field names and required keys follow the TNS bulk report manual (Jan 2025), section 5.5. Ids come
from the TNS values snapshot (`tns_values`), never from code.
Plan: agentic_planning/052-tns-reporting/plan.md (amendments 9-17).
"""
import datetime
import math

from django.conf import settings

from . import tns_values
from .candidate_ingest import SUPERSEDED
from .candidate_views import flux_snr, is_detection
from .common.utilities import GetSexigesimalString
from .models import TransientPhotData

# A detection at or above this S/N makes a discovery (see _discovery).
DISCOVERY_SNR = 5.0
# TNS limits: photometry entries per AT report, AT reports per submission.
MAX_PHOTOMETRY = 10
MAX_ENTRIES = 100
# Ours: the TNS manual gives no limit for remarks.
REMARKS_MAX_LENGTH = 512
# Where host_redshift came from (see host_redshift). A photo-z is sent to 2 decimals, a spec-z to 4:
# more digits read as a spectroscopic redshift.
TRANSIENT_SPEC_Z = 'transient spec-z'
HOST_SPEC_Z = 'host spec-z'
HOST_PHOTO_Z = 'host photo-z'


def tns_date(value):
    """A datetime as the UTC date, `YYYY-MM-DD`. Naive datetimes are taken as UTC. Whole days are
    enough: every transient found in one JWST exposure has that exposure's date."""
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc)
    return value.date().isoformat()


# --- batch values -----------------------------------------------------------

def default_shared():
    """The batch-wide values the form starts with. AT type, units and archive are generic TNS
    conventions from settings.TNS_REPORT_DEFAULTS (labels turned into ids). The per-survey values
    are empty here; the form fills them from the transients' observation group, or the reporter
    types them. Keys are the TNS keys they fill."""
    d = settings.TNS_REPORT_DEFAULTS
    return {
        'reporting_groupid': None,
        'data_source_groupid': None,
        'reporter': '',
        'at_type': tns_values.find_id('at_types', d['at_type']),
        'flux_unitid': tns_values.find_id('units', d['units']),
        'archiveid': tns_values.find_id('archives', d['archive']),
        'archival_remarks': '',
    }


# --- per-transient values from our data -------------------------------------

def point_snr(p):
    """flux/flux_err, or 1.0857/mag_err for a magnitude with no flux, or None."""
    snr = flux_snr(p.flux, p.flux_err)
    if snr is None and p.flux is None and p.mag is not None and p.mag_err:
        snr = 2.5 / math.log(10) / p.mag_err
    return snr


def tns_instrument(instrument):
    """The TNS instrument id for one of ours, matched as '<telescope> - <instrument>'
    ('JWST - NIRCam'), or None when TNS lists no such instrument."""
    return tns_values.find_id('instruments', '%s - %s' % (instrument.telescope.name, instrument.name))


def _discovery(detections):
    """The highest-S/N detection on the (UTC) day of the first point at S/N >= DISCOVERY_SNR, or None.
    JWST takes its filters in quick succession, so they share the day; the strongest one is the
    detection the candidate search would have found."""
    first = next((p for p in detections if (point_snr(p) or 0) >= DISCOVERY_SNR), None)
    if first is None:
        return None
    day = tns_date(first.obs_date)
    return max((p for p in detections if tns_date(p.obs_date) == day), key=lambda p: point_snr(p) or 0)


def _point(p):
    return {'id': p.pk, 'obs_date': p.obs_date, 'band': p.band.name, 'mag': p.mag, 'mag_err': p.mag_err,
            'snr': point_snr(p), 'instrumentid': tns_instrument(p.photometry.instrument)}


def host_redshift(transient):
    """(z, source) for TNS's host_redshift: the transient's spec-z, else the host's spec-z, else the
    host's photo-z; (None, None) when there is none above 0."""
    host = transient.host
    for z, source in ((transient.redshift, TRANSIENT_SPEC_Z),
                      (host.redshift if host is not None else None, HOST_SPEC_Z),
                      (host.photo_z if host is not None else None, HOST_PHOTO_Z)):
        if z is not None and z > 0:
            return z, source
    return None, None


def transient_fields(transient):
    """The per-transient values of one report entry, from current (not superseded) photometry and
    the host:

    {'transient_id', 'internal_name', 'ra', 'dec',
     'discovery_date': the discovery point's date (see _discovery), or None when no point reaches DISCOVERY_SNR,
     'photometry': the points to send, [the discovery point] (or []),
     'detections': every measured point, oldest first, for the reporter to pick from,
     'host_name', 'host_redshift', 'host_redshift_source',
     'remarks': always '', for the reporter to write}

    A point is {'id', 'obs_date', 'band', 'mag', 'mag_err', 'snr', 'instrumentid'}.
    """
    points = (TransientPhotData.objects.filter(photometry__transient=transient)
              .exclude(data_quality__name=SUPERSEDED)
              .select_related('band', 'photometry__instrument__telescope').order_by('obs_date', 'id'))
    detections = [p for p in points if p.mag is not None and is_detection(p.flux, p.flux_err, p.mag)]
    discovery = _discovery(detections)
    z, z_source = host_redshift(transient)
    return {
        'transient_id': transient.pk,
        'internal_name': transient.name,
        'ra': transient.ra,
        'dec': transient.dec,
        'discovery_date': discovery.obs_date if discovery is not None else None,
        'photometry': [_point(discovery)] if discovery is not None else [],
        'detections': [_point(p) for p in detections],
        'host_name': ((transient.host.name or '').strip() if transient.host is not None else ''),
        'host_redshift': z,
        'host_redshift_source': z_source,
        'remarks': '',
    }


# --- the payload ------------------------------------------------------------

def tns_filter(band, instrumentid):
    """(filterid, comments) for one of our band names. TNS lists JWST filters as 'F200W-JWST', so
    the band is looked up as is, then with the instrument's telescope. A band TNS does not list is
    sent as filter 'Other' with a comment naming it ('Filter is JWST-NIRCam-F090W.')."""
    instrument = tns_values.label('instruments', instrumentid) or ''
    telescope, _, camera = instrument.partition(' - ')
    found = tns_values.find_id('filters', band)
    if found is None and telescope:
        found = tns_values.find_id('filters', '%s-%s' % (band, telescope))
    if found is not None:
        return found, ''
    name = '-'.join(x for x in (telescope, camera, band) if x)
    return tns_values.find_id('filters', 'Other') or '', 'Filter is %s.' % name


def _id(value):
    return '' if value is None else str(value)


def _photometry(point, shared):
    filterid, comments = tns_filter(point['band'], point.get('instrumentid'))
    entry = {
        'obsdate': tns_date(point['obs_date']),
        'flux': '' if point['mag'] is None else '%.2f' % point['mag'],
    }
    if point.get('mag_err') is not None:
        entry['flux_error'] = '%.2f' % point['mag_err']
    entry.update({'flux_unitid': _id(shared['flux_unitid']), 'filterid': filterid,
                  'instrumentid': _id(point.get('instrumentid'))})
    if comments:
        entry['comments'] = comments
    return entry


def at_report_entry(fields, shared):
    """One `at_report` entry from a transient's fields (as `transient_fields` returns them, maybe
    edited) and the batch values (as `default_shared` returns them, filled in). Every value is a
    string, as in the TNS manual; a required value we lack is '' so `problems` can name it."""
    ra, dec = GetSexigesimalString(fields['ra'], fields['dec'])
    entry = {
        'ra': {'value': ra},
        'dec': {'value': dec},
        'reporting_groupid': _id(shared['reporting_groupid']),
        'data_source_groupid': _id(shared['data_source_groupid']),
        'reporter': (shared['reporter'] or '').strip(),
        'discovery_datetime': tns_date(fields['discovery_date']) if fields.get('discovery_date') else '',
        'at_type': _id(shared['at_type']),
        'internal_name': fields['internal_name'],
        # returned unchanged in TNS's reply, so the reply can be matched to the transient
        'internal_ids': {'tsst_id': str(fields['transient_id'])},
    }
    if fields.get('host_name'):
        entry['host_name'] = fields['host_name']
    if fields.get('host_redshift'):
        decimals = 2 if fields.get('host_redshift_source') == HOST_PHOTO_Z else 4
        entry['host_redshift'] = '%.*f' % (decimals, fields['host_redshift'])
    if (fields.get('remarks') or '').strip():
        entry['remarks'] = fields['remarks'].strip()
    entry['non_detection'] = {'archiveid': _id(shared['archiveid']),
                              'archival_remarks': (shared['archival_remarks'] or '').strip()}
    entry['photometry'] = {str(i): _photometry(p, shared) for i, p in enumerate(fields['photometry'])}
    return entry


def bulk_report(entries):
    """The `data` JSON object of one TNS submission: {'at_report': {'0': entry, '1': ...}}."""
    if not entries:
        raise ValueError('a TNS report needs at least one entry')
    if len(entries) > MAX_ENTRIES:
        raise ValueError('TNS takes at most %d entries per report, not %d' % (MAX_ENTRIES, len(entries)))
    return {'at_report': {str(i): entry for i, entry in enumerate(entries)}}


_REQUIRED = ('reporting_groupid', 'data_source_groupid', 'reporter', 'discovery_datetime', 'at_type')
_REQUIRED_PHOTOMETRY = ('obsdate', 'flux', 'flux_unitid', 'filterid', 'instrumentid')


def problems(entry):
    """{path: message} for what TNS would reject in one entry (empty when it looks complete):
    missing required values, no or too much photometry, an empty archival remark, long remarks."""
    found = {}
    for key in ('ra', 'dec'):
        if not entry.get(key, {}).get('value'):
            found[key] = 'required'
    for key in _REQUIRED:
        if not entry.get(key):
            found[key] = 'required'
    if len(entry.get('remarks', '')) > REMARKS_MAX_LENGTH:
        found['remarks'] = 'at most %d characters' % REMARKS_MAX_LENGTH

    photometry = entry.get('photometry') or {}
    if not photometry:
        found['photometry'] = 'at least the discovery point is required (no point at S/N >= %g)' % DISCOVERY_SNR
    elif len(photometry) > MAX_PHOTOMETRY:
        found['photometry'] = 'TNS takes at most %d points, not %d' % (MAX_PHOTOMETRY, len(photometry))
    for i, point in photometry.items():
        for key in _REQUIRED_PHOTOMETRY:
            if not point.get(key):
                found['photometry.%s.%s' % (i, key)] = 'required'

    nd = entry.get('non_detection') or {}
    for key in ('archiveid', 'archival_remarks'):
        if not nd.get(key):
            found['non_detection.' + key] = 'required'
    return found
