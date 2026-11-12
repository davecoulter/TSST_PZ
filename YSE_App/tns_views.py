"""TNS report pages (#52): pick transients, fill in the details, preview the payload.

- /tns/report/: transients without an IAU name, one box per observation group, with checkboxes.
- /tns/report/details/: the batch values, one row per transient (the photometry to send, host,
  remarks, per-row survey values), and beside each row the payload TNS would get.
- /tns/report/preview/: the payload for the details form as it stands, built by `build_report`.
- /tns/report/submit/: the same payload, sent to TNS as the chosen bot (tns_attempts).
- /tns/report/<batch>/: a submission's results; .../check/ asks TNS for the outcome.
- /tns/report/history/: every submission.

Open to the "TNS Reporters" group only; superusers are not let in by default (amendment 19).
Stage 2: nothing is sent to TNS.
Plan: agentic_planning/052-tns-reporting/plan.md.
"""
import datetime
import functools
import json
from collections import defaultdict

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import tns_attempts, tns_client, tns_report, tns_values
from .candidate_ingest import CANDIDATE
from .common.utilities import date_to_mjd, mjd_to_date
from .candidate_views import candidate_stats
from .models import TNSBot, TNSReportAttempt, Transient, TransientStatus, TransientTag

TNS_REPORTERS = 'TNS Reporters'  # the group, created by migration 0011
TARGET_HOSTS = {'sandbox': 'sandbox.wis-tns.org', 'production': 'www.wis-tns.org'}
# the per-survey batch values and the ObservationGroup field each one starts from (the reporter text
# and the archival remark are per report: typed for the batch)
SURVEY_KEYS = (('reporting_groupid', 'tns_reporting_group_id'), ('data_source_groupid', 'tns_data_source_group_id'))
# the non-detection values (amendment 18): set for the batch, and a row can override each one
NON_DETECTION_KEYS = ('non_detection', 'archiveid', 'archival_remarks', 'nd_obsdate', 'nd_limiting_flux',
                      'nd_filterid', 'nd_instrumentid')
BATCH_KEYS = ('reporting_groupid', 'data_source_groupid', 'reporter', 'at_type', 'flux_unitid') + NON_DETECTION_KEYS
ROW_KEYS = tuple(key for key, _ in SURVEY_KEYS) + NON_DETECTION_KEYS
Z_SOURCES = (tns_report.TRANSIENT_SPEC_Z, tns_report.HOST_SPEC_Z, tns_report.HOST_PHOTO_Z)


def is_tns_reporter(user):
    """Membership of TNS_REPORTERS, given on purpose: being a superuser is not enough, since a report
    goes out under the TSST bot's name."""
    return user.is_authenticated and user.groups.filter(name=TNS_REPORTERS).exists()


def tns_reporter_required(view):
    """Login first (a redirect), then 403 for anyone not in TNS_REPORTERS."""
    @functools.wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_tns_reporter(request.user):
            raise PermissionDenied('The TNS report pages are for the "%s" group.' % TNS_REPORTERS)
        return view(request, *args, **kwargs)
    return wrapped


def _target():
    """What every TNS page shows: which TNS, and how current its values are."""
    return {'tns_target': settings.TNS_TARGET, 'tns_host': TARGET_HOSTS[settings.TNS_TARGET],
            'tns_production': settings.TNS_TARGET == 'production', 'tns_values_as_of': tns_values.as_of()}


def _ids(values):
    ids = []
    for value in values:
        if str(value).isdigit() and int(value) not in ids:
            ids.append(int(value))
    return ids


def _transients(ids):
    """The transients with these ids that have no IAU name yet, in the order given."""
    found = {t.pk: t for t in Transient.objects.filter(pk__in=ids, iau_name__isnull=True)
             .select_related('obs_group', 'host')}
    return [found[i] for i in ids if i in found]


# --- select -----------------------------------------------------------------

