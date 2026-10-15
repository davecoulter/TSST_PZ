"""Candidate pages (#27): the /candidates/ grid, and the "Candidate data" section
of the transient detail page.

Candidates are transients with status "Candidate" (#23). Everything shown here is
read from the rows /add_candidate/ writes (photometry, diff images, web resources,
aliases, host); nothing is stored by these views. Plan:
agentic_planning/027-candidate-pages/plan.md.
"""
import datetime
from collections import defaultdict

from django.db.models import Count, Max, Min

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render

from . import view_utils
from .candidate_ingest import CANDIDATE, DEFAULT_SOURCE, RUN_SEPARATOR, SUPERSEDED, find_by_name
from .common.utilities import angular_separation_arcsec
from .models import (
    AlternateTransientNames, Transient, TransientDiffImage, TransientPhotData,
    TransientStatus, TransientWebResource,
)

# A point counts as a detection at or above this flux/flux_err.
DETECTION_SNR = 3.0
CARDS_PER_PAGE = 24
SORTS = {
    'newest': 'Newest first',
    'snr': 'Max S/N',
    'name': 'Name',
}


def _snr(flux, flux_err):
    if flux is None or not flux_err or flux_err <= 0:
        return None
    return flux / flux_err


def _is_detection(flux, flux_err, mag):
    """Same rule as the light-curve plots: S/N >= 3, or a mag with no flux."""
    snr = _snr(flux, flux_err)
    if snr is not None:
        return snr >= DETECTION_SNR
    return flux is None and mag is not None


def _source_is_candidate_pipeline(name):
    return (name or '').strip().lower() == DEFAULT_SOURCE


def _host_z(host):
    """(value, err, kind) with spec-z preferred over photo-z, or None."""
    if host is None:
        return None
    if host.redshift is not None:
        return host.redshift, host.redshift_err, 'spec'
    if host.photo_z is not None:
        return host.photo_z, host.photo_z_err, 'photo'
    return None


def candidate_stats(transient_ids):
    """Per-transient stats from stored photometry, superseded points excluded.

    Returns {transient_id: {'max_snr', 'filters', 'n_detections', 'best_diff',
    'best_sci'}}, where best_* are the stamps of the highest-S/N detection that
    has any.
    """
    stats = defaultdict(lambda: {'max_snr': None, 'filters': set(), 'n_detections': 0,
                                 'best_diff': None, 'best_sci': None, '_best_stamp_snr': None})
    points = (TransientPhotData.objects
              .filter(photometry__transient_id__in=transient_ids)
              .exclude(data_quality__name=SUPERSEDED)
              .values('id', 'photometry__transient_id', 'band__name', 'flux', 'flux_err', 'mag'))
    stamps = {d['phot_data_id']: d for d in TransientDiffImage.objects
              .filter(phot_data__photometry__transient_id__in=transient_ids)
              .values('phot_data_id', 'postage_stamp_diff', 'postage_stamp_file')}
    for p in points:
        if not _is_detection(p['flux'], p['flux_err'], p['mag']):
            continue
        s = stats[p['photometry__transient_id']]
        s['n_detections'] += 1
        s['filters'].add(p['band__name'])
        snr = _snr(p['flux'], p['flux_err'])
        if snr is not None and (s['max_snr'] is None or snr > s['max_snr']):
            s['max_snr'] = snr
        stamp = stamps.get(p['id'])
        if stamp and (stamp['postage_stamp_diff'] or stamp['postage_stamp_file']):
            rank = snr if snr is not None else float('-inf')
            if s['_best_stamp_snr'] is None or rank > s['_best_stamp_snr']:
                s['_best_stamp_snr'] = rank
                s['best_diff'] = stamp['postage_stamp_diff']
                s['best_sci'] = stamp['postage_stamp_file']
    return stats


@login_required
def candidate_dashboard(request):
    status = find_by_name(TransientStatus, CANDIDATE)
    sort = request.GET.get('sort', 'newest')
    if sort not in SORTS:
        sort = 'newest'

    candidates = []
    if status is not None:
        transients = list(Transient.objects.filter(status=status).select_related('host'))
        ids = [t.id for t in transients]
        stats = candidate_stats(ids)
        alias_counts = defaultdict(int)
        for transient_id in AlternateTransientNames.objects.filter(
                transient_id__in=ids).values_list('transient_id', flat=True):
            alias_counts[transient_id] += 1
        for t in transients:
            s = stats.get(t.id, {})
            candidates.append({
                'transient': t,
                'max_snr': s.get('max_snr'),
                'filters': sorted(s.get('filters', ())),
                'n_detections': s.get('n_detections', 0),
                'n_runs': 1 + alias_counts[t.id],
                'host_z': _host_z(t.host),
                # the stored headline stamps (#23) are only set on the first post
                'thumb': (s.get('best_diff') or t.postage_stamp_diff
                          or s.get('best_sci') or t.postage_stamp_file),
                'thumb_sci': s.get('best_sci') or t.postage_stamp_file,
            })

    if sort == 'snr':
        candidates.sort(key=lambda c: (c['max_snr'] is None, -(c['max_snr'] or 0)))
    elif sort == 'name':
        candidates.sort(key=lambda c: c['transient'].name.lower())
    else:
        candidates.sort(key=lambda c: (c['transient'].disc_date is None,
                                       -(c['transient'].disc_date.timestamp()
                                         if c['transient'].disc_date else 0)))

    page = Paginator(candidates, CARDS_PER_PAGE).get_page(request.GET.get('page'))
    context = {
        'page': page,
        'n_candidates': len(candidates),
        'sort': sort,
        'sorts': SORTS,
    }
    return render(request, 'YSE_App/candidate_dashboard.html', context)


