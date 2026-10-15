"""/add_candidate/: ingest one difference-imaging candidate (#23).

The payload contract is agentic_planning/023-add-candidate-endpoint/contract.md
(v1.0). A candidate is stored as a Transient with status and tag "Candidate";
repeat detections (new IDs from later runs) are matched server-side and appended
to the same Transient. Nothing is written unless the whole request succeeds.
"""
import base64
import datetime
import json
import logging
import math

from django.conf import settings as djangoSettings
from django.contrib import auth
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .basicauth import login_or_basic_auth_required
from .common.jwst_bands import nircam_lambda_eff
from .common.utilities import angular_separation_arcsec, find_nearest_within
from .models import (
    AlternateTransientNames, DataQuality, Host, HostCatalog, InformationSource, Instrument,
    Log, MagSystem, ObservationGroup, PhotometricBand, TagKind, Transient, TransientDiffImage,
    TransientPhotData, TransientPhotometry, TransientStatus, TransientTag,
    TransientWebResource,
)

logger = logging.getLogger(__name__)

CANDIDATE = 'Candidate'
SUPERSEDED = 'Superseded'
DEFAULT_SOURCE = 'diffpype'
DEFAULT_TELESCOPE = 'JWST'
# AB zero points for flux units, used when the payload omits flux_zero_point.
ZERO_POINTS = {'ujy': 23.9, 'njy': 31.4}
# Re-posted points within this many seconds of an existing one (same band)
# supersede it.
SAME_EPOCH_SECONDS = 1.0
# A POST may carry a list of candidates (contract v1.1); cap it so one request can't run forever.
MAX_BATCH = 500
# Fields the endpoint reads; anything else at the top level is reported in `warnings`.
KNOWN_FIELDS = {
    'candidate_id', 'ra', 'dec', 'permalink', 'fitsmap_url', 'source', 'run_id', 'field',
    'telescope', 'instrument', 'tags', 'quality_flag', 'notes', 'host', 'photometry',
}
RUN_SEPARATOR = ' \u00b7 '  # joins candidate id, run and field in a web resource's text


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
    if p['permalink'] is not None and not p['permalink'].lower().startswith(('http://', 'https://')):
        # it is shown as a link on the candidate pages; never accept e.g. javascript:
        errors['permalink'] = 'must be an http:// or https:// URL'
    if p['ra'] is not None and not 0 <= p['ra'] < 360:
        errors['ra'] = 'must be in [0, 360)'
    if p['dec'] is not None and not -90 <= p['dec'] <= 90:
        errors['dec'] = 'must be in [-90, 90]'

    tags = data.get('tags') or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors['tags'] = 'must be a list of strings'
        tags = []
    p['tags'] = [t.strip() for t in tags if t.strip()]
    if any(len(t) > 256 for t in p['tags']):
        errors['tags'] = 'a tag is longer than 256 characters'

    p['fitsmap_url'] = _string(data, 'fitsmap_url', '', errors, max_length=512)
    if p['fitsmap_url'] and not p['fitsmap_url'].lower().startswith(('http://', 'https://')):
        errors['fitsmap_url'] = 'must be an http:// or https:// URL'

    quality = data.get('quality_flag')
    if isinstance(quality, bool) or not (quality is None or isinstance(quality, (int, float, str))):
        errors['quality_flag'] = 'must be a number or a string'
        quality = None
    if isinstance(quality, float) and quality.is_integer():
        quality = int(quality)
    p['quality_flag'] = None if quality is None or str(quality).strip() == '' else str(quality).strip()
    p['notes'] = _string(data, 'notes', '', errors, max_length=4000)
    p['warnings'] = ["ignored unknown field '%s'" % k for k in sorted(set(data) - KNOWN_FIELDS)]

    host = data.get('host')
    if host is not None:
        if not isinstance(host, dict):
            errors['host'] = 'must be an object or null'
            host = None
        else:
            object_id = host.get('host_id')
            if isinstance(object_id, float) and object_id.is_integer():
                object_id = int(object_id)
            if object_id is None:
                errors['host.host_id'] = 'required'
            elif isinstance(object_id, bool) or not isinstance(object_id, int):
                errors['host.host_id'] = 'must be an integer'
            # host_z2 (the MLE) and host_sep are accepted and not stored: the separation is
            # computed from the two positions.
            host = {
                'object_id': object_id,
                'ra': _number(host, 'host_ra', 'host.', errors, required=True),
                'dec': _number(host, 'host_dec', 'host.', errors, required=True),
                'photo_z': _number(host, 'host_z', 'host.', errors),
                'catalog': _string(host, 'host_catalog', 'host.', errors, max_length=255),
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
    wavelength = nircam_lambda_eff(name) if (instrument.name or '').strip().lower() == 'nircam' else None
    if band is None:
        # Bands are created lazily for a known instrument, like the ingest CLI.
        band = PhotometricBand.objects.create(instrument=instrument, name=name, lambda_eff=wavelength,
                                              created_by=user, modified_by=user)
    elif wavelength and not (band.lambda_eff or '').strip():
        band.lambda_eff = wavelength
        band.modified_by = user
        band.save(update_fields=['lambda_eff', 'modified_by', 'modified_date'])
    return band


def _candidate_tags(names, user):
    """Candidate-kind tags for these names: matched ignoring case and whitespace, or
    created. A transient-kind tag with the same name is a different tag."""
    if not names:
        return []
    kind = _named(TagKind, 'Candidate', 'TagKind')
    existing = list(TransientTag.objects.filter(kind=kind).order_by('id'))
    tags = []
    for name in names:
        wanted = name.strip().lower()
        tag = next((t for t in existing if (t.name or '').strip().lower() == wanted), None)
        if tag is None:
            tag = TransientTag.objects.create(name=name.strip(), kind=kind,
                                              created_by=user, modified_by=user)
            existing.append(tag)
        tags.append(tag)
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


def _label(catalog):
    return catalog.nickname or catalog.filename


def _get_catalog(name, user):
    """The HostCatalog whose file name or nickname matches (ignoring case and whitespace), or a
    new one with `name` as its file name."""
    wanted = name.strip().lower()
    for catalog in HostCatalog.objects.order_by('id'):
        if wanted in ((catalog.filename or '').strip().lower(), (catalog.nickname or '').strip().lower()):
            return catalog
    return HostCatalog.objects.create(filename=name.strip(), created_by=user, modified_by=user)


def _host_name(catalog, object_id):
    suffix = ' %d' % object_id
    return (_label(catalog)[:64 - len(suffix)] + suffix)


def _attach_host(transient, h, user, warnings):
    """Find or create the host described by the payload and link it. The first host stays:
    a different later host is reported ('kept'), never swapped in. Returns the reply's
    `host` part, or None when the payload has no host."""
    if h is None:
        return None
    catalog_name = h['catalog']
    if not catalog_name:
        catalog_name = djangoSettings.CANDIDATE_DEFAULT_HOST_CATALOG
        warnings.append("host_catalog not given; assumed '%s'" % catalog_name)
    catalog = _get_catalog(catalog_name, user)

    host = Host.objects.filter(catalog=catalog, catalog_object_id=h['object_id']).order_by('id').first()
    matched_by = 'catalog id' if host else None
    if host is None:
        host, _ = find_nearest_within(Host.objects.all(), h['ra'], h['dec'],
                                      djangoSettings.TRANSIENT_MATCH_RADIUS_ARCSEC)
        matched_by = 'position' if host else None

    info = {'catalog': _label(catalog), 'catalog_object_id': h['object_id'], 'matched_by': matched_by}
    if host is None and transient.host_id is not None:
        # a different host than the one this object already has: don't store it, say so
        offered = angular_separation_arcsec(transient.ra, transient.dec, h['ra'], h['dec'])
        warnings.append("host not applied: this object already has host '%s'; the offered host "
                        "(%s %d) is %.2f arcsec from the object"
                        % (transient.host.name, _label(catalog), h['object_id'], offered))
        info.update(result='kept', name=None, separation_arcsec=round(offered, 4))
        return info

    created = host is None
    if created:
        host = Host.objects.create(name=_host_name(catalog, h['object_id']), ra=h['ra'], dec=h['dec'],
                                   catalog=catalog, catalog_object_id=h['object_id'],
                                   created_by=user, modified_by=user)
    changed = False
    if host.catalog_id is None and host.catalog_object_id is None:
        # found by position but never tied to a catalog: adopt this identity
        host.catalog, host.catalog_object_id = catalog, h['object_id']
        changed = True
    if h['photo_z'] is not None and host.photo_z is None:
        host.photo_z = h['photo_z']
        host.photo_z_source = _label(catalog)[:64]
        changed = True
    if changed:
        host.modified_by = user
        host.save()

    if transient.host_id is None:
        transient.host = host
        outcome = 'created' if created else 'matched'
    elif transient.host_id == host.id:
        outcome = 'matched'
    else:
        outcome = 'kept'
        warnings.append("host not applied: this object already has host '%s'; the offered host '%s' "
                        "is %.2f arcsec from the object"
                        % (transient.host.name, host.name,
                           angular_separation_arcsec(transient.ra, transient.dec, host.ra, host.dec)))
    info.update(result=outcome, name=host.name,
                separation_arcsec=round(angular_separation_arcsec(transient.ra, transient.dec,
                                                                  host.ra, host.dec), 4))
    return info


def _add_comment(transient, p, user):
    """The Save dialog's notes and confidence as one comment by the posting user (a `Log`
    row, like the detail page's comment form), not repeated on a re-post."""
    parts = []
    if p['quality_flag']:
        parts.append('quality_flag: %s' % p['quality_flag'])
    if p['notes']:
        parts.append('notes: %s' % p['notes'])
    if not parts:
        return
    text = '; '.join(parts)
    if not Log.objects.filter(transient=transient, created_by=user, comment=text).exists():
        Log.objects.create(transient=transient, comment=text, created_by=user, modified_by=user)


def _add_fitsmap(transient, p, user):
    url = p['fitsmap_url']
    if not url or TransientWebResource.objects.filter(transient=transient, resource_url=url).exists():
        return
    source = find_by_name(InformationSource, 'FitsMap') or InformationSource.objects.create(
        name='FitsMap', created_by=user, modified_by=user)
    TransientWebResource.objects.create(
        transient=transient, information_source=source, information_text=p['candidate_id'],
        resource_url=url, created_by=user, modified_by=user)


def _resource_text(p):
    """candidate id, then run and field when sent, so the Runs table can show them."""
    return RUN_SEPARATOR.join(x for x in (p['candidate_id'], p['run_id'], p['field']) if x)


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
    instrument = _instrument(p)
    obs_group = _obs_group(p)
    extra_tags = _candidate_tags(p['tags'], user)
    warnings = list(p['warnings'])
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

    # Status is what marks a candidate; the payload's tags are candidate-kind annotations.
    # A match on an existing non-candidate transient keeps its own status.
    if extra_tags:
        transient.tags.add(*extra_tags)

    if not TransientWebResource.objects.filter(transient=transient, resource_url=p['permalink']).exists():
        TransientWebResource.objects.create(
            transient=transient, information_source=source, information_text=_resource_text(p),
            resource_url=p['permalink'], created_by=user, modified_by=user)

    host_info = _attach_host(transient, p['host'], user, warnings)
    _add_fitsmap(transient, p, user)
    _add_comment(transient, p, user)
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
        'host': host_info,
        'warnings': warnings,
    }


