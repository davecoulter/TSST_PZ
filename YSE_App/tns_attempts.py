"""TNS report attempts (#52, plan 052 amendments 1-4 and 29): submitting, checking, writing back.

The state lives in TNSReportAttempt rows, so it survives a crash or a closed tab:

1. `start` locks the transients' rows, re-checks that none has an IAU name or a pending attempt, and
   saves one pending attempt per transient, with the payload entry to send. Two reporters submitting at
   once: the second waits for the first's locks, then finds the transients pending and is refused.
2. `send` calls TNS outside any transaction (no lock is held while waiting on the network) and saves
   TNS's report id the moment it comes. A refusal marks the batch failed; no answer leaves it unknown
   (pending with no report id), since TNS may have the report.
3. `check` asks TNS for the outcome, at most once per CHECK_GAP per batch (longer when TNS says it is
   rate limited), and `parse_reply` + `_resolve` turn each transient's feedback into its status,
   writing the IAU name back.
"""
import datetime
import json
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import tns_client, tns_report
from .candidate_ingest import CANDIDATE, find_by_name
from .models import TNSReportAttempt, Transient, TransientStatus

Attempt = TNSReportAttempt
CHECK_GAP = datetime.timedelta(seconds=10)
STALE_AFTER = datetime.timedelta(days=1)
INSERTED, EXISTS = '100', '101'  # TNS feedback codes (TNS bulk report manual, section 7)
# A candidate reported to TNS becomes a transient: its status goes from Candidate to this (Dave, 2026-11-11).
# Untagged, it then shows in the main dashboard's Needs review grid (#40).
REPORTED_STATUS = 'New'


class Blocked(Exception):
    """Some transients cannot be reported now: they have an IAU name or a pending attempt."""


def blocking(transient_ids):
    """{transient id: its pending attempt} (pending includes unknown): these cannot be reported again yet."""
    return {a.transient_id: a for a in Attempt.objects.filter(transient_id__in=list(transient_ids), status=Attempt.PENDING)}


def in_flight(transient):
    """Whether a TNS report of this transient is pending (or unknown). While it is, its IAU name cannot be
    changed by hand, in the admin or through the API (amendment 2): the write-back decides it."""
    return transient is not None and transient.pk is not None and Attempt.objects.filter(
        transient_id=transient.pk, status=Attempt.PENDING).exists()


def latest(transient_ids):
    """{transient id: its latest attempt}, for the select grid's badges."""
    found = {}
    for a in Attempt.objects.filter(transient_id__in=list(transient_ids)).order_by('-created_date', '-id'):
        found.setdefault(a.transient_id, a)
    return found


def start(pairs, bot, user):
    """[(transient, at_report entry)] -> the new batch id. Locks the transients' rows and re-checks them
    in one transaction; raises Blocked naming the ones that cannot be reported."""
    ids = [t.pk for t, _ in pairs]
    with transaction.atomic():
        locked = {t.pk: t for t in Transient.objects.select_for_update().filter(pk__in=ids)}
        named = sorted(t.name for t in locked.values() if t.iau_name)
        pending = sorted(Transient.objects.filter(pk__in=list(blocking(ids))).values_list('name', flat=True))
        gone = [str(i) for i in ids if i not in locked]
        if named or pending or gone:
            raise Blocked('; '.join(part for part in (
                'already have an IAU name: %s' % ', '.join(named) if named else '',
                'have a TNS report in flight: %s' % ', '.join(pending) if pending else '',
                'no longer exist: %s' % ', '.join(gone) if gone else '') if part))
        batch = uuid.uuid4()
        for transient, entry in pairs:
            Attempt.objects.create(transient=transient, bot=bot, batch=batch, target=settings.TNS_TARGET,
                                   base_url=settings.TNS_BASE_URL, payload=json.dumps(entry), created_by=user,
                                   modified_by=user)
    return batch


