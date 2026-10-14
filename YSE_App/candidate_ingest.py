"""/add_candidate/: ingest one difference-imaging candidate (#23).

The payload contract is agentic_planning/023-add-candidate-endpoint/contract.md
(v1.0). A candidate is stored as a Transient with status and tag "Candidate";
repeat detections (new IDs from later runs) are matched server-side and appended
to the same Transient. Nothing is written unless the whole request succeeds.
"""
import base64
import datetime
import json
import math

from django.conf import settings as djangoSettings
from django.contrib import auth
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .basicauth import login_or_basic_auth_required
from .common.utilities import find_nearest_within
from .models import (
    AlternateTransientNames, DataQuality, Host, InformationSource, Instrument,
    MagSystem, ObservationGroup, PhotometricBand, Transient, TransientDiffImage,
    TransientPhotData, TransientPhotometry, TransientStatus, TransientTag,
    TransientWebResource,
)

CANDIDATE = 'Candidate'
SUPERSEDED = 'Superseded'
DEFAULT_SOURCE = 'diffpype'
DEFAULT_TELESCOPE = 'JWST'
# AB zero points for flux units, used when the payload omits flux_zero_point.
ZERO_POINTS = {'ujy': 23.9, 'njy': 31.4}
# Re-posted points within this many seconds of an existing one (same band)
# supersede it.
SAME_EPOCH_SECONDS = 1.0


class PayloadError(Exception):
    """Bad request; `errors` maps a field path to a message."""
    def __init__(self, errors):
        super().__init__(errors)
        self.errors = errors


# --- validation -------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(obj, key, path, errors, required=False):
    value = obj.get(key)
    if value is None:
        if required:
            errors[path + key] = 'required'
        return None
    if not _is_number(value):
        errors[path + key] = 'must be a finite number'
        return None
    return float(value)


def _string(obj, key, path, errors, required=False, max_length=None):
    value = obj.get(key)
    if value is None or value == '':
        if required:
            errors[path + key] = 'required'
        return None
    if not isinstance(value, str):
        errors[path + key] = 'must be a string'
        return None
    if max_length and len(value) > max_length:
        errors[path + key] = 'longer than %d characters' % max_length
        return None
    return value


def _urls(obj, key, path, errors):
    value = obj.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors[path + key] = 'must be an object with sci/ref/diff'
        return {}
    urls = {}
    for kind in ('sci', 'ref', 'diff'):
        urls[kind] = _string(value, kind, '%s%s.' % (path, key), errors, max_length=512)
    return urls