def candidate_section_context(transient):
    """Context for the detail page's "Candidate data" section, or {} when the
    transient has no candidate-pipeline data and isn't a candidate."""
    resources = [r for r in TransientWebResource.objects.filter(transient=transient)
                 .select_related('information_source').order_by('id')
                 if _source_is_candidate_pipeline(r.information_source.name)]
    is_candidate = (transient.status.name or '').strip().lower() == CANDIDATE.lower()
    if not resources and not is_candidate:
        return {}

    # Runs: each candidate ID (the name, then aliases) with its websniff page.
    permalinks = defaultdict(list)
    details = {}  # run and field, when the pipeline sent them (stored after the id)
    for r in resources:
        key, _, detail = (r.information_text or '').strip().partition(RUN_SEPARATOR)
        key = key.strip()
        permalinks[key].append(r.resource_url)
        if detail:
            details.setdefault(key, detail)
    names = [transient.name] + list(AlternateTransientNames.objects
                                    .filter(transient=transient).order_by('id')
                                    .values_list('name', flat=True))
    runs = [{'name': n, 'permalinks': permalinks.pop(n, []), 'detail': details.get(n, '')} for n in names]
    # permalinks recorded under an ID that is neither the name nor an alias
    runs += [{'name': n, 'permalinks': urls, 'detail': details.get(n, '')} for n, urls in permalinks.items()]

    images = []
    for d in (TransientDiffImage.objects
              .filter(phot_data__photometry__transient=transient)
              .select_related('phot_data__band__instrument')
              .prefetch_related('phot_data__data_quality')
              .order_by('-phot_data__obs_date', 'phot_data__band__name')):
        pd = d.phot_data
        images.append({
            'phot': pd,
            'stamps': [(d.postage_stamp_file, d.postage_stamp_file_fits),
                       (d.postage_stamp_ref, d.postage_stamp_ref_fits),
                       (d.postage_stamp_diff, d.postage_stamp_diff_fits)],
            'snr': _snr(pd.flux, pd.flux_err),
            'detection': _is_detection(pd.flux, pd.flux_err, pd.mag),
            'superseded': any(q.name == SUPERSEDED for q in pd.data_quality.all()),
        })

    # Who flagged it: every POST adds photometry rows created by the poster
    # (re-posts too, as new rows that supersede the old ones), so the rows'
    # created_by covers everyone who sent this candidate in.
    flagged_by = list(TransientPhotData.objects
                      .filter(photometry__transient=transient)
                      .values('created_by__username', 'created_by__first_name',
                              'created_by__last_name')
                      .annotate(n_points=Count('id'), first=Min('created_date'),
                                last=Max('created_date'))
                      .order_by('first'))

    return {
        'candidate_section': True,
        'candidate_flagged_by': flagged_by,
        'candidate_runs': runs,
        'candidate_images': images,
        'candidate_n_superseded': sum(1 for i in images if i['superseded']),
        'candidate_host_z': _host_z(transient.host),
    }


# --- the candidate page (/candidate/<slug>/) ---------------------------------------

EPOCH_GAP_DAYS = 1.0  # points within a day of each other are one epoch


def _best(items):
    """Highest S/N among items, detections before non-detections."""
    return max(items, key=lambda i: (i['detection'], i['snr'] if i['snr'] is not None else float('-inf')))


def _triplet(item):
    """What the page shows for one point: its three cutouts and its numbers."""
    if item is None:
        return None
    pd = item['phot']
    (sci, sci_fits), (ref, ref_fits), (diff, diff_fits) = item['stamps']
    return {
        'band': pd.band.name, 'date': pd.obs_date, 'flux': pd.flux, 'flux_err': pd.flux_err,
        'mag': pd.mag, 'mag_err': pd.mag_err, 'snr': item['snr'], 'detection': item['detection'],
        'cutouts': [('SCI', sci, sci_fits), ('REF', ref, ref_fits), ('DIFF', diff, diff_fits)],
    }


