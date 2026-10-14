"""Candidate pages (#27): the /candidates/ grid, and the "Candidate data" section
of the transient detail page.

Candidates are transients with status "Candidate" (#23). Everything shown here is
read from the rows /add_candidate/ writes (photometry, diff images, web resources,
aliases, host); nothing is stored by these views. Plan:
agentic_planning/027-candidate-pages/plan.md.
"""
from collections import defaultdict

from django.db.models import Count, Max, Min

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .candidate_ingest import CANDIDATE, DEFAULT_SOURCE, SUPERSEDED, find_by_name
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
    for r in resources:
        permalinks[(r.information_text or '').strip()].append(r.resource_url)
    names = [transient.name] + list(AlternateTransientNames.objects
                                    .filter(transient=transient).order_by('id')
                                    .values_list('name', flat=True))
    runs = [{'name': n, 'permalinks': permalinks.pop(n, [])} for n in names]
    # permalinks recorded under an ID that is neither the name nor an alias
    runs += [{'name': n, 'permalinks': urls} for n, urls in permalinks.items()]

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