def validate_payload(data):
    """Return a normalized copy of the payload, or raise PayloadError."""
    if not isinstance(data, dict):
        raise PayloadError({'': 'body must be a JSON object'})
    errors = {}
    p = {
        'candidate_id': _string(data, 'candidate_id', '', errors, required=True, max_length=64),
        'ra': _number(data, 'ra', '', errors, required=True),
        'dec': _number(data, 'dec', '', errors, required=True),
        'permalink': _string(data, 'permalink', '', errors, required=True, max_length=512),
        'source': _string(data, 'source', '', errors, max_length=64) or DEFAULT_SOURCE,
        'run_id': _string(data, 'run_id', '', errors),
        'field': _string(data, 'field', '', errors),
        'telescope': _string(data, 'telescope', '', errors, max_length=64) or DEFAULT_TELESCOPE,
        'instrument': _string(data, 'instrument', '', errors, required=True, max_length=64),
    }
    if p['ra'] is not None and not 0 <= p['ra'] < 360:
        errors['ra'] = 'must be in [0, 360)'
    if p['dec'] is not None and not -90 <= p['dec'] <= 90:
        errors['dec'] = 'must be in [-90, 90]'

    tags = data.get('tags') or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors['tags'] = 'must be a list of strings'
        tags = []
    p['tags'] = tags

    host = data.get('host')
    if host is not None:
        if not isinstance(host, dict):
            errors['host'] = 'must be an object or null'
            host = None
        else:
            host = {
                'name': _string(host, 'name', 'host.', errors, required=True, max_length=64),
                'ra': _number(host, 'ra', 'host.', errors, required=True),
                'dec': _number(host, 'dec', 'host.', errors, required=True),
                'photo_z': _number(host, 'photo_z', 'host.', errors),
                'photo_z_err': _number(host, 'photo_z_err', 'host.', errors),
                'redshift': _number(host, 'redshift', 'host.', errors),
                'redshift_err': _number(host, 'redshift_err', 'host.', errors),
                'catalog': _string(host, 'catalog', 'host.', errors, max_length=64),
            }
    p['host'] = host

    phot = data.get('photometry')
    if not isinstance(phot, list) or not phot:
        errors['photometry'] = 'must be a non-empty list'
        phot = []
    points = []
    for i, pt in enumerate(phot):
        path = 'photometry[%d].' % i
        if not isinstance(pt, dict):
            errors[path[:-1]] = 'must be an object'
            continue
        point = {
            'band': _string(pt, 'band', path, errors, required=True, max_length=64),
            'mjd': _number(pt, 'mjd', path, errors, required=True),
            'flux': _number(pt, 'flux', path, errors),
            'flux_err': _number(pt, 'flux_err', path, errors),
            'flux_unit': _string(pt, 'flux_unit', path, errors, required=True),
            'flux_zero_point': _number(pt, 'flux_zero_point', path, errors),
            'mag': _number(pt, 'mag', path, errors),
            'mag_err': _number(pt, 'mag_err', path, errors),
            'limit_sigma': _number(pt, 'limit_sigma', path, errors),
            'stamps': _urls(pt, 'stamps', path, errors),
            'fits': _urls(pt, 'fits', path, errors),
        }
        upper_limit = pt.get('upper_limit')
        if not isinstance(upper_limit, bool):
            errors[path + 'upper_limit'] = 'required, true or false'
        point['upper_limit'] = bool(upper_limit)
        if point['flux_zero_point'] is None and point['flux_unit']:
            point['flux_zero_point'] = ZERO_POINTS.get(point['flux_unit'].lower())
        if point['upper_limit']:
            if point['limit_sigma'] is None:
                errors[path + 'limit_sigma'] = 'required when upper_limit is true'
            if point['flux_err'] is None and point['mag'] is None:
                errors[path + 'flux_err'] = 'flux_err or a limiting mag is required for an upper limit'
        elif point['flux'] is None and point['mag'] is None:
            errors[path + 'flux'] = 'flux/flux_err or mag/mag_err is required for a detection'
        points.append(point)
    p['photometry'] = points

    if errors:
        raise PayloadError(errors)
    return p


# --- lookups ----------------------------------------------------------------

def find_by_name(model, name):
    """The row whose name matches ignoring case and surrounding whitespace
    (compared in Python, so collation doesn't matter; same rule as migration
    0005), or None. For small lookup tables only."""
    wanted = name.strip().lower()
    for obj in model.objects.order_by('id'):
        if (obj.name or '').strip().lower() == wanted:
            return obj
    return None


def _named(model, name, what):
    obj = find_by_name(model, name)
    if obj is None:
        raise LookupError('%s "%s" is missing from the database (the candidate rows come from '
                          'migration 0005; run `manage.py migrate`)' % (what, name))
    return obj


def _instrument(p):
    instruments = Instrument.objects.filter(name__iexact=p['instrument'],
                                            telescope__name__iexact=p['telescope'])
    if not instruments.exists():
        raise PayloadError({'instrument': 'unknown instrument "%s" on telescope "%s"'
                            % (p['instrument'], p['telescope'])})
    return instruments.order_by('id').first()


def _obs_group(p):
    group = find_by_name(ObservationGroup, p['telescope'])
    return group or _named(ObservationGroup, 'Unknown', 'ObservationGroup')


def _band(instrument, name, user):
    band = PhotometricBand.objects.filter(instrument=instrument, name=name).order_by('id').first()
    if band is None:
        # Bands are created lazily for a known instrument, like the ingest CLI.
        band = PhotometricBand.objects.create(instrument=instrument, name=name,
                                              created_by=user, modified_by=user)
    return band


def _tags(names):
    tags, unknown = [], []
    for name in names:
        tag = find_by_name(TransientTag, name)
        if tag is None:
            unknown.append(name)
        else:
            tags.append(tag)
    if unknown:
        raise PayloadError({'tags': 'unknown tag(s): %s' % ', '.join(unknown)})
    return tags


MJD_EPOCH = datetime.datetime(1858, 11, 17, tzinfo=datetime.timezone.utc)


