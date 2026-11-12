"""#52 stage 3: submitting to TNS, checking, writing back (tns_attempts and its pages). The TNS client is
mocked: nothing here reaches TNS. The reply shapes are TNS's documented codes (100 inserted, 101 exists);
the real sandbox reply is checked by hand (plan 052, amendment 29)."""
import datetime
import json
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from . import tns_attempts, tns_client
from .models import TNSBot, TNSReportAttempt, Transient, TransientStatus
from .serializers.transient_serializers import TransientSerializer
from .test_tns_views import TnsPagesTestBase

Attempt = TNSReportAttempt
SANDBOX = dict(TNS_TARGET='sandbox', TNS_BASE_URL='https://sandbox.example', TNS_API_KEYS={'193638': 'k'})


def reply(*entries):
    return {'id_code': 200, 'id_message': 'OK', 'data': {'feedback': {'at_report': list(entries)}}}


def inserted(name, tsst_id=None):
    entry = {'100': {'objname': name, 'message': 'Transient object was inserted.'}}
    if tsst_id is not None:
        entry['internal_ids'] = {'tsst_id': str(tsst_id)}
    return entry


@override_settings(**SANDBOX)
class AttemptsTestBase(TnsPagesTestBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bot = TNSBot.objects.create(tns_id=193638, name='TSST_COSMOS_bot', **cls.audit)
        cls.keyless = TNSBot.objects.create(tns_id=1, name='other_bot', **cls.audit)
        cls.new = TransientStatus.objects.get_or_create(name='New', defaults=cls.audit)[0]

    def setUp(self):
        self.t = self.make('cand_a')
        self.p = self.point(self.t, 'F356W', 10, 0.12)

    def started(self, *transients):
        return tns_attempts.start([(t, {'internal_name': t.name}) for t in transients or (self.t,)], self.bot, self.reporter)

    def submit_ok(self, report_id='42'):
        return mock.patch.object(tns_attempts.tns_client, 'submit', return_value=(report_id, {'id_code': 200, 'data': {'report_id': report_id}}))

    def sent(self, *transients):
        batch = self.started(*transients)
        with self.submit_ok():
            tns_attempts.send(batch)
        Attempt.objects.filter(batch=batch).update(check_after=None)
        return batch

    def check(self, batch, body=None, error=None):
        with mock.patch.object(tns_attempts.tns_client, 'reply', return_value=body, side_effect=error) as called:
            state = tns_attempts.check(batch, self.reporter)
        return state, called


class StartTests(AttemptsTestBase):

    def test_start_saves_one_pending_attempt_per_transient_with_its_payload(self):
        other = self.make('cand_b')
        batch = self.started(self.t, other)
        attempts = list(Attempt.objects.filter(batch=batch).order_by('id'))
        self.assertEqual([(a.transient, a.status, a.report_id, json.loads(a.payload)) for a in attempts],
                         [(self.t, 'pending', '', {'internal_name': 'cand_a'}), (other, 'pending', '', {'internal_name': 'cand_b'})])
        self.assertEqual((attempts[0].target, attempts[0].base_url, attempts[0].bot), ('sandbox', 'https://sandbox.example', self.bot))
        self.assertTrue(attempts[0].unknown)  # no report id yet

    def test_a_named_or_in_flight_transient_blocks_the_whole_submission(self):
        named = self.make('cand_named', iau_name='2026aaa')
        with self.assertRaisesMessage(tns_attempts.Blocked, 'already have an IAU name: cand_named'):
            self.started(self.t, named)
        self.started(self.t)
        with self.assertRaisesMessage(tns_attempts.Blocked, 'have a TNS report in flight: cand_a'):
            self.started(self.t)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_failed_and_abandoned_attempts_do_not_block(self):
        Attempt.objects.filter(batch=self.started()).update(status=Attempt.FAILED)
        Attempt.objects.filter(batch=self.started()).update(status=Attempt.ABANDONED)
        self.started()
        self.assertEqual(Attempt.objects.filter(status=Attempt.PENDING).count(), 1)


class SendTests(AttemptsTestBase):

    def test_tns_accepts_and_the_report_id_is_saved(self):
        batch = self.started()
        with self.submit_ok('777') as submit:
            tns_attempts.send(batch)
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual((attempt.status, attempt.report_id, attempt.unknown), ('pending', '777', False))
        bot, data = submit.call_args.args
        self.assertEqual((bot, data), (self.bot, {'at_report': {'0': {'internal_name': 'cand_a'}}}))

    def test_a_refusal_or_a_request_that_never_left_is_failed(self):
        for error in (tns_client.TNSError('Forbidden (TNS 403)', status=403, response={'id_code': 403}),
                      tns_client.NotSent('could not reach TNS'), tns_client.RateLimited('limit', retry_after=60)):
            batch = self.started()
            with mock.patch.object(tns_attempts.tns_client, 'submit', side_effect=error):
                tns_attempts.send(batch)
            attempt = Attempt.objects.get(batch=batch)
            self.assertEqual((attempt.status, attempt.message), ('failed', str(error)))

    def test_no_answer_leaves_it_unknown(self):
        batch = self.started()
        with mock.patch.object(tns_attempts.tns_client, 'submit', side_effect=tns_client.NoAnswer('read timeout')):
            tns_attempts.send(batch)
        attempt = Attempt.objects.get(batch=batch)
        self.assertTrue(attempt.unknown)
        self.assertIn('may or may not have the report', attempt.message)
        with self.assertRaises(tns_attempts.Blocked):  # still blocks a new report
            self.started()


class CheckTests(AttemptsTestBase):

    def test_reported_writes_the_iau_name_back(self):
        batch = self.sent()
        state, called = self.check(batch, reply(inserted('2026xyz', self.t.pk)))
        self.assertEqual(state[0], 'resolved')
        called.assert_called_once_with(self.bot, '42')
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual((attempt.status, attempt.iau_name, attempt.message), ('reported', '2026xyz', 'Transient object was inserted.'))
        t = Transient.objects.get(pk=self.t.pk)
        self.assertEqual((t.iau_name, t.slug, t.modified_by), ('2026xyz', '2026xyz', self.reporter))
        self.assertEqual(t.status, self.new)  # a reported candidate becomes a transient

    def test_a_reported_transient_that_is_not_a_candidate_keeps_its_status(self):
        watch = TransientStatus.objects.get_or_create(name='Watch', defaults=self.audit)[0]
        Transient.objects.filter(pk=self.t.pk).update(status=watch)
        self.check(self.sent(), reply(inserted('2026xyw')))
        self.assertEqual(Transient.objects.get(pk=self.t.pk).status, watch)

    def test_an_existing_object_is_reported_with_its_separation(self):
        batch = self.sent()
        self.check(batch, reply({'101': {'objname': 'AT 2025abc', 'message': 'Transient object exists', 'separation': '0.43'}}))
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual((attempt.status, attempt.iau_name, attempt.objname_separation), ('reported', '2025abc', 0.43))
        self.assertEqual(Transient.objects.get(pk=self.t.pk).iau_name, '2025abc')

    def test_a_refused_entry_is_failed_with_tns_messages(self):
        batch = self.sent()
        self.check(batch, reply({'non_detection': {'1': {'message': 'Last non-detection should precede the discovery'}}}))
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual((attempt.status, attempt.message), ('failed', 'non_detection: Last non-detection should precede the discovery'))
        self.assertIsNone(Transient.objects.get(pk=self.t.pk).iau_name)

    def test_a_refused_report_as_tns_sends_it_is_failed_with_the_field_and_a_hint(self):
        """TNS's real answer for a bot reporting for a group it is not in (sandbox report 297429): HTTP 400,
        the feedback in the body, the error as a list under the field. The client returns it as the outcome."""
        body = {'id_code': 400, 'id_message': 'Bad request', 'data': {'feedback': {'at_report': [{
            'reporting_groupid': [{'error_id': 0, 'message': 'Invalid. DebugNum-134'}],
            'internal_ids': {'tsst_id': str(self.t.pk)}}]}}}
        batch = self.sent()
        error = tns_client.TNSError('Bad request (TNS 400)', status=400, response=body)
        with mock.patch.object(tns_client, '_post', side_effect=error):
            state = tns_attempts.check(batch, self.reporter)
        self.assertEqual(state[0], 'resolved')
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual((attempt.status, attempt.message),
                         ('failed', 'reporting_groupid: Invalid. DebugNum-134 (is the bot a member of this group?)'))
        self.assertIsNone(Transient.objects.get(pk=self.t.pk).iau_name)

    def test_a_400_without_feedback_stays_an_error_and_pending(self):
        batch = self.sent()
        error = tns_client.TNSError('Bad request (TNS 400)', status=400, response={'id_code': 400, 'id_message': 'Bad request'})
        with mock.patch.object(tns_client, '_post', side_effect=error):
            state = tns_attempts.check(batch, self.reporter)
        self.assertEqual(state[0], 'error: Bad request (TNS 400)')
        self.assertEqual(Attempt.objects.get(batch=batch).status, 'pending')

    def test_a_name_we_hold_is_never_overwritten(self):
        batch = self.sent()
        Transient.objects.filter(pk=self.t.pk).update(iau_name='2026mine')
        self.check(batch, reply(inserted('2026xyz')))
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual(attempt.status, 'name_differs')
        self.assertIn('TNS says 2026xyz; we hold 2026mine', attempt.message)
        t = Transient.objects.get(pk=self.t.pk)
        self.assertEqual((t.iau_name, t.status), ('2026mine', self.candidate))  # left for a person to resolve

    def test_a_name_another_transient_has_is_not_taken(self):
        self.make('cand_holder', iau_name='2026xyz')
        batch = self.sent()
        self.check(batch, reply(inserted('2026xyz')))
        attempt = Attempt.objects.get(batch=batch)
        self.assertEqual(attempt.status, 'name_differs')
        self.assertIn('which cand_holder already has', attempt.message)

    def test_entries_are_matched_by_the_echoed_tsst_id_else_by_position(self):
        other = self.make('cand_b')
        batch = self.sent(self.t, other)
        self.check(batch, reply(inserted('2026bbb', other.pk), inserted('2026aaa', self.t.pk)))
        names = dict(Attempt.objects.filter(batch=batch).values_list('transient__name', 'iau_name'))
        self.assertEqual(names, {'cand_a': '2026aaa', 'cand_b': '2026bbb'})

    def test_a_reply_keyed_by_position_as_a_dict(self):
        batch = self.sent()
        body = {'id_code': 200, 'data': {'feedback': {'at_report': {'0': inserted('2026ddd')}}}}
        self.check(batch, body)
        self.assertEqual(Attempt.objects.get(batch=batch).iau_name, '2026ddd')

    def test_not_ready_leaves_it_pending(self):
        batch = self.sent()
        state, _ = self.check(batch, error=tns_client.NotReady('not yet'))
        self.assertEqual(state[0], 'not ready')
        self.assertEqual(Attempt.objects.get(batch=batch).status, 'pending')

    def test_checks_are_spaced_out(self):
        batch = self.sent()
        self.check(batch, error=tns_client.NotReady('not yet'))
        state, called = self.check(batch, error=tns_client.NotReady('not yet'))
        self.assertEqual(state[0], 'too soon')
        self.assertGreater(state[1], 0)
        called.assert_not_called()

    def test_a_rate_limit_pushes_the_next_check_back(self):
        batch = self.sent()
        state, _ = self.check(batch, error=tns_client.RateLimited('limit', retry_after=45))
        self.assertEqual(state, ('rate limited', 45))
        wait = Attempt.objects.get(batch=batch).check_after - timezone.now()
        self.assertGreater(wait, datetime.timedelta(seconds=40))

    def test_an_unknown_submission_has_nothing_to_check(self):
        batch = self.started()
        state, called = self.check(batch, reply(inserted('2026eee')))
        self.assertEqual(state[0], 'nothing to check')
        called.assert_not_called()

    def test_an_abandoned_attempt_is_left_alone(self):
        batch = self.sent()
        self.assertEqual(tns_attempts.abandon(list(Attempt.objects.filter(batch=batch)), self.admin), 1)
        self.check(batch, reply(inserted('2026fff')))
        self.assertEqual(Attempt.objects.get(batch=batch).status, 'abandoned')
        self.assertIsNone(Transient.objects.get(pk=self.t.pk).iau_name)


class GuardTests(AttemptsTestBase):
    """Amendment 2: no hand edit of the IAU name while a report is in flight."""

    def test_the_api_refuses_an_iau_name_change_while_in_flight(self):
        self.sent()
        serializer = TransientSerializer(instance=self.t, data={'iau_name': '2026hand'}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn('in flight', str(serializer.errors['iau_name']))
        Attempt.objects.update(status=Attempt.FAILED)
        self.assertTrue(TransientSerializer(instance=self.t, data={'iau_name': '2026hand'}, partial=True).is_valid())

    def test_the_admin_shows_it_read_only_while_in_flight(self):
        self.sent()
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin:YSE_App_transient_change', args=[self.t.pk]))
        self.assertNotContains(response, 'name="iau_name"')
        self.assertContains(response, 'a TNS report of this transient is in flight')


class SubmitViewTests(AttemptsTestBase):

    def submit(self, **extra):
        data = dict(self.report_form(self.t, self.p), bot=self.bot.pk)
        data.update(extra)
        self.login(self.reporter)
        return self.client.post(reverse('tns_report_submit'), data)

    def test_submit_starts_sends_and_goes_to_the_results(self):
        with self.submit_ok('99') as submit:
            response = self.submit()
        self.assertEqual(response.status_code, 200, response.content)
        attempt = Attempt.objects.get()
        self.assertEqual(response.json()['results'], reverse('tns_report_results', args=[attempt.batch]))
        self.assertEqual((attempt.report_id, attempt.created_by), ('99', self.reporter))
        sent = submit.call_args.args[1]['at_report']['0']
        self.assertEqual((sent['internal_name'], sent['reporting_groupid']), ('cand_a', '171'))
        self.assertEqual(json.loads(attempt.payload), sent)

    def test_nothing_is_sent_without_a_bot_with_a_key_or_with_problems(self):
        with mock.patch.object(tns_attempts.tns_client, 'submit') as submit:
            for extra, message in (({'bot': ''}, 'choose a bot'), ({'bot': self.keyless.pk}, 'has no sandbox key'),
                                   ({'reporter': ''}, 'the report has problems')):
                response = self.submit(**extra)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()['error'])
        submit.assert_not_called()
        self.assertFalse(Attempt.objects.exists())

    def test_an_in_flight_transient_is_refused(self):
        self.started()
        with mock.patch.object(tns_attempts.tns_client, 'submit') as submit:
            response = self.submit()
        self.assertEqual(response.status_code, 409)
        self.assertIn('in flight: cand_a', response.json()['error'])
        submit.assert_not_called()

    @override_settings(TNS_TARGET='production', TNS_BASE_URL='https://www.example', TNS_API_KEYS={'193638': 'k'})
    def test_production_needs_production_typed(self):
        with self.submit_ok():
            self.assertEqual(self.submit(confirm='production').status_code, 400)
            self.assertEqual(self.submit(confirm='PRODUCTION').status_code, 200)

    def test_only_reporters_submit(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('tns_report_submit'), {}).status_code, 403)