def send(batch):
    """Send a started batch to TNS as its bot. Saves the report id, or marks the batch failed (TNS
    refused, or the request never left) or leaves it unknown (no answer: TNS may have it)."""
    attempts = list(Attempt.objects.filter(batch=batch).select_related('bot').order_by('id'))
    data = tns_report.bulk_report([json.loads(a.payload) for a in attempts])
    ids = [a.pk for a in attempts]
    try:
        report_id, body = tns_client.submit(attempts[0].bot, data)
    except tns_client.NoAnswer as e:
        Attempt.objects.filter(pk__in=ids).update(
            message='No answer from TNS (%s): it may or may not have the report. Look for it on TNS before '
                    'a superuser marks this abandoned.' % e, response=_dump(e.response), modified_date=timezone.now())
    except tns_client.TNSError as e:
        Attempt.objects.filter(pk__in=ids).update(status=Attempt.FAILED, message=str(e), response=_dump(e.response),
                                                  modified_date=timezone.now())
    else:
        Attempt.objects.filter(pk__in=ids).update(report_id=report_id, response=_dump(body),
                                                  check_after=timezone.now() + datetime.timedelta(seconds=5),
                                                  modified_date=timezone.now())


def _dump(body):
    return json.dumps(body) if body is not None else ''


def check(batch, user):
    """Ask TNS for the outcome of a batch's pending attempts. Returns (state, seconds until the next
    check is allowed): state is 'resolved', 'not ready', 'too soon', 'rate limited', 'error: ...' or
    'nothing to check'."""
    now = timezone.now()
    with transaction.atomic():  # one check at a time per batch: a second click waits here, then is too soon
        pending = list(Attempt.objects.select_for_update().filter(batch=batch, status=Attempt.PENDING)
                       .exclude(report_id='').select_related('bot').order_by('id'))
        if not pending:
            return 'nothing to check', 0
        after = max((a.check_after for a in pending if a.check_after), default=None)
        if after and after > now:
            return 'too soon', (after - now).total_seconds()
        Attempt.objects.filter(pk__in=[a.pk for a in pending]).update(last_checked=now, check_after=now + CHECK_GAP)

    try:
        body = tns_client.reply(pending[0].bot, pending[0].report_id)
    except tns_client.NotReady:
        return 'not ready', CHECK_GAP.total_seconds()
    except tns_client.RateLimited as e:
        Attempt.objects.filter(pk__in=[a.pk for a in pending]).update(check_after=now + datetime.timedelta(seconds=e.retry_after))
        return 'rate limited', e.retry_after
    except tns_client.TNSError as e:
        Attempt.objects.filter(pk__in=[a.pk for a in pending]).update(message='Checking failed: %s' % e)
        return 'error: %s' % e, CHECK_GAP.total_seconds()

    every = list(Attempt.objects.filter(batch=batch).order_by('id'))  # the reply follows the submission's order
    outcomes = parse_reply(body, every)
    for attempt in pending:
        _resolve(attempt.pk, outcomes.get(attempt.pk), body, user)
    return 'resolved', 0


# --- TNS's reply ------------------------------------------------------------

def _codes(value):
    """Every (code, details) in a feedback entry: TNS keys its messages by numeric code ('100': {...}),
    nested under the field they are about."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).isdigit() and isinstance(inner, dict):
                yield str(key), inner
            yield from _codes(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _codes(inner)


def _entries(body):
    """The reply's per-entry feedback, in submission order."""
    feedback = ((body.get('data') or {}).get('feedback') or {}).get('at_report')
    if isinstance(feedback, dict):
        return [feedback[k] for k in sorted(feedback, key=lambda k: int(k) if str(k).isdigit() else 0)]
    return list(feedback or [])


def _find(value, key):
    """The first value under `key` anywhere in a nested reply, else None."""
    if isinstance(value, dict):
        if isinstance(value.get(key), (str, int)):
            return value[key]
        value = list(value.values())
    if isinstance(value, list):
        for inner in value:
            found = _find(inner, key)
            if found is not None:
                return found
    return None