def _obs_date(mjd):
    return MJD_EPOCH + datetime.timedelta(days=mjd)


def _snr(point):
    if point['upper_limit']:
        return -1.0
    if point['flux'] is not None and point['flux_err']:
        return point['flux'] / point['flux_err']
    if point['mag_err']:
        return 1.0857 / point['mag_err']
    return 0.0


# --- ingest -----------------------------------------------------------------

def _find_existing(p):
    """Same candidate_id (as name or alias) first, then position."""
    by_name = Transient.objects.filter(name=p['candidate_id']).order_by('id').first()
    if by_name is not None:
        return by_name, None
    alias = AlternateTransientNames.objects.filter(name=p['candidate_id']).order_by('id').first()
    if alias is not None:
        return alias.transient, None
    return find_nearest_within(Transient.objects.all(), p['ra'], p['dec'],
                               djangoSettings.TRANSIENT_MATCH_RADIUS_ARCSEC)


def _attach_host(transient, h, user):
    if h is None:
        return
    if transient.host is None:
        host = Host.objects.filter(name=h['name']).order_by('id').first()
        if host is None:
            host, _ = find_nearest_within(Host.objects.all(), h['ra'], h['dec'],
                                          djangoSettings.TRANSIENT_MATCH_RADIUS_ARCSEC)
        if host is None:
            host = Host.objects.create(name=h['name'], ra=h['ra'], dec=h['dec'],
                                       created_by=user, modified_by=user)
        transient.host = host
    host = transient.host
    changed = False
    for field in ('photo_z', 'photo_z_err', 'redshift', 'redshift_err'):
        if h[field] is not None and getattr(host, field) is None:
            setattr(host, field, h[field])
            changed = True
    if h['catalog'] and h['photo_z'] is not None and not host.photo_z_source:
        host.photo_z_source = h['catalog']
        changed = True
    if changed:
        host.modified_by = user
        host.save()


def _add_photometry(transient, p, instrument, obs_group, user):
    superseded = _named(DataQuality, SUPERSEDED, 'DataQuality')
    ab = find_by_name(MagSystem, 'AB')
    photometry = TransientPhotometry.objects.filter(
        transient=transient, instrument=instrument, obs_group=obs_group).order_by('id').first()
    if photometry is None:
        photometry = TransientPhotometry.objects.create(
            transient=transient, instrument=instrument, obs_group=obs_group,
            created_by=user, modified_by=user)

    added = n_superseded = 0
    for pt in p['photometry']:
        band = _band(instrument, pt['band'], user)
        obs_date = _obs_date(pt['mjd'])
        window = datetime.timedelta(seconds=SAME_EPOCH_SECONDS)
        older = TransientPhotData.objects.filter(
            photometry__transient=transient, photometry__instrument=instrument, band=band,
            obs_date__gte=obs_date - window, obs_date__lte=obs_date + window,
        ).exclude(data_quality=superseded)
        for old in older:
            old.data_quality.add(superseded)
            n_superseded += 1

        flux, flux_err, mag, mag_err = pt['flux'], pt['flux_err'], pt['mag'], pt['mag_err']
        zp = pt['flux_zero_point']
        if pt['upper_limit']:
            # No limit column: keep flux/flux_err so the limit is recoverable
            # (and plotted by the existing light-curve code), not a mag.
            if flux_err is None and mag is not None and zp is not None:
                flux_err = 10 ** (-0.4 * (mag - zp)) / pt['limit_sigma']
            mag = mag_err = None

        photdata = TransientPhotData.objects.create(
            photometry=photometry, band=band, obs_date=obs_date,
            flux=flux, flux_err=flux_err, flux_zero_point=zp, mag=mag, mag_err=mag_err,
            mag_sys=ab, diffim=True, created_by=user, modified_by=user)
        added += 1

        stamps, fits = pt['stamps'], pt['fits']
        if any(stamps.values()) or any(fits.values()):
            TransientDiffImage.objects.create(
                phot_data=photdata,
                postage_stamp_file=stamps.get('sci'), postage_stamp_ref=stamps.get('ref'),
                postage_stamp_diff=stamps.get('diff'),
                postage_stamp_file_fits=fits.get('sci'), postage_stamp_ref_fits=fits.get('ref'),
                postage_stamp_diff_fits=fits.get('diff'),
                created_by=user, modified_by=user)
    return added, n_superseded