class PagesTests(AttemptsTestBase):

    def test_results_page_and_check(self):
        batch = self.sent()
        self.login(self.reporter)
        page = self.client.get(reverse('tns_report_results', args=[batch]))
        self.assertContains(page, 'TSST_COSMOS_bot')
        self.assertContains(page, 'Check again')
        with mock.patch.object(tns_attempts.tns_client, 'reply', return_value=reply(inserted('2026ggg'))):
            data = self.client.post(reverse('tns_report_check', args=[batch])).json()
        self.assertEqual((data['state'], data['pending']), ('resolved', 0))
        page = self.client.get(reverse('tns_report_results', args=[batch]))
        self.assertContains(page, '2026ggg')
        self.assertNotContains(page, 'Check again')

    def test_a_failed_attempt_offers_report_again_until_it_is_reported_again(self):
        batch = self.sent()
        Attempt.objects.filter(batch=batch).update(status=Attempt.FAILED, message='reporting_groupid: Invalid.')
        self.login(self.reporter)
        page = self.client.get(reverse('tns_report_results', args=[batch]))
        self.assertEqual(page.context['retry'], [self.t.pk])
        self.assertContains(page, 'Report the 1 failed again')
        self.assertContains(page, '%s?t=%d' % (reverse('tns_report_details'), self.t.pk))
        self.sent()  # reported again: the old submission no longer offers it
        self.assertEqual(self.client.get(reverse('tns_report_results', args=[batch])).context['retry'], [])

    def test_an_unknown_submission_says_what_to_do(self):
        batch = self.started()
        self.login(self.reporter)
        self.assertContains(self.client.get(reverse('tns_report_results', args=[batch])), 'may or may not have the report')

    def test_history_lists_submissions(self):
        batch = self.sent()
        self.login(self.reporter)
        page = self.client.get(reverse('tns_report_history'))
        self.assertContains(page, reverse('tns_report_results', args=[batch]))
        self.assertContains(page, '1 pending')

    def test_the_select_grid_badges_and_locks_an_in_flight_transient(self):
        self.sent()
        self.login(self.reporter)
        page = self.client.get(reverse('tns_report_select'))
        (row,) = [r for g in page.context['groups'] for r in g['rows'] if r['transient'] == self.t]
        self.assertTrue(row['blocked'])
        self.assertContains(page, 'title="A TNS report of it is in flight"')
        self.assertContains(page, '>pending</a>')


