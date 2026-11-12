"""#52 stage 3: the TNS client, with requests.post mocked (no TNS is called)."""
import json
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings
from urllib3.exceptions import MaxRetryError, NewConnectionError

from . import tns_client
from .models import TNSBot

KEY = 'sandbox-key-not-real'
BOT = TNSBot(tns_id=193638, name='TSST_COSMOS_bot')
CONFIGURED = dict(TNS_TARGET='sandbox', TNS_BASE_URL='https://sandbox.example/', TNS_API_KEYS={'193638': KEY})


def response(status=200, body=None, headers=None, reason='OK'):
    r = mock.Mock(status_code=status, headers=headers or {}, reason=reason)
    r.json = mock.Mock(return_value=body) if body is not None else mock.Mock(side_effect=ValueError('not JSON'))
    return r


@override_settings(**CONFIGURED)
class TnsClientTests(SimpleTestCase):

    def post(self, reply):
        return mock.patch.object(tns_client.requests, 'post', return_value=reply)

    def test_a_request_names_the_bot_and_carries_the_key(self):
        with self.post(response(body={'id_code': 200, 'data': {'groups': {'170': 'TSST_COSMOS_3D'}}})) as post:
            self.assertEqual(tns_client.values(BOT), {'groups': {'170': 'TSST_COSMOS_3D'}})
        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertEqual(url, 'https://sandbox.example/api/get/values')
        self.assertEqual(kwargs['data'], {'api_key': KEY})
        marker = kwargs['headers']['User-Agent']
        self.assertTrue(marker.startswith('tns_marker'))
        self.assertEqual(json.loads(marker[len('tns_marker'):]), {'tns_id': 193638, 'type': 'bot', 'name': 'TSST_COSMOS_bot'})
        self.assertEqual(kwargs['timeout'], tns_client.TIMEOUT)

    def test_submit_sends_the_report_as_json_and_returns_the_report_id(self):
        data = {'at_report': {'0': {'internal_name': 'cand_1'}}}
        with self.post(response(body={'id_code': 200, 'data': {'report_id': 12345}})) as post:
            report_id, body = tns_client.submit(BOT, data)
        self.assertEqual(report_id, '12345')
        self.assertEqual(json.loads(post.call_args.kwargs['data']['data']), data)
        self.assertTrue(post.call_args.args[0].endswith('/api/set/bulk-report'))

    def test_a_submission_without_a_report_id_is_an_error(self):
        with self.post(response(body={'id_code': 200, 'data': {}})):
            with self.assertRaises(tns_client.TNSError):
                tns_client.submit(BOT, {'at_report': {}})

    def test_a_reply_that_is_not_ready(self):
        with self.post(response(404, {'id_code': 404, 'id_message': 'No reply yet'}, reason='Not Found')):
            with self.assertRaises(tns_client.NotReady):
                tns_client.reply(BOT, '12345')

    def test_a_404_elsewhere_is_an_error_not_a_wait(self):
        with self.post(response(404, None, reason='Not Found')):
            with self.assertRaises(tns_client.TNSError) as caught:
                tns_client.values(BOT)
        self.assertNotIsInstance(caught.exception, tns_client.NotReady)

    def test_the_rate_limit(self):
        with self.post(response(429, {'id_code': 429, 'id_message': 'Too many requests'},
                                headers={'x-rate-limit-reset': '42'})):
            with self.assertRaises(tns_client.RateLimited) as caught:
                tns_client.reply(BOT, '12345')
        self.assertEqual(caught.exception.retry_after, 42)

    def test_tns_messages_are_kept(self):
        body = {'id_code': 403, 'id_message': 'Forbidden: bot not in group'}
        with self.post(response(403, body, reason='Forbidden')):
            with self.assertRaises(tns_client.TNSError) as caught:
                tns_client.submit(BOT, {'at_report': {}})
        self.assertEqual(str(caught.exception), 'Forbidden: bot not in group (TNS 403)')
        self.assertEqual((caught.exception.status, caught.exception.response), (403, body))

    def test_a_non_json_error(self):
        with self.post(response(500, None, reason='Internal Server Error')):
            with self.assertRaises(tns_client.TNSError) as caught:
                tns_client.values(BOT)
        self.assertEqual(str(caught.exception), 'HTTP 500 Internal Server Error')
        self.assertIsInstance(caught.exception, tns_client.NoAnswer)

    def raised(self, error):
        with mock.patch.object(tns_client.requests, 'post', side_effect=error):
            with self.assertRaises(tns_client.TNSError) as caught:
                tns_client.submit(BOT, {'at_report': {}})
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        return caught.exception

    def test_never_sent_when_no_connection_was_made(self):
        """Amendment 29: a refused or unresolvable connection, or a connect timeout, sent nothing."""
        refused = requests.ConnectionError(MaxRetryError(None, '/', reason=NewConnectionError(None, 'refused')))
        for error in (refused, requests.ConnectTimeout('connect timeout')):
            self.assertIsInstance(self.raised(error), tns_client.NotSent, error)
        self.assertIn('could not reach TNS', str(self.raised(refused)))

    def test_no_answer_when_tns_may_have_it(self):
        """A read timeout or a dropped connection may follow the send: whether TNS has it is unknown."""
        for error in (requests.ReadTimeout('read timeout'), requests.ConnectionError('Connection aborted ' + KEY)):
            caught = self.raised(error)
            self.assertIsInstance(caught, tns_client.NoAnswer, error)
            self.assertIn('no answer from TNS', str(caught))

    def test_a_tns_server_error_is_no_answer(self):
        with self.post(response(500, None, reason='Internal Server Error')):
            with self.assertRaises(tns_client.NoAnswer):
                tns_client.submit(BOT, {'at_report': {}})

    def test_a_refusal_is_neither(self):
        with self.post(response(400, {'id_code': 400, 'id_message': 'Bad request'}, reason='Bad Request')):
            with self.assertRaises(tns_client.TNSError) as caught:
                tns_client.submit(BOT, {'at_report': {}})
        self.assertNotIsInstance(caught.exception, (tns_client.NotSent, tns_client.NoAnswer))

    def test_the_key_is_never_logged(self):
        with self.post(response(body={'id_code': 200, 'data': {}})), self.assertLogs('YSE_App.tns_client', 'INFO') as logs:
            tns_client.values(BOT)
        self.assertNotIn(KEY, '\n'.join(logs.output))

    def test_has_key(self):
        self.assertTrue(tns_client.has_key(BOT))
        self.assertFalse(tns_client.has_key(TNSBot(tns_id=1, name='other_bot')))


class TnsClientNotConfiguredTests(SimpleTestCase):

    @override_settings(TNS_TARGET='sandbox', TNS_BASE_URL='', TNS_API_KEYS={})
    def test_no_section(self):
        with mock.patch.object(tns_client.requests, 'post') as post:
            with self.assertRaisesMessage(tns_client.NotConfigured, 'settings.ini [tns_sandbox] has no base_url'):
                tns_client.values(BOT)
        post.assert_not_called()

    @override_settings(TNS_TARGET='production', TNS_BASE_URL='https://www.example/', TNS_API_KEYS={'1': 'x'})
    def test_no_key_for_this_bot(self):
        with mock.patch.object(tns_client.requests, 'post') as post:
            with self.assertRaisesMessage(tns_client.NotConfigured,
                                          'settings.ini [tns_production] has no key for TSST_COSMOS_bot (193638)'):
                tns_client.values(BOT)
        post.assert_not_called()