def _links(transient):
    """The websniff page (latest candidate-pipeline resource) and the FitsMap view."""
    permalink = fitsmap = None
    for r in (TransientWebResource.objects.filter(transient=transient)
              .select_related('information_source').order_by('-id')):
        name = (r.information_source.name or '').strip().lower()
        if permalink is None and name == DEFAULT_SOURCE:
            permalink = r.resource_url
        elif fitsmap is None and name == 'fitsmap':
            fitsmap = r.resource_url
    return {'permalink': permalink, 'fitsmap': fitsmap}


def candidate_pointer_context(transient):
    """What the transient page needs to point at the candidate page: {} when the
    object has no candidate-pipeline data and is not a candidate."""
    is_candidate = (transient.status.name or '').strip().lower() == CANDIDATE.lower()
    links = _links(transient)
    has_data = links['permalink'] is not None or TransientDiffImage.objects.filter(
        phot_data__photometry__transient=transient).exists()
    if not (is_candidate or has_data):
        return {}
    return {'candidate_pointer': True, 'candidate_links': links}


def candidate_page_context(transient):
    """Everything the candidate page shows, or {} when the object has no candidate data."""
    ctx = candidate_section_context(transient)
    if not ctx:
        return {}
    images = ctx['candidate_images']
    current = [i for i in images if not i['superseded']]
    with_stamps = [i for i in current if any(stamp for stamp, _ in i['stamps'])]

    best = _best(with_stamps) if with_stamps else None
    latest = None
    if with_stamps:
        newest = max(i['phot'].obs_date for i in with_stamps)
        epoch = [i for i in with_stamps
                 if newest - i['phot'].obs_date <= datetime.timedelta(days=EPOCH_GAP_DAYS)]
        latest = _best(epoch)

    # reference cutouts: the most recent one in each filter; the host image is the reference of
    # the best detection (no supernova light in it), else the best one there is
    refs = {}
    for i in current:
        ref, ref_fits = i['stamps'][1]
        if ref and (i['phot'].band.name not in refs
                    or i['phot'].obs_date > refs[i['phot'].band.name]['date']):
            refs[i['phot'].band.name] = {'band': i['phot'].band.name, 'ref': ref,
                                         'fits': ref_fits, 'date': i['phot'].obs_date, 'item': i}
    host_image = None
    if best and best['stamps'][1][0]:
        host_image = best['stamps'][1][0]
    elif refs:
        host_image = _best([r['item'] for r in refs.values()])['stamps'][1][0]

    filters_seen = {i['phot'].band.name for i in current}
    filters_detected = {i['phot'].band.name for i in current if i['detection']}
    snrs = [i['snr'] for i in current if i['detection'] and i['snr'] is not None]

    host = transient.host
    ctx.update({
        'candidate_best': _triplet(best),
        'candidate_latest': _triplet(latest),
        'candidate_ref_gallery': sorted(({k: v for k, v in r.items() if k != 'item'}
                                         for r in refs.values()), key=lambda r: r['band']),
        'candidate_host_image': host_image,
        'candidate_filters_seen': len(filters_seen),
        'candidate_filters_detected': len(filters_detected),
        'candidate_max_snr': max(snrs) if snrs else None,
        'candidate_links': _links(transient),
        'candidate_host_sep': (angular_separation_arcsec(transient.ra, transient.dec, host.ra, host.dec)
                               if host else None),
        'candidate_host_catalog': (host.catalog.nickname or host.catalog.filename)
                                  if host and host.catalog_id else None,
    })
    return ctx


@login_required
def candidate_detail(request, slug):
    transient = Transient.objects.filter(slug=slug).select_related('host__catalog', 'status').first()
    if transient is None:
        alias = AlternateTransientNames.objects.filter(slug=slug).select_related('transient').first()
        if alias is not None:
            return redirect('candidate_detail', slug=alias.transient.slug)
        raise Http404('Candidate not found')

    context = candidate_page_context(transient)
    if not context:
        # nothing from the candidate pipeline: the regular page is the page for this object
        return redirect('transient_detail', slug=transient.slug or transient.name)

    statuses = TransientStatus.objects
    context.update({
        'transient': transient,
        'all_transient_statuses': statuses.order_by('name'),
        'transient_status_follow': statuses.filter(name='Following').first(),
        'transient_status_watch': statuses.filter(name='Watch').first(),
        'transient_status_interesting': statuses.filter(name='Interesting').first(),
        'transient_status_ignore': statuses.filter(name='Ignore').first(),
    })
    # the existing Photometric Summary, as the transient page builds it
    last = view_utils.get_recent_phot_for_transient(request.user, transient_id=transient.id)
    first = view_utils.get_disc_mag_for_transient(request.user, transient_id=transient.id)
    if last and first:
        context.update({
            'recent_mag': last.mag, 'recent_filter': last.band, 'recent_magdate': last.obs_date,
            'first_mag': first.mag, 'first_filter': first.band, 'first_magdate': first.obs_date,
        })
    return render(request, 'YSE_App/candidate_detail.html', context)