def _request_user(request):
    if request.user.is_authenticated:
        return request.user
    # login_or_basic_auth_required has already validated these credentials.
    _, credentials = request.META['HTTP_AUTHORIZATION'].split(' ', 1)
    username, password = base64.b64decode(credentials.strip()).decode('utf-8').split(':', 1)
    return auth.authenticate(username=username, password=password)


def _ingest_one(data, user, dry_run=False):
    """Validate and ingest one candidate in its own transaction.

    Returns (http_status, body). Nothing is written unless the whole candidate
    succeeds. With dry_run the full create-or-append logic runs, then the
    transaction is rolled back, so the reply is exactly what a real run would
    say but nothing is saved."""
    try:
        payload = validate_payload(data)
        with transaction.atomic():
            body = ingest_candidate(payload, user)
            if dry_run:
                transaction.set_rollback(True)
                body['dry_run'] = True
    except PayloadError as e:
        return 400, {'errors': e.errors}
    except LookupError as e:
        return 500, {'errors': {'': str(e)}}
    return (201 if body['result'] == 'created' else 200), body


def _add_batch(items, user, dry_run=False):
    """A list of candidates: each is independent (own transaction, in order, so
    a later item can match an earlier one). The response says which failed."""
    if not items:
        return JsonResponse({'errors': {'': 'the list is empty'}}, status=400)
    if len(items) > MAX_BATCH:
        return JsonResponse({'errors': {'': 'at most %d candidates per request' % MAX_BATCH}}, status=400)
    results = []
    for index, item in enumerate(items):
        try:
            status, body = _ingest_one(item, user, dry_run)
        except Exception:
            logger.exception('add_candidate: unexpected error on item %d', index)
            status, body = 500, {'errors': {'': 'internal error; see the server log'}}
        results.append({
            'index': index,
            'candidate_id': item.get('candidate_id') if isinstance(item, dict) else None,
            'status': status,
            **body,
        })
    summary = {
        'created': sum(r['status'] == 201 for r in results),
        'appended': sum(r['status'] == 200 for r in results),
        'failed': sum(r['status'] not in (200, 201) for r in results),
    }
    if dry_run:
        summary['dry_run'] = True
    return JsonResponse({'summary': summary, 'results': results}, status=200)


@csrf_exempt
@login_or_basic_auth_required
def add_candidate(request):
    if request.method != 'POST':
        return JsonResponse({'errors': {'': 'POST only'}}, status=405)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'errors': {'': 'body is not valid JSON'}}, status=400)

    user = _request_user(request)
    if user is None:
        # never write anything without an authenticated user
        return JsonResponse({'errors': {'': 'authentication failed'}}, status=403)

    dry_run = request.GET.get('dry_run', '').lower() in ('1', 'true', 'yes')
    if isinstance(data, list):
        return _add_batch(data, user, dry_run)
    status, body = _ingest_one(data, user, dry_run)
    return JsonResponse(body, status=status)
