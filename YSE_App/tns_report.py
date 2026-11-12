"""Reporting candidates to TNS (#52): the AT report payload.

- `transient_fields(transient)` reads what one report entry needs from our data (the discovery
  point and the other measured points to pick from, host redshift). These are the per-transient
  values the details form prefills and a reporter may edit. Remarks are left for the reporter:
  our comments judge whether a candidate is real, which is not what a TNS remark is for.
- `default_shared()` gives the batch-wide values the form starts with.
- `at_report_entry(fields, shared)` turns both into one TNS `at_report` entry. It reads no
  database; the preview and the submission both call it.
- `problems(entry)` lists what TNS would reject, before anything is sent; `describe(entry)` lists
  every value with its TNS label, for the preview.

Field names and required keys follow the TNS bulk report manual (Jan 2025), section 5.5. Ids come
from the TNS values (`tns_values`, TNS's own lists), never from code.
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
# The two kinds of non-detection TNS takes (one is required): an archive the transient is absent
# from, with a remark, or a dated observation with its limiting magnitude (amendment 18).
ND_ARCHIVAL = 'archival'
ND_OBSERVATION = 'observation'


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
        'non_detection': ND_ARCHIVAL,
        'archiveid': tns_values.find_id('archives', d['archive']),
        'archival_remarks': '',
        # an observed non-detection: our data does not have it yet, so the reporter enters it
        'nd_obsdate': '',
        'nd_limiting_flux': '',
        'nd_filterid': None,
        'nd_instrumentid': None,
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

def other_filter():
    """TNS's filter id for 'Other': a filter TNS does not list, named in the point's comment."""
    return tns_values.find_id('filters', 'Other') or ''


def filter_comment(band, instrumentid):
    """The comment that names one of our bands when it is sent as filter 'Other'
    ('Filter is JWST-NIRCam-F090W.')."""
    telescope, _, camera = (tns_values.label('instruments', instrumentid) or '').partition(' - ')
    return 'Filter is %s.' % '-'.join(x for x in (telescope, camera, band) if x)


def tns_filter(band, instrumentid):
    """(filterid, comments) for one of our band names. TNS lists JWST filters as 'F200W-JWST', so
    the band is looked up as is, then with the instrument's telescope. A band TNS does not list is
    sent as filter 'Other' with a comment naming it (filter_comment)."""
    telescope = (tns_values.label('instruments', instrumentid) or '').partition(' - ')[0]
    found = tns_values.find_id('filters', band)
    if found is None and telescope:
        found = tns_values.find_id('filters', '%s-%s' % (band, telescope))
    if found is not None:
        return found, ''
    return other_filter(), filter_comment(band, instrumentid)


def format_redshift(z, source):
    """A redshift as TNS gets it, and as the form shows it: a photo-z to 2 decimals, a spec-z to 4
    (more digits read as spectroscopic). '' for none."""
    if z is None:
        return ''
    return '%.*f' % (2 if source == HOST_PHOTO_Z else 4, z)


def _id(value):
    return '' if value is None else str(value)


def _photometry(point, shared):
    """One photometry entry. The filter comes from the band (tns_filter) unless the reporter chose
    one ('filterid' in the point, with its 'comments'); a comment is sent only with filter 'Other'."""
    if 'filterid' in point:
        filterid = _id(point['filterid'])
        comments = (point.get('comments') or '').strip() if filterid == other_filter() else ''
    else:
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


def _non_detection(shared):
    """The entry's non_detection: an observation (date, limiting magnitude in the batch's units,
    filter, instrument) when shared['non_detection'] says so, else the archive and its remark."""
    if shared.get('non_detection') == ND_OBSERVATION:
        return {'obsdate': shared.get('nd_obsdate') or '', 'limiting_flux': shared.get('nd_limiting_flux') or '',
                'flux_unitid': _id(shared['flux_unitid']), 'filterid': _id(shared.get('nd_filterid')),
                'instrumentid': _id(shared.get('nd_instrumentid'))}
    return {'archiveid': _id(shared['archiveid']), 'archival_remarks': (shared['archival_remarks'] or '').strip()}


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
        entry['host_redshift'] = format_redshift(fields['host_redshift'], fields.get('host_redshift_source'))
    if (fields.get('remarks') or '').strip():
        entry['remarks'] = fields['remarks'].strip()
    entry['non_detection'] = _non_detection(shared)
    entry['photometry'] = {str(i): _photometry(p, shared) for i, p in enumerate(fields['photometry'])}
    return entry


def bulk_report(entries):
    """The `data` JSON object of one TNS submission: {'at_report': {'0': entry, '1': ...}}."""
    if not entries:
        raise ValueError('a TNS report needs at least one entry')
    if len(entries) > MAX_ENTRIES:
        raise ValueError('TNS takes at most %d entries per report, not %d' % (MAX_ENTRIES, len(entries)))
    return {'at_report': {str(i): entry for i, entry in enumerate(entries)}}


# entry keys that hold a TNS id, and the TNS values kind that labels it
_LABELLED = {'reporting_groupid': 'groups', 'data_source_groupid': 'groups', 'at_type': 'at_types',
             'flux_unitid': 'units', 'filterid': 'filters', 'instrumentid': 'instruments', 'archiveid': 'archives'}


def describe(entry, prefix=''):
    """[(path, value, label)] for every value in an entry, nested keys joined with '.'
    ('photometry.0.filterid'). label is the TNS label of an id, None for an id TNS never had, and ''
    for a value that is not an id."""
    rows = []
    for key, value in entry.items():
        path = prefix + key
        if isinstance(value, dict):
            rows += describe(value, path + '.')
        else:
            kind = _LABELLED.get(key)
            rows.append((path, value, tns_values.label(kind, value) if kind and value != '' else ''))
    return rows


_REQUIRED = ('reporting_groupid', 'data_source_groupid', 'reporter', 'discovery_datetime', 'at_type')
_REQUIRED_PHOTOMETRY = ('obsdate', 'flux', 'flux_unitid', 'filterid', 'instrumentid')
# TNS requires all but the limit; we require it too, since a non-detection without one says little
_REQUIRED_NON_DETECTION = ('obsdate', 'limiting_flux', 'flux_unitid', 'filterid', 'instrumentid')


def problems(entry, today=None):
    """{path: message} for what TNS would reject in one entry (empty when it looks complete):
    missing required values, no or too much photometry, an incomplete non-detection (or one not before
    the discovery), long remarks, an id TNS never had or no longer lists. Also a date after `today`
    (UTC, by default now): TNS accepts those (it named a 2028 discovery "2028A"), so we refuse them."""
    found = {}
    for path, value, text in describe(entry):
        kind = _LABELLED.get(path.rsplit('.', 1)[-1])
        if kind and value != '' and text is None:
            found[path] = 'not a TNS id (%s)' % value
        elif kind and value != '' and not tns_values.listed(kind, value):
            found[path] = 'TNS no longer lists %s (%s)' % (text, value)
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
        if point.get('filterid') and point['filterid'] == other_filter() and not point.get('comments'):
            found['photometry.%s.comments' % i] = 'name the filter: it is sent as "Other"'

    nd = entry.get('non_detection') or {}
    observed = 'obsdate' in nd
    for key in (_REQUIRED_NON_DETECTION if observed else ('archiveid', 'archival_remarks')):
        if not nd.get(key):
            found['non_detection.' + key] = 'required'
    # TNS's blocking error 1; with whole days, the same day does not precede
    discovery = entry.get('discovery_datetime')
    if observed and nd.get('obsdate') and discovery and nd['obsdate'] >= discovery:
        found['non_detection.obsdate'] = 'must be before the discovery date (%s)' % discovery

    today = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    dated = [('discovery_datetime', discovery), ('non_detection.obsdate', nd.get('obsdate') if observed else None)]
    dated += [('photometry.%s.obsdate' % i, point.get('obsdate')) for i, point in photometry.items()]
    for path, date in dated:
        if date and date > today:  # YYYY-MM-DD strings compare as dates
            found[path] = 'in the future (%s; today is %s)' % (date, today)
    return found