@tns_reporter_required
def tns_report_select(request):
    """Transients without an IAU name, filtered by status (Candidate by default) and candidate tag,
    one box per observation group: the group's TNS values start the details form."""
    status_name = request.GET.get('status', CANDIDATE)
    tag_name = (request.GET.get('tag') or '').strip()
    found = Transient.objects.filter(iau_name__isnull=True, status__name__iexact=status_name)
    if tag_name:
        found = found.filter(tags__name__iexact=tag_name).distinct()
    transients = list(found.select_related('obs_group', 'host').order_by('-disc_date', 'name'))
    ids = [t.pk for t in transients]
    stats = candidate_stats(ids)
    tags = defaultdict(list)
    for transient_id, name in (Transient.tags.through.objects.filter(transient_id__in=ids)
                               .values_list('transient_id', 'transienttag__name')):
        tags[transient_id].append(name)

    attempts = tns_attempts.latest(ids)  # each transient's latest TNS report, for its badge (amendment 29)
    by_group = defaultdict(list)
    for t in transients:
        s = stats.get(t.pk, {})
        z, z_source = tns_report.host_redshift(t)
        attempt = attempts.get(t.pk)
        by_group[t.obs_group].append({
            'transient': t, 'max_snr': s.get('max_snr'), 'filters': sorted(s.get('filters', ())),
            'attempt': attempt, 'blocked': attempt is not None and attempt.status == TNSReportAttempt.PENDING,
            'z': tns_report.format_redshift(z, z_source), 'z_source': z_source, 'tags': sorted(tags[t.pk], key=str.lower),
        })
    groups = [{'group': g, 'rows': by_group[g], 'has_tns': bool(g.tns_reporting_group_id or g.tns_data_source_group_id)}
              for g in sorted(by_group, key=lambda g: g.name.lower())]
    context = dict(_target(), groups=groups, n=len(transients), status=status_name, tag=tag_name,
                   statuses=TransientStatus.objects.order_by('name').values_list('name', flat=True),
                   tag_names=TransientTag.objects.filter(kind__name__iexact='Candidate').order_by('name')
                   .values_list('name', flat=True),
                   max_entries=tns_report.MAX_ENTRIES, bots=_bots())
    return render(request, 'YSE_App/tns_report_select.html', context)


# --- details ----------------------------------------------------------------

def _survey_values(group):
    return {key: ((getattr(group, attr) if group is not None else None) or '').strip() for key, attr in SURVEY_KEYS}


def initial_values(transients):
    """(batch, overrides) the details form starts with. A per-survey batch value is the one every
    transient's observation group agrees on ('' when they differ or have none); a row's override is
    its group's value where that differs from the batch value."""
    batch = tns_report.default_shared()
    per_row = [_survey_values(t.obs_group) for t in transients]
    for key, _ in SURVEY_KEYS:
        values = {row[key] for row in per_row}
        batch[key] = values.pop() if len(values) == 1 else ''
    overrides = [{key: (row[key] if row[key] != batch[key] else '') for key, _ in SURVEY_KEYS} for row in per_row]
    return batch, overrides


def _labelled(point):
    """A detection for the picker: TNS's whole-day date, the MJD to order points within a day, and the
    TNS filter and instrument it starts with (the reporter can change both). The comment names the
    band, for when the filter is 'Other'."""
    filterid, _ = tns_report.tns_filter(point['band'], point['instrumentid'])
    return dict(point, date=tns_report.tns_date(point['obs_date']), mjd=date_to_mjd(point['obs_date']),
                filterid=filterid, filter_label=tns_values.label('filters', filterid),
                filter_comment=tns_report.filter_comment(point['band'], point['instrumentid']),
                instrument_label=tns_values.label('instruments', point['instrumentid']))


@tns_reporter_required
def tns_report_details(request):
    """The details form for the transients picked on the select page (?t=<id>&t=<id>...)."""
    transients = _transients(_ids(request.GET.getlist('t')))
    if not transients:
        return redirect('tns_report_select')
    if len(transients) > tns_report.MAX_ENTRIES:
        return render(request, 'YSE_App/tns_report_details.html', dict(
            _target(), too_many=len(transients), max_entries=tns_report.MAX_ENTRIES))
    batch, overrides = initial_values(transients)
    rows = []
    for t, override in zip(transients, overrides):
        fields = tns_report.transient_fields(t)
        picked = {p['id'] for p in fields['photometry']}
        rows.append({
            'transient': t, 'fields': fields, 'override': override,
            'discovery_id': fields['photometry'][0]['id'] if fields['photometry'] else None,
            'discovery_date': tns_report.tns_date(fields['discovery_date']) if fields['discovery_date'] else '',
            'host_redshift': tns_report.format_redshift(fields['host_redshift'], fields['host_redshift_source']),
            'detections': [dict(_labelled(d), picked=d['id'] in picked) for d in fields['detections']],
        })
    context = dict(
        _target(), rows=rows, batch=batch, bots=_bots(),
        group_choices=tns_values.choices('groups'), at_type_choices=tns_values.choices('at_types'),
        unit_choices=tns_values.choices('units'), archive_choices=tns_values.choices('archives'),
        filter_choices=tns_values.choices('filters'), instrument_choices=tns_values.choices('instruments'),
        nd_archival=tns_report.ND_ARCHIVAL, nd_observation=tns_report.ND_OBSERVATION, other_filter=tns_report.other_filter(),
        z_sources=Z_SOURCES, max_photometry=tns_report.MAX_PHOTOMETRY, remarks_max=tns_report.REMARKS_MAX_LENGTH)
    return render(request, 'YSE_App/tns_report_details.html', context)