def _set_headline_stamps(transient, p):
    """Fill Transient.postage_stamp_* (the grid thumbnail) if still empty, from
    the highest-S/N detection that has stamps."""
    if transient.postage_stamp_file:
        return
    with_stamps = [pt for pt in p['photometry'] if any(pt['stamps'].values())]
    if not with_stamps:
        return
    best = max(with_stamps, key=_snr)
    transient.postage_stamp_file = best['stamps'].get('sci')
    transient.postage_stamp_ref = best['stamps'].get('ref')
    transient.postage_stamp_diff = best['stamps'].get('diff')
    transient.postage_stamp_file_fits = best['fits'].get('sci')
    transient.postage_stamp_ref_fits = best['fits'].get('ref')
    transient.postage_stamp_diff_fits = best['fits'].get('diff')


def ingest_candidate(p, user):
    """Create or append; returns the response body. Call inside a transaction."""
    status = _named(TransientStatus, CANDIDATE, 'TransientStatus')
    candidate_tag = _named(TransientTag, CANDIDATE, 'TransientTag')
    instrument = _instrument(p)
    obs_group = _obs_group(p)
    extra_tags = _tags(p['tags'])
    source = find_by_name(InformationSource, p['source'])
    if source is None:
        source = InformationSource.objects.create(name=p['source'], created_by=user, modified_by=user)

    detections = [_obs_date(pt['mjd']) for pt in p['photometry'] if not pt['upper_limit']]
    transient, separation = _find_existing(p)
    created = transient is None
    if created:
        transient = Transient.objects.create(
            name=p['candidate_id'], ra=p['ra'], dec=p['dec'], status=status, obs_group=obs_group,
            disc_date=min(detections) if detections else None,
            created_by=user, modified_by=user)
    else:
        # Append only: name, slug, ra/dec and status are never changed.
        if detections and (transient.disc_date is None or min(detections) < transient.disc_date):
            transient.disc_date = min(detections)
        if p['candidate_id'] != transient.name and not AlternateTransientNames.objects.filter(
                transient=transient, name=p['candidate_id']).exists():
            AlternateTransientNames.objects.create(
                transient=transient, obs_group=obs_group, name=p['candidate_id'],
                created_by=user, modified_by=user)

    # The Candidate tag marks candidates; a match on an existing non-candidate
    # transient keeps its own status and tags.
    if transient.status_id == status.id:
        transient.tags.add(candidate_tag)
    if extra_tags:
        transient.tags.add(*extra_tags)

    if not TransientWebResource.objects.filter(transient=transient, resource_url=p['permalink']).exists():
        TransientWebResource.objects.create(
            transient=transient, information_source=source, information_text=p['candidate_id'],
            resource_url=p['permalink'], created_by=user, modified_by=user)

    _attach_host(transient, p['host'], user)
    added, n_superseded = _add_photometry(transient, p, instrument, obs_group, user)
    _set_headline_stamps(transient, p)
    transient.modified_by = user
    transient.save()

    return {
        'result': 'created' if created else 'appended',
        'transient': transient.name,
        'url': reverse('transient_detail', kwargs={'slug': transient.slug or transient.name}),
        'match_separation_arcsec': None if separation is None else round(separation, 4),
        'photometry_added': added,
        'photometry_superseded': n_superseded,
    }


def _request_user(request):
    if request.user.is_authenticated:
        return request.user
    # login_or_basic_auth_required has already validated these credentials.
    _, credentials = request.META['HTTP_AUTHORIZATION'].split(' ', 1)
    username, password = base64.b64decode(credentials.strip()).decode('utf-8').split(':', 1)
    return auth.authenticate(username=username, password=password)


@csrf_exempt
@login_or_basic_auth_required
def add_candidate(request):
    if request.method != 'POST':
        return JsonResponse({'errors': {'': 'POST only'}}, status=405)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'errors': {'': 'body is not valid JSON'}}, status=400)

    try:
        payload = validate_payload(data)
        user = _request_user(request)
        with transaction.atomic():
            body = ingest_candidate(payload, user)
    except PayloadError as e:
        return JsonResponse({'errors': e.errors}, status=400)
    except LookupError as e:
        return JsonResponse({'errors': {'': str(e)}}, status=500)

    return JsonResponse(body, status=201 if body['result'] == 'created' else 200)