class DetailPagesTests(AttemptsTestBase):
    """Stage 4: the latest report as a badge by the title, and every report in a box, for TNS reporters."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for name in ('Following', 'Watch', 'Interesting', 'Ignore'):  # the legacy transient page needs them
            TransientStatus.objects.get_or_create(name=name, defaults=cls.audit)

    def pages(self):
        return [reverse('transient_detail', args=[self.t.slug]), reverse('candidate_detail', args=[self.t.slug])]

    def test_reporters_see_the_badge_and_every_report(self):
        failed = self.sent()
        Attempt.objects.filter(batch=failed).update(status=Attempt.FAILED, message='Forbidden: bot not in group')
        self.sent()
        self.login(self.reporter)
        for url in self.pages():
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            self.assertContains(page, '>pending</a>')  # the latest, by the title
            self.assertContains(page, 'TNS reports <span class="badge">2</span>')
            self.assertContains(page, 'Forbidden: bot not in group')
            self.assertContains(page, reverse('tns_report_results', args=[failed]))

    def test_a_failed_latest_report_says_retry(self):
        Attempt.objects.filter(batch=self.sent()).update(status=Attempt.FAILED)
        self.login(self.reporter)
        self.assertContains(self.client.get(self.pages()[0]), 'failed: retry')

    def test_others_and_unreported_transients_show_nothing(self):
        box = 'TNS reports <span class="badge">'  # not the nav's "TNS reports" link, which reporters always have
        self.login(self.reporter)
        for url in self.pages():
            self.assertNotContains(self.client.get(url), box)
        self.sent()
        self.login(self.admin)  # a superuser outside the TNS Reporters group
        for url in self.pages():
            page = self.client.get(url)
            self.assertNotContains(page, box)
            self.assertNotContains(page, '>pending</a>')