# --- the payload from the form ----------------------------------------------

def _batch(post):
    shared = tns_report.default_shared()
    for key in BATCH_KEYS:
        shared[key] = (post.get(key) or '').strip() or None
    return shared


def _number(text):
    """A form value as a float, None when empty; ValueError otherwise."""
    text = (text or '').strip()
    return float(text) if text else None


def _chosen(post, prefix, point):
    """(point, errors) for a picked point, with what the form set for it on top of our data: the MJD,
    magnitude and error (amendment 26), and the TNS filter, instrument and comment. A value the form
    did not post (e.g. a locked field) keeps ours. A value that does not parse keeps ours too, and
    errors ({TNS key: message}) says so."""
    point, key, errors = dict(point), '%sp%d-' % (prefix, point['id']), {}
    if key + 'filterid' in post:
        point['filterid'] = post[key + 'filterid'].strip() or None
        point['comments'] = post.get(key + 'comments') or ''
    if key + 'instrumentid' in post:
        point['instrumentid'] = post[key + 'instrumentid'].strip() or None
    if key + 'mjd' in post:
        try:
            point['obs_date'] = datetime.datetime.fromisoformat(mjd_to_date(float(post[key + 'mjd']))).replace(
                tzinfo=datetime.timezone.utc)
        except (TypeError, ValueError, OverflowError):
            errors['obsdate'] = 'an MJD'
    if key + 'mag' in post:
        try:
            point['mag'] = _number(post[key + 'mag'])  # empty: problems() asks for it
        except ValueError:
            errors['flux'] = 'a magnitude'
    if key + 'mag_err' in post:
        try:
            point['mag_err'] = _number(post[key + 'mag_err'])
        except ValueError:
            errors['flux_error'] = 'a number, or empty'
    return point, errors


def _row(post, transient):
    """(fields, overrides, errors) for one transient: our data with the form's values on top."""
    prefix = 'r%d-' % transient.pk
    fields = tns_report.transient_fields(transient)
    errors = {}

    current = {str(d['id']): d for d in fields['detections']}
    picked = set(post.getlist(prefix + 'phot'))
    if picked - set(current):
        errors['photometry'] = 'points %s are not current detections of this transient' % ', '.join(sorted(picked - set(current)))
    # The reporter must name the discovery point: it is always sent, as TNS's entry 0, and the
    # discovery date is its date (edited through its MJD, never typed apart), so the two cannot disagree.
    discovery = (post.get(prefix + 'discovery') or '').strip()
    if discovery not in current:
        errors['discovery_datetime'] = ('pick the discovery point' if not discovery
                                        else 'the discovery point is not a current detection of this transient')
        discovery = None
    else:
        picked.add(discovery)
    chosen = sorted((_chosen(post, prefix, d) for d in fields['detections'] if str(d['id']) in picked),
                    key=lambda pe: (str(pe[0]['id']) != discovery, pe[0]['obs_date']))
    fields['photometry'] = [point for point, _ in chosen]
    for i, (_, point_errors) in enumerate(chosen):
        errors.update({'photometry.%d.%s' % (i, k): message for k, message in point_errors.items()})
    fields['discovery_date'] = fields['photometry'][0]['obs_date'] if discovery else None

    fields['host_name'] = (post.get(prefix + 'host_name') or '').strip()
    z = (post.get(prefix + 'host_redshift') or '').strip()
    fields['host_redshift'] = None
    if z:
        try:
            fields['host_redshift'] = float(z)
        except ValueError:
            errors['host_redshift'] = 'a number'
        else:
            if fields['host_redshift'] <= 0:
                errors['host_redshift'] = 'above 0, or empty'
    source = post.get(prefix + 'host_redshift_source')
    fields['host_redshift_source'] = source if source in Z_SOURCES else None
    fields['remarks'] = post.get(prefix + 'remarks') or ''

    overrides = {key: (post.get(prefix + key) or '').strip() for key in ROW_KEYS}
    return fields, {key: value for key, value in overrides.items() if value}, errors


