"""Candidate pages (#27): the /candidates/ grid, and the "Candidate data" section
of the transient detail page.

Candidates are transients with status "Candidate" (#23). Everything shown here is
read from the rows /add_candidate/ writes (photometry, diff images, web resources,
aliases, host); nothing is stored by these views. Plan:
agentic_planning/027-candidate-pages/plan.md.
"""
import datetime
import re
from collections import defaultdict
from urllib.parse import urlencode

from django.db.models import Count, Max, Min

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import dashboard_sets, view_utils
from .candidate_ingest import CANDIDATE, DEFAULT_SOURCE, RUN_SEPARATOR, SUPERSEDED, _candidate_tags, find_by_name
from .forms import TransientCommentForm
from .transient_names import find_transient, name_q, transient_not_found
from .common.utilities import angular_separation_arcsec
from .models import (
    AlternateTransientNames, Log, TagKind, Transient, TransientDiffImage, TransientPhotData,
    TransientStatus, TransientTag, TransientWebResource, WebAppColor,
)

# A point counts as a detection at or above this flux/flux_err.
DETECTION_SNR = 3.0
ROWS_PER_PAGE = 50
# the Candidates table: (sort key, heading); a numeric or date column sorts high to low first
COLUMNS = [
    ('name', 'Name'), ('newest', 'Discovered'), ('last', 'Last seen'), ('snr', 'Max S/N'), ('quality', 'Score'),
    ('filters', 'Filters \u22653\u03c3'), ('z', 'Host z'), ('detections', 'Detections'),
    ('runs', 'Runs'), ('reporters', 'Reporters'),
]
SORTS = dict(COLUMNS)
_EARLIEST = datetime.datetime(1, 1, 1, tzinfo=datetime.timezone.utc)
# the Save dialog's confidence is stored as the comment text "quality_flag: N; notes: ..."
_QUALITY = re.compile(r'^quality_flag:\s*(\d+(?:\.\d+)?)')
QUALITY_HELP = '1 definite, 2 probable, 3 possible; the average of each reporter\'s latest, lower is better'


def flux_snr(flux, flux_err):
    """flux/flux_err, or None without a usable error. Also used by tns_report (#52)."""
    if flux is None or not flux_err or flux_err <= 0:
        return None
    return flux / flux_err


def is_detection(flux, flux_err, mag):
    """Same rule as the light-curve plots: S/N >= 3, or a mag with no flux. Also used by tns_report
    (#52), so the TNS photometry picker and the candidate pages agree."""
    snr = flux_snr(flux, flux_err)
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
                                 'best_diff': None, 'best_sci': None, '_best_stamp_snr': None,
                                 'last_date': None})
    points = (TransientPhotData.objects
              .filter(photometry__transient_id__in=transient_ids)
              .exclude(data_quality__name=SUPERSEDED)
              .values('id', 'photometry__transient_id', 'band__name', 'flux', 'flux_err', 'mag', 'obs_date'))
    stamps = {d['phot_data_id']: d for d in TransientDiffImage.objects
              .filter(phot_data__photometry__transient_id__in=transient_ids)
              .values('phot_data_id', 'postage_stamp_diff', 'postage_stamp_file')}
    for p in points:
        last = stats[p['photometry__transient_id']]
        if last['last_date'] is None or p['obs_date'] > last['last_date']:
            last['last_date'] = p['obs_date']  # any current point, detection or limit
        if not is_detection(p['flux'], p['flux_err'], p['mag']):
            continue
        s = stats[p['photometry__transient_id']]
        s['n_detections'] += 1
        s['filters'].add(p['band__name'])
        snr = flux_snr(p['flux'], p['flux_err'])
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


def candidate_quality(ids):
    """{transient_id: (average, reporters)} of the quality flag (1 definite, 2 probable, 3 possible):
    each reporter's latest `quality_flag: N` comment counts once."""
    latest = {}
    for transient_id, user_id, comment in (Log.objects
                                           .filter(transient_id__in=ids, comment__startswith='quality_flag:')
                                           .order_by('id')
                                           .values_list('transient_id', 'created_by_id', 'comment')):
        match = _QUALITY.match(comment)
        if match:
            latest[(transient_id, user_id)] = float(match.group(1))
    per_transient = defaultdict(list)
    for (transient_id, _), value in latest.items():
        per_transient[transient_id].append(value)
    return {t: (sum(v) / len(v), len(v)) for t, v in per_transient.items()}


