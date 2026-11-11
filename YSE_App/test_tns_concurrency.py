"""#52 stage 3: the lock under real concurrency (plan 052, amendments 1 and 30).

Two reporters submit the same transient at once. Each runs tns_attempts.start in its own thread, so its
own MySQL connection and transaction, with real row locks (nothing about the locking is mocked). The
first is held inside its transaction, after taking the lock, while the second starts: the second must
wait on the row lock, then find the first's pending attempt and be refused.
"""
import threading
import time
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase, override_settings

from . import tns_attempts
from .models import ObservationGroup, TNSBot, TNSReportAttempt, Transient, TransientStatus


@override_settings(TNS_TARGET='sandbox', TNS_BASE_URL='https://sandbox.example', TNS_API_KEYS={})
class ConcurrentSubmitTests(TransactionTestCase):
    # Real transactions: the database is emptied after the test, so restore what migrations put in it
    # (the TNS values, the TNS Reporters group, ...) for the tests that follow.
    serialized_rollback = True

    def setUp(self):
        self.user = User.objects.create_user('racer', password='pw')
        audit = dict(created_by=self.user, modified_by=self.user)
        status = TransientStatus.objects.get_or_create(name='Candidate', defaults=audit)[0]
        group = ObservationGroup.objects.create(name='race group', **audit)
        self.transient = Transient.objects.create(name='cand_race', ra=150.0, dec=2.0, status=status, obs_group=group, **audit)
        self.bot = TNSBot.objects.create(tns_id=193638, name='TSST_COSMOS_bot', **audit)

    def test_two_submissions_at_once_report_the_transient_once(self):
        first_has_lock, release_first = threading.Event(), threading.Event()
        outcomes = {}
        real_blocking = tns_attempts.blocking

        def blocking(ids):
            # called inside start's transaction, after the transients' rows are locked
            if threading.current_thread().name == 'first':
                first_has_lock.set()
                release_first.wait(10)
            return real_blocking(ids)

        def submit():
            name = threading.current_thread().name
            try:
                transient = Transient.objects.get(pk=self.transient.pk)
                outcomes[name] = tns_attempts.start([(transient, {'internal_name': transient.name})], self.bot, self.user)
            except tns_attempts.Blocked as e:
                outcomes[name] = e
            finally:
                connection.close()  # each thread has its own connection

        with mock.patch.object(tns_attempts, 'blocking', side_effect=blocking):
            first = threading.Thread(target=submit, name='first')
            second = threading.Thread(target=submit, name='second')
            first.start()
            self.assertTrue(first_has_lock.wait(10))
            second.start()
            time.sleep(1)  # the second is now waiting on the row lock the first holds
            self.assertNotIn('second', outcomes)
            release_first.set()
            first.join(30)
            second.join(30)

        self.assertNotIsInstance(outcomes['first'], Exception)
        self.assertIsInstance(outcomes['second'], tns_attempts.Blocked)
        self.assertIn('in flight: cand_race', str(outcomes['second']))
        self.assertEqual(TNSReportAttempt.objects.filter(transient=self.transient).count(), 1)