def _non_detection(values):
    """(values, errors): the batch values for one row with the non-detection kind settled and an
    observation's date and limit checked and normalized ('YYYY-MM-DD', a 2-decimal magnitude).
    Missing values are left to tns_report.problems."""
    values, errors = dict(values), {}
    if values.get('non_detection') not in (tns_report.ND_ARCHIVAL, tns_report.ND_OBSERVATION):
        values['non_detection'] = tns_report.ND_ARCHIVAL
    if values['non_detection'] != tns_report.ND_OBSERVATION:
        return values, errors
    date = values.get('nd_obsdate') or ''
    if date:
        try:
            values['nd_obsdate'] = datetime.datetime.strptime(date, '%Y-%m-%d').date().isoformat()
        except ValueError:
            errors['non_detection.obsdate'] = 'a date, YYYY-MM-DD'
            values['nd_obsdate'] = ''
    limit = values.get('nd_limiting_flux') or ''
    if limit:
        try:
            values['nd_limiting_flux'] = '%.2f' % float(limit)
        except ValueError:
            errors['non_detection.limiting_flux'] = 'a number: the limiting magnitude'
            values['nd_limiting_flux'] = ''
    return values, errors


def build_report(post, transients):
    """The report the details form describes: {'ok', 'payload', 'entries'}, where each entry is
    {'transient_id', 'name', 'rows' (tns_report.describe), 'problems' ({path: message})}. The preview
    shows it; stage 3's submission sends `payload` only when `ok`."""
    shared = _batch(post)
    entries, out = [], []
    for t in transients:
        fields, overrides, errors = _row(post, t)
        values, nd_errors = _non_detection(dict(shared, **overrides))
        errors.update(nd_errors)
        entry = tns_report.at_report_entry(fields, values)
        entries.append(entry)
        found = dict(tns_report.problems(entry), **errors)
        out.append({'transient_id': t.pk, 'name': t.name, 'rows': tns_report.describe(entry), 'problems': found})
    return {'ok': not any(e['problems'] for e in out), 'payload': tns_report.bulk_report(entries), 'entries': out}


@tns_reporter_required
@require_POST
def tns_report_preview(request):
    """JSON: build_report for the posted details form. Sends nothing to TNS."""
    transients = _transients(_ids(request.POST.getlist('t')))
    if not transients:
        return JsonResponse({'error': 'no transients without an IAU name were posted'}, status=400)
    if len(transients) > tns_report.MAX_ENTRIES:
        return JsonResponse({'error': 'TNS takes at most %d per report' % tns_report.MAX_ENTRIES}, status=400)
    return JsonResponse(dict(build_report(request.POST, transients), target=settings.TNS_TARGET))


# --- submitting and results (stage 3, amendment 29) --------------------------

def _bots():
    """[(bot, has a key here)] of the active bots, for "Report as": one without a key is shown, greyed out."""
    return [(bot, tns_client.has_key(bot)) for bot in TNSBot.objects.filter(active=True)]


@tns_reporter_required
@require_POST
def tns_report_submit(request):
    """Send the details form's report to TNS as the chosen bot. JSON: {'results': url} once it is
    started (whatever TNS then said, the results page shows), or {'error'} (400 or 409) when nothing
    was started."""
    ids = _ids(request.POST.getlist('t'))
    found = {t.pk: t for t in Transient.objects.filter(pk__in=ids).select_related('obs_group', 'host')}
    transients = [found[i] for i in ids if i in found]
    if not transients:
        return JsonResponse({'error': 'no transients were posted'}, status=400)
    if len(transients) > tns_report.MAX_ENTRIES:
        return JsonResponse({'error': 'TNS takes at most %d per report' % tns_report.MAX_ENTRIES}, status=400)
    if settings.TNS_TARGET == 'production' and request.POST.get('confirm') != 'PRODUCTION':
        return JsonResponse({'error': 'type PRODUCTION to send to the production TNS'}, status=400)
    bot = TNSBot.objects.filter(pk=request.POST.get('bot') or None, active=True).first()
    if bot is None:
        return JsonResponse({'error': 'choose a bot to report as'}, status=400)
    if not tns_client.has_key(bot):
        return JsonResponse({'error': 'settings.ini has no %s key for %s' % (settings.TNS_TARGET, bot)}, status=400)
    report = build_report(request.POST, transients)  # rebuilt here: never trust a payload from the page
    if not report['ok']:
        return JsonResponse({'error': 'the report has problems; see the preview'}, status=400)
    entries = [report['payload']['at_report'][str(i)] for i in range(len(transients))]
    try:
        batch = tns_attempts.start(list(zip(transients, entries)), bot, request.user)
    except tns_attempts.Blocked as e:
        return JsonResponse({'error': 'Not sent. %s.' % e}, status=409)
    tns_attempts.send(batch)
    return JsonResponse({'results': reverse('tns_report_results', args=[batch])})