def _sort_value(column, c):
    """The value a table column sorts by, or None when the row has none (those go last)."""
    return {
        'name': lambda: c['transient'].display_name.lower(),
        'newest': lambda: c['transient'].disc_date,
        'last': lambda: c['last_date'],
        'snr': lambda: c['max_snr'],
        'quality': lambda: c['quality'],
        'filters': lambda: len(c['filters']) or None,
        'z': lambda: c['host_z'][0] if c['host_z'] else None,
        'detections': lambda: c['n_detections'],
        'runs': lambda: c['n_runs'],
        'reporters': lambda: c['n_reporters'],
    }[column]()


def _slug(text, taken):
    """A short token for a grid's paging parameter, unique on the page."""
    slug = ''.join(ch for ch in text.lower() if ch.isalnum()) or 'grid'
    while slug in taken:
        slug += '_'
    taken.add(slug)
    return slug


@login_required
def candidate_dashboard(request):
    """The Candidates page (#27, #40): sub-grids, like the main dashboard. They are exclusive: a candidate
    still tagged New is only in the New grid (the backlog, a call to action, always first); once New is
    removed it is in one grid per candidate tag it has, or in No tag, so nothing disappears."""
    status = find_by_name(TransientStatus, CANDIDATE)
    sort = request.GET.get('sort', 'newest')
    if sort not in SORTS:
        sort = 'newest'
    direction = request.GET.get('dir')
    if direction not in ('asc', 'desc'):
        direction = 'asc' if sort in ('name', 'quality') else 'desc'
    query = (request.GET.get('q') or '').strip()

    candidates = []
    if status is not None:
        found = Transient.objects.filter(status=status)
        if query:
            found = found.filter(name_q(query))
        transients = list(found.select_related('host'))
        ids = [t.id for t in transients]
        stats = candidate_stats(ids)
        quality = candidate_quality(ids)
        alias_counts = defaultdict(int)
        internal_names = {t.id: t.name for t in transients}
        for transient_id, alias_name in AlternateTransientNames.objects.filter(
                transient_id__in=ids).values_list('transient_id', 'name'):
            if alias_name != internal_names[transient_id]:  # the old slug kept on renaming (#29)
                alias_counts[transient_id] += 1
        reporters = defaultdict(set)  # who sent each candidate in: the rows' creators
        for transient_id, user_id in (TransientPhotData.objects
                                      .filter(photometry__transient_id__in=ids)
                                      .values_list('photometry__transient_id', 'created_by_id').distinct()):
            reporters[transient_id].add(user_id)
        tag_names = defaultdict(list)  # each candidate's candidate-kind tags
        for transient_id, name in (Transient.tags.through.objects
                                   .filter(transient_id__in=ids, transienttag__kind__name__iexact='Candidate')
                                   .values_list('transient_id', 'transienttag__name')):
            tag_names[transient_id].append(name)
        for t in transients:
            s = stats.get(t.id, {})
            candidates.append({
                'transient': t,
                'max_snr': s.get('max_snr'),
                'filters': sorted(s.get('filters', ())),
                'n_detections': s.get('n_detections', 0),
                'n_runs': 1 + alias_counts[t.id],
                'n_reporters': len(reporters[t.id]),
                'quality': quality[t.id][0] if t.id in quality else None,
                'quality_n': quality[t.id][1] if t.id in quality else 0,
                'last_date': s.get('last_date'),
                'host_z': _host_z(t.host),
                'tag_names': sorted(tag_names[t.id], key=str.lower),
                # the stored headline stamps (#23) are only set on the first post
                'thumb': (s.get('best_diff') or t.postage_stamp_diff
                          or s.get('best_sci') or t.postage_stamp_file),
            })

    # the exclusive sub-grids
    new_name = 'new'
    new = [c for c in candidates if any(n.strip().lower() == new_name for n in c['tag_names'])]
    by_tag, no_tag = defaultdict(list), []
    for c in candidates:
        if c in new:
            continue
        for n in (c['tag_names'] or [None]):
            (by_tag[n] if n is not None else no_tag).append(c)
    groups = [('New', new, True)] + [(n, by_tag[n], False) for n in sorted(by_tag, key=str.lower)]
    if no_tag:
        groups.append(('No tag', no_tag, False))

    def ordered(rows):
        with_value = [c for c in rows if _sort_value(sort, c) is not None]
        without = [c for c in rows if _sort_value(sort, c) is None]
        with_value.sort(key=lambda c: _sort_value(sort, c), reverse=(direction == 'desc'))
        return with_value + without

    taken, grids = set(), []
    for title, rows, is_new in groups:
        slug = _slug(title, taken)
        param = 'page_' + slug
        grids.append({
            'title': title, 'slug': slug, 'is_new': is_new, 'count': len(rows), 'param': param,
            'page': Paginator(ordered(rows), ROWS_PER_PAGE).get_page(request.GET.get(param)),
        })

    headers = []
    for key, label in COLUMNS:
        active = key == sort
        next_dir = ('asc' if direction == 'desc' else 'desc') if active else (
            'asc' if key in ('name', 'quality') else 'desc')
        headers.append({'label': label, 'active': active, 'title': QUALITY_HELP if key == 'quality' else '',
                        'arrow': ('\u25b2' if direction == 'asc' else '\u25bc') if active else '',
                        'href': '?' + urlencode({'sort': key, 'dir': next_dir, 'q': query})})
    context = {
        'grids': grids,
        'n_in_all': len(candidates),   # not n_candidates: the sidebar sets that name (new candidates)
        'n_new': len(new),
        'headers': headers,
        'q': query,
        'sort': sort,
        'dir': direction,
        'query_base': urlencode({'sort': sort, 'dir': direction, 'q': query}),
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
    # renaming to the IAU name keeps the internal name as an alias too (#29): one run, not two
    names = [transient.name] + [n for n in AlternateTransientNames.objects
                                .filter(transient=transient).order_by('id')
                                .values_list('name', flat=True) if n != transient.name]
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
            'snr': flux_snr(pd.flux, pd.flux_err),
            'detection': is_detection(pd.flux, pd.flux_err, pd.mag),
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
        'phot_id': pd.id, 'band': pd.band.name, 'date': pd.obs_date, 'flux': pd.flux, 'flux_err': pd.flux_err,
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


def _epoch_grid(images):
    """Every cutout laid out like the websniff card: for each epoch one column per filter and the
    rows DIFF, SCI, REF. Current and superseded points are grouped separately (they interleave in
    time), current epochs first; superseded ones are hidden behind the toggle."""
    groups = []
    for superseded in (False, True):
        for item in (i for i in images if i['superseded'] == superseded):  # newest first
            date = item['phot'].obs_date
            if groups and groups[-1]['superseded'] == superseded and \
                    groups[-1]['date'] - date <= datetime.timedelta(days=EPOCH_GAP_DAYS):
                groups[-1]['items'].append(item)
            else:
                groups.append({'date': date, 'superseded': superseded, 'items': [item]})
    grid = []
    for g in groups:
        by_band = {}
        for item in g['items']:
            band = item['phot'].band.name
            if band not in by_band or (item['snr'] or float('-inf')) > (by_band[band]['snr'] or float('-inf')):
                by_band[band] = item
        bands = sorted(by_band)
        rows = []
        for label, index in (('DIFF', 2), ('SCI', 0), ('REF', 1)):
            cells = []
            for band in bands:
                item = by_band[band]
                stamp, fits = item['stamps'][index]
                cell = {'url': stamp, 'fits': fits, 'band': band, 'phot_id': item['phot'].id}
                if label == 'DIFF':
                    cell.update(mag=item['phot'].mag, mag_err=item['phot'].mag_err,
                                limit=not item['detection'])
                cells.append(cell)
            rows.append({'label': label, 'cells': cells})
        grid.append({'date': g['date'], 'superseded': g['superseded'], 'bands': bands, 'rows': rows})
    return grid


def photometry_epochs(transient):
    """Current (not superseded) photometry grouped into epochs, points within EPOCH_GAP_DAYS of the
    epoch's first point, newest epoch first."""
    points = (TransientPhotData.objects.filter(photometry__transient=transient)
              .exclude(data_quality__name=SUPERSEDED).select_related('band').order_by('obs_date'))
    epochs = []
    for p in points:
        if epochs and p.obs_date - epochs[-1][0].obs_date <= datetime.timedelta(days=EPOCH_GAP_DAYS):
            epochs[-1].append(p)
        else:
            epochs.append([p])
    return list(reversed(epochs))


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
    host_band = None
    if host_image and best and best['stamps'][1][0] == host_image:
        host_band = best['phot'].band.name
    elif host_image:
        host_band = next((r['band'] for r in refs.values() if r['ref'] == host_image), None)
    ctx.update({
        'candidate_epochs': _epoch_grid(images),
        'candidate_epoch_options': [(i, ep[0].obs_date) for i, ep in enumerate(photometry_epochs(transient))],
        'candidate_host_image_band': host_band,
        'candidate_best': _triplet(best),
        'candidate_best_is_latest': bool(best and latest and best['phot'].id == latest['phot'].id),
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
    # an old slug (alias) or a name typed into the URL redirects to the current slug (#29)
    transient = find_transient(slug, Transient.objects.select_related('host__catalog', 'status'))
    if transient is None:
        return transient_not_found(request, slug)
    if transient.slug and transient.slug != slug:
        return redirect('candidate_detail', slug=transient.slug)

    context = candidate_page_context(transient)
    if not context:
        # nothing from the candidate pipeline: the regular page is the page for this object
        return redirect('transient_detail', slug=transient.slug or transient.name)

    candidate_kind = find_by_name(TagKind, 'Candidate')
    statuses = TransientStatus.objects
    # the backlog, newest first, as on the Candidates page: where Mark triaged and Skip lead
    new_slugs = list(dashboard_sets.new_candidates().order_by('-disc_date', 'id').values_list('slug', flat=True))
    is_new = transient.slug in new_slugs
    next_new = None
    if is_new:
        at = new_slugs.index(transient.slug)
        following = new_slugs[at + 1:] + new_slugs[:at]
        next_new = following[0] if following else None
    quality = candidate_quality([transient.id])
    context.update({
        'candidate_is_new': is_new,
        'candidate_next_new': next_new,
        'candidate_quality': quality.get(transient.id),
        'candidate_quality_help': QUALITY_HELP,
        'transient': transient,
        'logs': Log.objects.filter(transient=transient).select_related('created_by').order_by('id'),
        'transient_comment_form': TransientCommentForm(),
        'candidate_tags_assigned': transient.tags.filter(kind=candidate_kind).select_related('color').order_by('name') if candidate_kind else [],
        'candidate_tags_available': TransientTag.objects.filter(kind=candidate_kind).select_related('color').order_by('name') if candidate_kind else [],
        'all_colors': WebAppColor.objects.all(),
        'all_transient_statuses': statuses.order_by('name'),
        'transient_status_new': statuses.filter(name='New').first(),
        'transient_status_watch': statuses.filter(name='Watch').first(),
        'transient_status_archived': statuses.filter(name='Archived').first(),
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


# --- the SED (observed and rest frame), one epoch at a time ---------------------------

def _transient_host_z(transient):
    """The host's redshift as a number (spec-z, else photo-z), for the rest-frame SED."""
    host = transient.host
    if host is None:
        return None
    if host.redshift is not None:
        return host.redshift
    return host.photo_z


@login_required
def candidate_sed(request, transient_id):
    """Observed and rest-frame SED of one epoch (?epoch=N, 0 is the latest) as Bokeh HTML, like the
    light curve: magnitude against wavelength, limits drawn at the 3-sigma limiting magnitude."""
    import math
    from astropy.cosmology import FlatLambdaCDM
    from bokeh.embed import file_html
    from bokeh.layouts import column
    from bokeh.models import ColumnDataSource, HoverTool
    from bokeh.palettes import Category10
    from bokeh.plotting import figure
    from bokeh.resources import CDN

    transient = Transient.objects.filter(pk=transient_id).select_related('host').first()
    if transient is None:
        raise Http404('Candidate not found')
    epochs = photometry_epochs(transient)
    if not epochs:
        return HttpResponse('<p class="text-muted">No photometry.</p>')
    try:
        index = min(max(int(request.GET.get('epoch', 0)), 0), len(epochs) - 1)
    except ValueError:
        index = 0

    points = []
    for p in epochs[index]:
        try:
            wavelength = float(p.band.lambda_eff) / 1e4  # Angstrom text -> micron
        except (TypeError, ValueError):
            continue
        zero_point = p.flux_zero_point if p.flux_zero_point is not None else 23.9
        if is_detection(p.flux, p.flux_err, p.mag) and p.mag is not None:
            points.append({'band': p.band.name, 'lam': wavelength, 'mag': p.mag,
                           'err': p.mag_err or 0.0, 'limit': False})
        elif p.flux_err and p.flux_err > 0:
            points.append({'band': p.band.name, 'lam': wavelength,
                           'mag': zero_point - 2.5 * math.log10(DETECTION_SNR * p.flux_err),
                           'err': 0.0, 'limit': True})
    if not points:
        return HttpResponse('<p class="text-muted">No bands with a known wavelength in this epoch.</p>')

    colors = {b: Category10[10][i % 10] for i, b in enumerate(sorted({q['band'] for q in points}))}
    z = _transient_host_z(transient)
    cosmo = FlatLambdaCDM(H0=70, Om0=0.3)

    def panel(title, xlabel, ylabel, xs, ys):
        fig = figure(width=600, height=280, sizing_mode='scale_width', title=title,
                     x_axis_label=xlabel, y_axis_label=ylabel, tools='pan,wheel_zoom,box_zoom,reset,save')
        fig.y_range.flipped = True  # brighter at the top
        for limit, marker in ((False, 'circle'), (True, 'inverted_triangle')):
            subset = [i for i, q in enumerate(points) if q['limit'] == limit]
            if not subset:
                continue
            source = ColumnDataSource(dict(
                x=[xs[i] for i in subset], y=[ys[i] for i in subset],
                band=[points[i]['band'] for i in subset],
                color=[colors[points[i]['band']] for i in subset]))
            renderer = getattr(fig, marker)('x', 'y', source=source, size=12, color='color', alpha=0.9)
            fig.add_tools(HoverTool(renderers=[renderer], tooltips=[('band', '@band'), (ylabel, '@y{0.00}')]))
        for i, q in enumerate(points):
            if q['err'] and not q['limit']:
                fig.line([xs[i], xs[i]], [ys[i] - q['err'], ys[i] + q['err']], color=colors[q['band']])
        return fig

    figures = [panel('Observed', 'Observed wavelength (\u03bcm)', 'Observed AB mag',
                     [q['lam'] for q in points], [q['mag'] for q in points])]
    if z is not None and z > 0:
        dm = float(cosmo.distmod(z).value)
        shift = 2.5 * math.log10(1 + z)
        figures.append(panel('Rest frame, z = %.3f' % z, 'Rest wavelength (\u03bcm)', 'Absolute AB mag',
                             [q['lam'] / (1 + z) for q in points],
                             [q['mag'] - dm + shift for q in points]))
    html = file_html(column(*figures, sizing_mode='scale_width'), CDN, 'SED')
    return HttpResponse(html.replace('width: 90%', 'width: 100%'))


# --- candidate tags: add, create or remove one -----------------------------------------

def _tag_json(tag):
    return {'id': tag.id, 'name': tag.name, 'color': str(tag.color) if tag.color_id else ''}


def _find_or_create_candidate_tag(name, user, kind, color=None):
    """The candidate-kind tag with this name (ignoring case and whitespace), or a new one."""
    wanted = name.strip().lower()
    for tag in TransientTag.objects.filter(kind=kind).order_by('id'):
        if (tag.name or '').strip().lower() == wanted:
            return tag
    return TransientTag.objects.create(name=name.strip(), kind=kind, color=color,
                                       created_by=user, modified_by=user)


@login_required
@require_POST
def candidate_tag(request, transient_id):
    """POST action=add|create|remove, name=<tag> and an optional color=<WebAppColor id> (#38).

    add applies the tag to this transient (creating it if new); create makes it available without
    applying it; remove takes it off. The reply lists this transient's candidate tags and every
    candidate tag, which is what the page's widget shows."""
    transient = Transient.objects.filter(pk=transient_id).first()
    if transient is None:
        raise Http404('Candidate not found')
    action = request.POST.get('action')
    name = (request.POST.get('name') or '').strip()
    if action not in ('add', 'create', 'remove') or not name or len(name) > 256:
        return JsonResponse({'errors': 'action must be add, create or remove, and the name 1 to 256 characters'},
                            status=400)
    kind = find_by_name(TagKind, 'Candidate')
    if kind is None:
        return JsonResponse({'errors': 'the Candidate tag kind is missing (run `manage.py migrate`)'},
                            status=500)
    color = WebAppColor.objects.filter(pk=request.POST.get('color')).first() if request.POST.get('color') else None
    if action in ('add', 'create'):
        tag = _find_or_create_candidate_tag(name, request.user, kind, color)
        if action == 'add':
            transient.tags.add(tag)
    else:
        wanted = name.lower()
        for tag in transient.tags.filter(kind=kind):
            if (tag.name or '').strip().lower() == wanted:
                transient.tags.remove(tag)
    return JsonResponse({
        'tags': [_tag_json(t) for t in transient.tags.filter(kind=kind).select_related('color').order_by('name')],
        'available': [_tag_json(t) for t in TransientTag.objects.filter(kind=kind).select_related('color').order_by('name')],
    })