def _iau(objname):
    """'2026abc' from TNS's objname, without an 'AT'/'SN' prefix should there be one (we store none)."""
    return re.sub(r'^(AT|SN)\s*', '', (objname or '').strip())


def parse_reply(body, attempts):
    """{attempt id: {'code', 'iau_name', 'separation', 'message'}} from TNS's bulk report reply. An
    entry is matched by the `internal_ids.tsst_id` we sent when TNS echoes it, else by its position.
    code is '100' (inserted), '101' (exists: matched an object TNS has) or None (refused)."""
    by_transient = {a.transient_id: a for a in attempts}
    outcomes = {}
    for i, entry in enumerate(_entries(body)):
        echoed = str(_find(entry, 'tsst_id') or '')
        attempt = by_transient.get(int(echoed)) if echoed.isdigit() else None
        if attempt is None and i < len(attempts):
            attempt = attempts[i]
        if attempt is None:
            continue
        codes = dict(_codes(entry))
        hit = next((c for c in (INSERTED, EXISTS) if codes.get(c, {}).get('objname')), None)
        messages = [d.get('message') for c, d in _codes(entry) if d.get('message')]
        outcomes[attempt.pk] = {
            'code': hit,
            'iau_name': _iau(codes[hit]['objname']) if hit else '',
            'separation': _float(codes[hit].get('separation') if hit else None),
            'message': '; '.join(dict.fromkeys(messages)) or ('' if hit else 'TNS refused it, without a message'),
        }
    return outcomes


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve(attempt_id, outcome, body, user):
    """Apply one transient's feedback. A name is written back only where we hold none; a different
    name we hold, or one another transient already has, makes it name_differs, for a person to resolve."""
    with transaction.atomic():
        attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
        if attempt.status != Attempt.PENDING:
            return  # abandoned meanwhile
        attempt.response, attempt.modified_by = json.dumps(body), user
        if outcome is None:
            attempt.message = "TNS's reply has no feedback for this transient; check it on TNS."
            attempt.save()
            return
        attempt.message = outcome['message']
        if not outcome['code']:
            attempt.status = Attempt.FAILED
            attempt.save()
            return
        attempt.iau_name, attempt.objname_separation = outcome['iau_name'], outcome['separation']
        transient = Transient.objects.select_for_update().get(pk=attempt.transient_id)
        holder = Transient.objects.filter(iau_name=outcome['iau_name']).exclude(pk=transient.pk).first()
        if transient.iau_name == outcome['iau_name'] or (not transient.iau_name and holder is None):
            attempt.status = Attempt.REPORTED
            changed = transient.iau_name != outcome['iau_name']
            transient.iau_name = outcome['iau_name']  # into an empty name only: this moves the slug (#29)
            changed = _promote(transient) or changed
            if changed:
                transient.modified_by = user
                transient.save()
        elif transient.iau_name:
            attempt.status = Attempt.NAME_DIFFERS
            attempt.message = 'TNS says %s; we hold %s. %s' % (outcome['iau_name'], transient.iau_name, attempt.message)
        else:
            attempt.status = Attempt.NAME_DIFFERS
            attempt.message = 'TNS says %s, which %s already has. %s' % (outcome['iau_name'], holder.name, attempt.message)
        attempt.save()


def _promote(transient):
    """A reported candidate becomes a transient: status Candidate -> REPORTED_STATUS. True if it changed."""
    if transient.status is None or (transient.status.name or '').strip().lower() != CANDIDATE.lower():
        return False
    status = find_by_name(TransientStatus, REPORTED_STATUS)
    if status is None:
        return False
    transient.status = status
    return True


def abandon(attempts, user):
    """Mark pending (or unknown) attempts abandoned, so their transients can be reported again."""
    return Attempt.objects.filter(pk__in=[a.pk for a in attempts], status=Attempt.PENDING).update(
        status=Attempt.ABANDONED, modified_by=user, modified_date=timezone.now())