def _batch_attempts(batch):
    attempts = list(TNSReportAttempt.objects.filter(batch=batch).select_related('transient', 'bot', 'created_by')
                    .order_by('id'))
    if not attempts:
        raise Http404('No such TNS submission')
    return attempts


def attempt_state(attempt):
    """(status word, badge colour) for an attempt: what the results page, history and detail pages show."""
    if attempt.unknown:
        return 'unknown', 'danger'
    return {TNSReportAttempt.PENDING: ('pending', 'warning'), TNSReportAttempt.REPORTED: ('reported', 'success'),
            TNSReportAttempt.NAME_DIFFERS: ('name differs', 'danger'), TNSReportAttempt.FAILED: ('failed', 'danger'),
            TNSReportAttempt.ABANDONED: ('abandoned', 'default')}[attempt.status]


@tns_reporter_required
def tns_report_results(request, batch):
    """One submission: each transient's status, the IAU name, TNS's message, and the payload sent."""
    attempts = _batch_attempts(batch)
    first = attempts[0]
    # "report again": a failed or abandoned attempt that is still its transient's latest, with no IAU name
    latest = tns_attempts.latest([a.transient_id for a in attempts])
    retry = [a.transient_id for a in attempts if a.status in (TNSReportAttempt.FAILED, TNSReportAttempt.ABANDONED)
             and latest.get(a.transient_id) == a and not a.transient.iau_name]
    rows = [dict(attempt=a, state=attempt_state(a), payload=json.dumps(json.loads(a.payload), indent=1),
                 stale=a.status == TNSReportAttempt.PENDING and timezone.now() - a.created_date > tns_attempts.STALE_AFTER,
                 retry=a.transient_id in retry)
            for a in attempts]
    checkable = any(a.status == TNSReportAttempt.PENDING and a.report_id for a in attempts)
    return render(request, 'YSE_App/tns_report_results.html', dict(
        _target(), rows=rows, first=first, batch=batch, checkable=checkable, retry=retry,
        sent_to=first.target, gap=int(tns_attempts.CHECK_GAP.total_seconds())))


@tns_reporter_required
@require_POST
def tns_report_check(request, batch):
    """JSON: ask TNS for a submission's outcome (rate-limited per submission), and the statuses after."""
    _batch_attempts(batch)
    state, wait = tns_attempts.check(batch, request.user)
    statuses = {a.pk: attempt_state(a)[0] for a in TNSReportAttempt.objects.filter(batch=batch)}
    return JsonResponse({'state': state, 'wait': wait, 'statuses': statuses,
                         'pending': sum(s in ('pending', 'unknown') for s in statuses.values())})


@tns_reporter_required
def tns_report_history(request):
    """Every submission, newest first, with its counts by status: the way back to a submission's results."""
    batches = {}
    for a in (TNSReportAttempt.objects.select_related('bot', 'created_by').order_by('-created_date', 'id')[:2000]):
        b = batches.setdefault(a.batch, {'batch': a.batch, 'first': a, 'counts': defaultdict(int), 'n': 0})
        b['counts'][attempt_state(a)[0]] += 1
        b['n'] += 1
    rows = [dict(b, counts=sorted(b['counts'].items())) for b in batches.values()]
    return render(request, 'YSE_App/tns_report_history.html', dict(_target(), batches=rows))


@tns_reporter_required
@require_POST
def tns_values_refresh(request):
    """JSON: refresh the TNS values (and link TNS groups to observation groups) as the chosen bot, at
    most once per tns_values.REFRESH_GAP site-wide (amendments 20-21)."""
    bot = TNSBot.objects.filter(pk=request.POST.get('bot') or None, active=True).first()
    if bot is None or not tns_client.has_key(bot):
        return JsonResponse({'error': 'choose a bot with a %s key' % settings.TNS_TARGET}, status=400)
    try:
        summary = tns_values.refresh(bot, request.user)
    except tns_values.TooSoon as e:
        return JsonResponse({'error': str(e), 'wait': e.wait}, status=429)
    except tns_client.TNSError as e:
        return JsonResponse({'error': 'TNS did not answer as expected: %s' % e}, status=502)
    return JsonResponse({'summary': summary, 'text': tns_values.summary_text(summary)})
