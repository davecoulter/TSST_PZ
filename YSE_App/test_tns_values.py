"""#52 stage 3: the TNS values table and its refresh from TNS, with the observation group sync (plan 052
amendments 20-21). TNS is mocked, with replies shaped like the real /api/get/values reply."""
import datetime
import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from . import tns_report, tns_values
from .admin import ObservationGroupForm
from .models import ObservationGroup, TNSBot, TNSValue, TNSValueSync
from .test_tns_report import SHARED, fields
from .test_tns_views import TnsPagesTestBase

SANDBOX = dict(TNS_TARGET='sandbox', TNS_BASE_URL='https://sandbox.example', TNS_API_KEYS={'193638': 'k'})


@override_settings(**SANDBOX)
class ValuesTestBase(TnsPagesTestBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bot = TNSBot.objects.create(tns_id=193638, name='TSST_COSMOS_bot', **cls.audit)

    def setUp(self):
        tns_values.clear()
        self.addCleanup(tns_values.clear)  # the next test reads the rolled-back table, not this one's copy

    def tns(self, **changes):
        """TNS's values as seeded, with `changes` ({kind: {id: label or None to drop}}) applied."""
        data = {}
        for kind, tns_id, text in TNSValue.objects.values_list('kind', 'tns_id', 'label'):
            data.setdefault(kind, {})[tns_id] = text
        for kind, values in changes.items():
            for tns_id, text in values.items():
                if text is None:
                    data[kind].pop(tns_id, None)
                else:
                    data.setdefault(kind, {})[tns_id] = text
        return data

    def refreshed(self, data, gap=None):
        with mock.patch.object(tns_values.tns_client, 'values', return_value=data) as values:
            summary = tns_values.refresh(self.bot, self.admin, gap=gap)
        values.assert_called_once_with(self.bot)
        return summary


class ApplyTests(ValuesTestBase):

    def test_new_values_are_added_renamed_ones_relabelled_dropped_ones_unlisted(self):
        summary = self.refreshed(self.tns(groups={'198': 'TSST_VENUS', '28': 'NUTS2', '157': None}))
        self.assertEqual(summary['added'], {'groups': 1})
        self.assertEqual(summary['relabelled'], {'groups': ['28: NUTS -> NUTS2']})
        self.assertEqual(summary['unlisted'], {'groups': ['157']})
        self.assertEqual(tns_values.find_id('groups', 'TSST_VENUS'), '198')
        self.assertEqual(tns_values.label('groups', 28), 'NUTS2')
        self.assertEqual(tns_values.label('groups', 157), 'TSST_COSMOS')  # kept, never deleted
        self.assertFalse(tns_values.listed('groups', 157))
        self.assertNotIn(('157', 'TSST_COSMOS'), tns_values.choices('groups'))
        self.assertTrue(TNSValueSync.objects.get().ok)
        self.assertGreater(tns_values.as_of(), timezone.now() - datetime.timedelta(minutes=1))

    def test_a_value_tns_lists_again_is_relisted(self):
        self.refreshed(self.tns(groups={'157': None}))
        summary = self.refreshed(self.tns())
        self.assertEqual(summary['relisted'], {'groups': ['157']})
        self.assertTrue(tns_values.listed('groups', 157))

    def test_a_kind_tns_left_out_is_left_alone(self):
        data = self.tns()
        del data['filters']
        summary = self.refreshed(data)
        self.assertNotIn('filters', summary['unlisted'])
        self.assertTrue(tns_values.listed('filters', 100))

    def test_a_report_using_an_unlisted_id_is_flagged(self):
        self.refreshed(self.tns(groups={'170': None}))
        problems = tns_report.problems(tns_report.at_report_entry(fields(), SHARED))
        self.assertEqual(problems['reporting_groupid'], 'TNS no longer lists TSST_COSMOS_3D (170)')

    def test_the_admin_form_offers_listed_groups_only(self):
        self.refreshed(self.tns(groups={'170': None}))
        form = ObservationGroupForm(instance=self.unknown, data={'name': 'x', 'tns_reporting_group_id': '170'})
        self.assertFalse(form.is_valid())

    def test_summary_text(self):
        text = tns_values.summary_text(self.refreshed(self.tns(groups={'198': 'TSST_VENUS'})))
        self.assertTrue(text.startswith('1 values added (1 groups); 0 relabelled; 0 unlisted; observation groups: '), text)


class LinkObsGroupsTests(ValuesTestBase):
    """Amendment 21's decision tree, for each TNS group."""

    def link(self, groups):
        return tns_values.link_obs_groups(groups, self.admin)

    def test_an_obs_group_linked_to_the_id_is_left_alone(self):
        result = self.link({'171': 'TSST renamed on TNS'})  # cls.survey ('TSST') is linked to 171
        self.assertEqual(result, {'created': [], 'linked': [], 'skipped': []})
        self.assertEqual(ObservationGroup.objects.get(tns_reporting_group_id='171').name, 'TSST')  # never renamed

    def test_the_obs_group_with_its_name_is_linked(self):
        ztf = ObservationGroup.objects.create(name=' ztf ', **self.audit)
        self.assertEqual(self.link({'48': 'ZTF'})['linked'], [' ztf  (48)'])
        ztf.refresh_from_db()
        self.assertEqual((ztf.tns_reporting_group_id, ztf.tns_data_source_group_id, ztf.name), ('48', '48', ' ztf '))

    def test_a_group_with_no_obs_group_gets_one(self):
        self.assertEqual(self.link({'198': 'TSST_VENUS'})['created'], ['TSST_VENUS (198)'])
        venus = ObservationGroup.objects.get(name='TSST_VENUS')
        self.assertEqual((venus.tns_reporting_group_id, venus.tns_data_source_group_id, venus.created_by),
                         ('198', '198', self.admin))

    def test_ambiguous_or_otherwise_linked_names_are_skipped(self):
        ObservationGroup.objects.create(name='ATLAS', **self.audit)
        ObservationGroup.objects.create(name='atlas', **self.audit)
        ObservationGroup.objects.create(name='PS1', tns_reporting_group_id='9', **self.audit)
        result = self.link({'10': 'ATLAS', '11': 'PS1'})
        self.assertEqual(result['skipped'], ['ATLAS (10): 2 observation groups have that name',
                                             'PS1 (11): observation group PS1 is linked to TNS group 9'])
        self.assertFalse(ObservationGroup.objects.filter(tns_reporting_group_id__in=['10', '11']).exists())
        text = tns_values.summary_text({'added': {}, 'relabelled': {}, 'unlisted': {}, 'obs_groups': result})
        self.assertIn('2 skipped; skipped: ATLAS (10): 2 observation groups have that name; skipped: PS1 (11)', text)

    def test_a_refresh_links_every_group_and_a_second_changes_nothing(self):
        first = self.refreshed(self.tns(groups={'198': 'TSST_VENUS'}))['obs_groups']
        self.assertIn('TSST_VENUS (198)', first['created'])
        self.assertEqual(ObservationGroup.objects.exclude(tns_reporting_group_id=None).count(),
                         TNSValue.objects.filter(kind='groups').count())
        self.assertEqual(self.refreshed(self.tns())['obs_groups'], {'created': [], 'linked': [], 'skipped': []})


class RefreshTests(ValuesTestBase):

    def test_refreshes_are_spaced_out_failed_ones_included(self):
        with mock.patch.object(tns_values.tns_client, 'values', side_effect=tns_values.tns_client.TNSError('Unauthorized (TNS 401)')):
            with self.assertRaises(tns_values.tns_client.TNSError):
                tns_values.refresh(self.bot, self.admin)
        failed = TNSValueSync.objects.get()
        self.assertEqual((failed.ok, failed.summary), (False, 'Unauthorized (TNS 401)'))
        with mock.patch.object(tns_values.tns_client, 'values') as values:
            with self.assertRaises(tns_values.TooSoon) as caught:
                tns_values.refresh(self.bot, self.admin)
        values.assert_not_called()
        self.assertGreater(caught.exception.wait, 500)
        self.assertEqual(tns_values.as_of().date().isoformat(), '2025-06-18')  # a failed refresh dates nothing

    def test_the_button(self):
        self.login(self.reporter)
        url = reverse('tns_values_refresh')
        with mock.patch.object(tns_values.tns_client, 'values', return_value=self.tns(groups={'198': 'TSST_VENUS'})):
            reply = self.client.post(url, {'bot': self.bot.pk})
            self.assertEqual(reply.status_code, 200, reply.content)
            self.assertIn('1 values added', reply.json()['text'])
            self.assertEqual(self.client.post(url, {'bot': self.bot.pk}).status_code, 429)
        self.assertEqual(self.client.post(url, {'bot': ''}).status_code, 400)
        page = self.client.get(reverse('tns_report_select'))
        self.assertContains(page, 'Refresh from TNS')
        self.assertContains(page, 'TNS values as of %s' % timezone.now().strftime('%Y-%m-%d'))

    def test_only_reporters_refresh(self):
        self.login(self.other)
        self.assertEqual(self.client.post(reverse('tns_values_refresh'), {'bot': self.bot.pk}).status_code, 403)

    def test_the_command(self):
        out = StringIO()
        with mock.patch.object(tns_values.tns_client, 'values', return_value=self.tns(groups={'28': 'NUTS2'})):
            call_command('sync_tns_values', '--bot', 'tsst_cosmos_bot', '--user', 'tns_admin', stdout=out)
            call_command('sync_tns_values', '--bot', '193638', '--user', 'tns_admin', stdout=StringIO())  # no spacing
        self.assertIn('relabelled groups 28: NUTS -> NUTS2', out.getvalue())
        self.assertEqual(TNSValueSync.objects.filter(ok=True).count(), 2)
        self.assertEqual(json.loads(TNSValueSync.objects.first().summary)['relabelled'], {})

    def test_the_cache_is_cleared_by_a_refresh_in_this_process(self):
        self.assertIsNone(tns_values.find_id('groups', 'TSST_VENUS'))  # loads the copy
        self.refreshed(self.tns(groups={'198': 'TSST_VENUS'}))
        self.assertEqual(tns_values.find_id('groups', 'TSST_VENUS'), '198')
