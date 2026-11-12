"""TNS 2.0 API client (#52): the calls the TNS report pages make, each as one TNS bot.

- `values(bot)`: POST /api/get/values, TNS's enumerations ({table: {id: label}}).
- `submit(bot, data)`: POST /api/set/bulk-report, one bulk AT report; returns TNS's report id.
- `reply(bot, report_id)`: POST /api/get/bulk-report-reply, the outcome of a report. Raises NotReady
  while TNS is still working on it (it answers 404 until then).

Every request is a form POST with two fields, `api_key` and the call's own (`data`, `report_id`), and a
`User-Agent: tns_marker{"tns_id": ..., "type": "bot", "name": ...}` header naming the bot.

Where to: settings.TNS_BASE_URL, and the key is settings.TNS_API_KEYS[<bot's TNS id>]. Both come from
this deployment's [tns_sandbox] or [tns_production] section of settings.ini (plan 052, amendment 28),
so the integration tests' fake TNS server is just another base_url. The key is sent, never stored,
logged, raised or returned (amendment 4).
"""
import json
import logging

import requests
from django.conf import settings
from urllib3.exceptions import NewConnectionError
from django.views.decorators.debug import sensitive_variables

logger = logging.getLogger(__name__)

TIMEOUT = 30  # seconds, per request
VALUES = '/api/get/values'
SUBMIT = '/api/set/bulk-report'
REPLY = '/api/get/bulk-report-reply'


class TNSError(Exception):
    """A call that did not succeed. As raised, a plain TNSError means TNS answered and refused (HTTP
    4xx, or a 200 without what was asked for); the subclasses say when it did not answer. `status` is
    the HTTP status (None when TNS was not reached); `response` is TNS's JSON reply, when there was
    one, to be stored with the attempt."""

    def __init__(self, message, status=None, response=None):
        super().__init__(message)
        self.status = status
        self.response = response


class NotSent(TNSError):
    """The request certainly did not reach TNS (no connection could be made): safe to call it failed."""


class NoAnswer(TNSError):
    """TNS may have received the request but gave no usable answer (a timeout or dropped connection
    after sending, or a TNS server error). For a submission, whether TNS has the report is unknown."""


class NotConfigured(NotSent):
    """settings.ini has no base_url, or no key for this bot, for this deployment's TNS."""


class NotReady(TNSError):
    """TNS has not finished processing the report yet: ask again later."""


class RateLimited(TNSError):
    """TNS's rate limit is used up; `retry_after` is how many seconds until it resets."""

    def __init__(self, message, retry_after, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


def _section():
    return '[tns_%s]' % settings.TNS_TARGET


def has_key(bot):
    """Whether settings.ini has an API key for this bot, for this deployment's TNS."""
    return bool(settings.TNS_API_KEYS.get(str(bot.tns_id)))


def user_agent(bot):
    """The header TNS identifies bots by; the id is a number, as on the bot's TNS page."""
    return 'tns_marker' + json.dumps({'tns_id': int(bot.tns_id), 'type': 'bot', 'name': bot.name})


def _json(response):
    try:
        return response.json()
    except ValueError:
        return None


def _message(body, response):
    """TNS's own message (its JSON replies carry id_code and id_message), else the HTTP status."""
    if isinstance(body, dict) and body.get('id_message'):
        return '%s (TNS %s)' % (body['id_message'], body.get('id_code', response.status_code))
    return 'HTTP %d %s' % (response.status_code, response.reason or '')


@sensitive_variables('key', 'form')
def _post(bot, path, fields):
    """TNS's JSON reply to one call, or a TNSError. NotReady for a reply that is not ready (404)."""
    if not settings.TNS_BASE_URL:
        raise NotConfigured('settings.ini %s has no base_url' % _section())
    key = settings.TNS_API_KEYS.get(str(bot.tns_id))
    if not key:
        raise NotConfigured('settings.ini %s has no key for %s' % (_section(), bot))
    form = dict(fields, api_key=key)
    url = settings.TNS_BASE_URL.rstrip('/') + path
    try:
        response = requests.post(url, data=form, headers={'User-Agent': user_agent(bot)}, timeout=TIMEOUT)
    except requests.RequestException as e:
        if _never_connected(e):
            raise NotSent('could not reach TNS at %s: %s' % (settings.TNS_BASE_URL, type(e).__name__)) from None
        raise NoAnswer('no answer from TNS at %s: %s' % (settings.TNS_BASE_URL, type(e).__name__)) from None
    body = _json(response)
    logger.info('TNS %s as %s: HTTP %d', path, bot, response.status_code)  # never the form: it holds the key

    if response.status_code == 429:
        reset = response.headers.get('x-rate-limit-reset', '')
        raise RateLimited('TNS rate limit reached; it resets in %s s' % (reset or '?'),
                          retry_after=int(reset) if reset.isdigit() else 60, status=429, response=body)
    if response.status_code == 404 and path == REPLY:
        raise NotReady('TNS has not processed the report yet', status=404, response=body)
    if response.status_code >= 500:
        raise NoAnswer(_message(body, response), status=response.status_code, response=body)
    if response.status_code != 200 or not isinstance(body, dict):
        raise TNSError(_message(body, response), status=response.status_code, response=body)
    return body


def _never_connected(error):
    """Whether a requests error happened before anything was sent: a connect timeout, or a refused or
    unresolvable connection. Anything else (a read timeout, a dropped connection) may follow a send."""
    if isinstance(error, requests.ConnectTimeout):
        return True
    reason = getattr(error.args[0], 'reason', None) if error.args else None
    return isinstance(error, requests.ConnectionError) and isinstance(reason, NewConnectionError)


def values(bot):
    """TNS's enumerations: {table: {id: label}} (groups, at_types, filters, instruments, ...)."""
    return _post(bot, VALUES, {}).get('data') or {}


def submit(bot, data):
    """Send one bulk report (`data` as tns_report.bulk_report builds it). Returns (report_id, TNS's
    reply). The outcome comes later, from `reply`."""
    body = _post(bot, SUBMIT, {'data': json.dumps(data)})
    report_id = (body.get('data') or {}).get('report_id')
    if not report_id:
        raise TNSError('TNS accepted the report but returned no report id', status=200, response=body)
    return str(report_id), body


def reply(bot, report_id):
    """TNS's reply for a report, as it sent it (NotReady until there is one). A report TNS processed and
    refused comes back as HTTP 400 with the per-entry feedback in its body (sandbox, 2026-11-12): that
    is the outcome, so it is returned like a 200; a 400 without feedback is still an error."""
    try:
        return _post(bot, REPLY, {'report_id': str(report_id)})
    except TNSError as e:
        if e.status == 400 and isinstance(e.response, dict) and ((e.response.get('data') or {}).get('feedback')):
            return e.response
        raise
