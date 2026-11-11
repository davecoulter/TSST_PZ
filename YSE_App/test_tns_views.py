"""#52 stage 2: the TNS report pages (select, details, preview), their permission, the ObservationGroup
TNS fields. Nothing is sent to TNS."""
import datetime
import json
import math

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from . import tns_report, tns_views
from .admin import ObservationGroupForm
from .models import (Instrument, Observatory, ObservationGroup, PhotometricBand, TagKind, Telescope, Transient,
                     TransientPhotData, TransientPhotometry, TransientStatus, TransientTag)
from .serializers.enum_serializers import ObservationGroupSerializer

UTC = datetime.timezone.utc
ZP = 23.9


class TnsPagesTestBase(TestCase):

	@classmethod
	def setUpTestData(cls):
		cls.reporter = User.objects.create_user('tns_reporter', password='pw')
		cls.reporter.groups.add(Group.objects.get(name=tns_views.TNS_REPORTERS))  # made by migration 0011
		cls.other = User.objects.create_user('not_a_reporter', password='pw')
		cls.admin = User.objects.create_superuser('tns_admin', password='pw')
		cls.audit = dict(created_by=cls.admin, modified_by=cls.admin)
		cls.candidate = TransientStatus.objects.get_or_create(name='Candidate', defaults=cls.audit)[0]
		cls.survey = ObservationGroup.objects.create(
			name='TSST', tns_reporting_group_id='171', tns_data_source_group_id='171',
			**cls.audit)
		cls.unknown = ObservationGroup.objects.create(name='Unknown survey', **cls.audit)
		observatory = Observatory.objects.create(name='JWST', utc_offset=0, tz_name='UTC', **cls.audit)
		telescope = Telescope.objects.create(name='JWST', observatory=observatory, latitude=0.0, longitude=0.0,
		                                     elevation=0.0, **cls.audit)
		cls.nircam = Instrument.objects.create(name='NIRCam', telescope=telescope, **cls.audit)
		cls.bands = {b: PhotometricBand.objects.create(name=b, instrument=cls.nircam, **cls.audit)
		             for b in ('F150W', 'F200W', 'F356W')}

	def make(self, name, group=None, **fields):
		t = Transient.objects.create(name=name, ra=150.18, dec=2.44, status=self.candidate,
		                             obs_group=group or self.survey, **dict(self.audit, **fields))
		t.photometry_header = TransientPhotometry.objects.create(transient=t, instrument=self.nircam,
		                                                         obs_group=t.obs_group, **self.audit)
		return t

	def point(self, t, band, day, flux, flux_err=0.01):
		return TransientPhotData.objects.create(
			photometry=t.photometry_header, band=self.bands[band],
			obs_date=datetime.datetime(2026, 1, 1, tzinfo=UTC) + datetime.timedelta(days=day),
			flux=flux, flux_err=flux_err, flux_zero_point=ZP, mag=ZP - 2.5 * math.log10(flux),
			mag_err=2.5 * math.log10(1 + flux_err / flux), **self.audit)

	def login(self, user):
		self.client.force_login(user)

	def report_form(self, for_transient, first_point, **row):
		"""A complete details form for one transient, sending first_point as its discovery; `row` overrides
		its values (the parameter names keep clear of the form's own, e.g. 'discovery')."""
		data = {'t': [for_transient.pk], 'reporting_groupid': '171', 'data_source_groupid': '171',
		        'reporter': 'A. Reporter', 'at_type': '1', 'flux_unitid': '1', 'archiveid': '0',
		        'archival_remarks': 'Not in the reference.'}
		values = {'discovery': first_point.pk, 'phot': [first_point.pk], 'host_name': '', 'host_redshift': '',
		          'host_redshift_source': tns_report.HOST_PHOTO_Z, 'remarks': ''}
		values.update(row)
		data.update({'r%d-%s' % (for_transient.pk, k): v for k, v in values.items()})
		return data


class TnsPermissionTests(TnsPagesTestBase):
	"""Only the TNS Reporters group; everyone else, superusers included, gets 403 (amendment 19)."""

	def setUp(self):
		self.t = self.make('cand_perm')
		self.urls = [reverse('tns_report_select'), reverse('tns_report_details') + '?t=%d' % self.t.pk]

	def test_anonymous_is_sent_to_login(self):
		for url in self.urls:
			self.assertEqual(self.client.get(url).status_code, 302, url)
		self.assertEqual(self.client.post(reverse('tns_report_preview'), {'t': self.t.pk}).status_code, 302)

	def test_users_and_superusers_outside_the_group_get_403(self):
		for user in (self.other, self.admin):
			self.login(user)
			for url in self.urls:
				self.assertEqual(self.client.get(url).status_code, 403, (user, url))
			self.assertEqual(self.client.post(reverse('tns_report_preview'), {'t': self.t.pk}).status_code, 403)

	def test_reporters_get_in_superuser_or_not(self):
		self.admin.groups.add(Group.objects.get(name=tns_views.TNS_REPORTERS))
		for user in (self.reporter, self.admin):
			self.login(user)
			for url in self.urls:
				self.assertEqual(self.client.get(url).status_code, 200, (user, url))
			self.assertEqual(self.client.post(reverse('tns_report_preview'), {'t': self.t.pk}).status_code, 200)

	def test_preview_takes_post_only(self):
		self.login(self.reporter)
		self.assertEqual(self.client.get(reverse('tns_report_preview')).status_code, 405)

	def test_is_tns_reporter(self):
		self.assertTrue(tns_views.is_tns_reporter(self.reporter))
		self.assertFalse(tns_views.is_tns_reporter(self.admin))
		self.assertFalse(tns_views.is_tns_reporter(self.other))


class TnsNavTests(TnsPagesTestBase):

	def test_the_nav_entry_shows_for_reporters_only(self):
		link = 'href="%s"' % reverse('tns_report_select')
		for user, shown in ((self.reporter, True), (self.admin, False), (self.other, False)):
			self.login(user)
			response = self.client.get(reverse('candidate_dashboard'))
			self.assertEqual(response.status_code, 200)
			(self.assertContains if shown else self.assertNotContains)(response, link)


class TnsSelectTests(TnsPagesTestBase):

	def test_lists_transients_without_an_iau_name_by_observation_group(self):
		a = self.make('cand_a')
		b = self.make('cand_b', group=self.unknown)
		self.make('cand_named', iau_name='2026abc')
		self.login(self.reporter)
		response = self.client.get(reverse('tns_report_select'))
		groups = {g['group'].name: [r['transient'].name for r in g['rows']] for g in response.context['groups']}
		self.assertEqual(groups, {'TSST': [a.name], 'Unknown survey': [b.name]})
		self.assertContains(response, 'SANDBOX TNS')
		self.assertContains(response, 'no TNS values set for this observation group')  # the Unknown survey box

	def test_filters_by_candidate_tag(self):
		kind = TagKind.objects.create(name='Candidate', **self.audit)
		tag = TransientTag.objects.create(name='Promising', kind=kind, **self.audit)
		tagged = self.make('cand_tagged')
		tagged.tags.add(tag)
		self.make('cand_untagged')
		self.login(self.reporter)
		response = self.client.get(reverse('tns_report_select'), {'tag': 'promising'})
		self.assertEqual([r['transient'].name for g in response.context['groups'] for r in g['rows']], ['cand_tagged'])


class TnsInitialValuesTests(TnsPagesTestBase):

	def test_one_survey_fills_the_batch(self):
		batch, overrides = tns_views.initial_values([self.make('a'), self.make('b')])
		self.assertEqual((batch['reporting_groupid'], batch['data_source_groupid']), ('171', '171'))
		# per report, not per obs group: the reporter types them
		self.assertEqual((batch['reporter'], batch['archival_remarks']), ('', ''))
		self.assertEqual(overrides, [{'reporting_groupid': '', 'data_source_groupid': ''}] * 2)

	def test_mixed_surveys_leave_the_batch_empty_and_fill_the_rows(self):
		batch, overrides = tns_views.initial_values([self.make('a'), self.make('b', group=self.unknown)])
		self.assertEqual(batch['reporting_groupid'], '')
		self.assertEqual(overrides[0], {'reporting_groupid': '171', 'data_source_groupid': '171'})
		self.assertEqual(overrides[1]['reporting_groupid'], '')  # nothing known: the batch value applies
		self.assertEqual((batch['at_type'], batch['flux_unitid'], batch['archiveid']), ('1', '1', '0'))


class TnsDetailsTests(TnsPagesTestBase):

	def test_rows_preselect_the_discovery_point(self):
		t = self.make('cand_d')
		self.point(t, 'F200W', 10, 0.06)
		strongest = self.point(t, 'F356W', 10.1, 0.12)
		self.login(self.reporter)
		response = self.client.get(reverse('tns_report_details'), {'t': t.pk})
		(row,) = response.context['rows']
		self.assertEqual([d['id'] for d in row['detections'] if d['picked']], [strongest.pk])
		self.assertEqual(row['discovery_date'], '2026-01-11')
		self.assertEqual(row['discovery_id'], strongest.pk)
		self.assertEqual([round(d['mjd'], 2) for d in row['detections']], [61051.0, 61051.1])  # 2026-01-11 is MJD 61051
		self.assertContains(response, 'F356W-JWST')

	def test_named_or_unknown_ids_are_dropped_and_none_left_goes_back(self):
		named = self.make('cand_named', iau_name='2026abd')
		self.login(self.reporter)
		response = self.client.get(reverse('tns_report_details'), {'t': [named.pk, 999999, 'x']})
		self.assertRedirects(response, reverse('tns_report_select'))


class TnsPreviewTests(TnsPagesTestBase):

	def setUp(self):
		self.t = self.make('cand_p')
		self.f200 = self.point(self.t, 'F200W', 10, 0.06)
		self.f356 = self.point(self.t, 'F356W', 10.1, 0.12)
		self.login(self.reporter)

	def form(self, **row):
		return self.report_form(self.t, self.f356, **row)

	def preview(self, **row):
		response = self.client.post(reverse('tns_report_preview'), self.form(**row))
		self.assertEqual(response.status_code, 200)
		return response.json()

	def test_a_complete_form_is_ready_and_matches_the_builder(self):
		data = self.preview(host_redshift='1.2468', remarks='Seen in two bands.')
		self.assertTrue(data['ok'])
		self.assertEqual(data['target'], 'sandbox')
		entry = data['payload']['at_report']['0']
		self.assertEqual(entry['internal_name'], 'cand_p')
		self.assertEqual(entry['internal_ids'], {'tsst_id': str(self.t.pk)})
		self.assertEqual(entry['discovery_datetime'], '2026-01-11')
		self.assertEqual(entry['host_redshift'], '1.25')  # a photo-z: 2 decimals
		self.assertEqual(entry['remarks'], 'Seen in two bands.')
		self.assertEqual(entry['photometry']['0']['filterid'], '105')  # F356W-JWST
		self.assertEqual(entry['non_detection'], {'archiveid': '0', 'archival_remarks': 'Not in the reference.'})
		rows = {path: label for path, value, label in data['entries'][0]['rows']}
		self.assertEqual(rows['reporting_groupid'], 'TSST')
		self.assertEqual(rows['photometry.0.instrumentid'], 'JWST - NIRCam')

	def test_the_discovery_point_is_sent_first(self):
		entry = self.preview(phot=[self.f200.pk, self.f356.pk])['payload']['at_report']['0']
		self.assertEqual([p['filterid'] for p in entry['photometry'].values()], ['105', '100'])

	def test_row_values_override_the_batch(self):
		entry = self.preview(reporting_groupid='170', archival_remarks='Not in COSMOS-Web.')['payload']['at_report']['0']
		self.assertEqual((entry['reporting_groupid'], entry['data_source_groupid']), ('170', '171'))
		self.assertEqual(entry['non_detection']['archival_remarks'], 'Not in COSMOS-Web.')

	def test_the_reporter_is_for_the_whole_batch(self):
		entry = self.preview(reporter='B. Other')['payload']['at_report']['0']
		self.assertEqual(entry['reporter'], 'A. Reporter')

	def test_a_point_can_take_another_filter_and_instrument(self):
		key = 'p%d-' % self.f356.pk
		entry = self.preview(**{key + 'filterid': '100', key + 'instrumentid': '186', key + 'comments': 'ignored'})
		point = entry['payload']['at_report']['0']['photometry']['0']
		self.assertEqual((point['filterid'], point['instrumentid']), ('100', '186'))
		self.assertNotIn('comments', point)  # a comment goes only with filter Other

	def test_measurements_can_be_edited(self):
		"""Amendment 26: the MJD, magnitude and error are editable; the discovery date follows the MJD."""
		key = 'p%d-' % self.f356.pk
		entry = self.preview(**{key + 'mjd': '61049.5', key + 'mag': '26.123', key + 'mag_err': ''})['payload']['at_report']['0']
		self.assertEqual(entry['discovery_datetime'], '2026-01-09')  # MJD 61049 is 2026-01-09
		point = entry['photometry']['0']
		self.assertEqual((point['obsdate'], point['flux']), ('2026-01-09', '26.12'))
		self.assertNotIn('flux_error', point)

	def test_unreadable_measurements_are_flagged_and_ours_kept(self):
		key = 'p%d-' % self.f356.pk
		data = self.preview(**{key + 'mjd': 'soon', key + 'mag': 'bright', key + 'mag_err': '?'})
		problems = data['entries'][0]['problems']
		self.assertEqual((problems['photometry.0.obsdate'], problems['photometry.0.flux'], problems['photometry.0.flux_error']),
		                 ('an MJD', 'a magnitude', 'a number, or empty'))
		self.assertEqual(data['payload']['at_report']['0']['discovery_datetime'], '2026-01-11')

	def test_an_emptied_magnitude_is_required(self):
		data = self.preview(**{'p%d-mag' % self.f356.pk: ''})
		self.assertEqual(data['entries'][0]['problems']['photometry.0.flux'], 'required')

	def test_filter_other_needs_a_comment(self):
		key = 'p%d-' % self.f356.pk
		data = self.preview(**{key + 'filterid': '0', key + 'comments': ' '})
		self.assertEqual(data['entries'][0]['problems']['photometry.0.comments'], 'name the filter: it is sent as "Other"')
		point = self.preview(**{key + 'filterid': '0', key + 'comments': 'Filter is JWST-NIRCam-F356W.'})['payload']['at_report']['0']['photometry']['0']
		self.assertEqual((point['filterid'], point['comments']), ('0', 'Filter is JWST-NIRCam-F356W.'))

	def test_details_prefill_the_redshift_as_sent(self):
		self.t.redshift = 1.88999998569
		self.t.save()
		response = self.client.get(reverse('tns_report_details'), {'t': self.t.pk})
		self.assertEqual(response.context['rows'][0]['host_redshift'], '1.8900')  # a spec-z: 4 decimals
		self.assertContains(response, 'value="1.8900"')

	def test_problems_are_reported_per_transient(self):
		data = self.preview(discovery='', phot=[], host_redshift='-1', remarks='x' * 513)
		self.assertFalse(data['ok'])
		problems = data['entries'][0]['problems']
		self.assertEqual(problems['discovery_datetime'], 'pick the discovery point')
		self.assertIn('photometry', problems)
		self.assertEqual(problems['host_redshift'], 'above 0, or empty')
		self.assertEqual(problems['remarks'], 'at most 512 characters')

	def test_the_discovery_date_is_the_discovery_points(self):
		entry = self.preview(discovery=self.f200.pk, phot=[self.f200.pk, self.f356.pk])['payload']['at_report']['0']
		self.assertEqual(entry['discovery_datetime'], '2026-01-11')
		self.assertEqual([p['filterid'] for p in entry['photometry'].values()], ['100', '105'])  # F200W first

	def test_the_discovery_point_is_sent_even_when_its_box_is_unticked(self):
		entry = self.preview(discovery=self.f200.pk, phot=[self.f356.pk])['payload']['at_report']['0']
		self.assertEqual([p['filterid'] for p in entry['photometry'].values()], ['100', '105'])

	def test_a_discovery_point_of_another_transient_is_refused(self):
		other = self.make('cand_other')
		foreign = self.point(other, 'F200W', 3, 0.2)
		data = self.preview(discovery=foreign.pk)
		self.assertEqual(data['entries'][0]['problems']['discovery_datetime'],
		                 'the discovery point is not a current detection of this transient')
		self.assertEqual(data['payload']['at_report']['0']['discovery_datetime'], '')

	def test_an_observed_non_detection_from_the_batch(self):
		form = self.form()
		form.update(non_detection=tns_report.ND_OBSERVATION, nd_obsdate='2025-12-30', nd_limiting_flux='28.456',
		            nd_filterid='100', nd_instrumentid='185')
		data = self.client.post(reverse('tns_report_preview'), form).json()
		self.assertTrue(data['ok'], data['entries'][0]['problems'])
		self.assertEqual(data['payload']['at_report']['0']['non_detection'], {
			'obsdate': '2025-12-30', 'limiting_flux': '28.46', 'flux_unitid': '1', 'filterid': '100', 'instrumentid': '185'})

	def test_a_row_can_switch_to_an_observed_non_detection(self):
		data = self.preview(non_detection=tns_report.ND_OBSERVATION, nd_obsdate='2026-01-11', nd_limiting_flux='deep')
		problems = data['entries'][0]['problems']
		self.assertEqual(problems['non_detection.obsdate'], 'must be before the discovery date (2026-01-11)')
		self.assertEqual(problems['non_detection.limiting_flux'], 'a number: the limiting magnitude')
		self.assertEqual(problems['non_detection.filterid'], 'required')
		self.assertNotIn('archiveid', data['payload']['at_report']['0']['non_detection'])

	def test_an_observed_non_detection_date_must_be_a_date(self):
		data = self.preview(non_detection=tns_report.ND_OBSERVATION, nd_obsdate='30/12/2025')
		self.assertEqual(data['entries'][0]['problems']['non_detection.obsdate'], 'a date, YYYY-MM-DD')

	def test_a_row_can_override_the_archive(self):
		entry = self.preview(archiveid='1')['payload']['at_report']['0']
		self.assertEqual(entry['non_detection'], {'archiveid': '1', 'archival_remarks': 'Not in the reference.'})

	def test_a_point_of_another_transient_is_refused(self):
		other = self.make('cand_other')
		foreign = self.point(other, 'F200W', 3, 0.2)
		data = self.preview(phot=[self.f356.pk, foreign.pk])
		self.assertIn('not current detections', data['entries'][0]['problems']['photometry'])
		self.assertEqual(len(data['payload']['at_report']['0']['photometry']), 1)

	def test_an_empty_batch_value_is_flagged(self):
		form = self.form()
		form['reporting_groupid'] = ''
		data = self.client.post(reverse('tns_report_preview'), form).json()
		self.assertEqual(data['entries'][0]['problems']['reporting_groupid'], 'required')

	def test_no_transients_is_a_400(self):
		response = self.client.post(reverse('tns_report_preview'), {'t': ['999999']})
		self.assertEqual(response.status_code, 400)

	@override_settings(TNS_TARGET='production')
	def test_production_banner(self):
		response = self.client.get(reverse('tns_report_details'), {'t': self.t.pk})
		self.assertContains(response, 'PRODUCTION TNS')
		self.assertNotContains(response, 'SANDBOX TNS')


class ObservationGroupTnsFieldTests(TnsPagesTestBase):

	def test_admin_form_offers_tns_groups_and_stores_empty_as_null(self):
		form = ObservationGroupForm(instance=self.unknown, data={
			'name': 'Unknown survey', 'tns_reporting_group_id': '170', 'tns_data_source_group_id': ''})
		self.assertIn(('170', 'TSST_COSMOS_3D (170)'), form.fields['tns_reporting_group_id'].choices)
		self.assertTrue(form.is_valid(), form.errors)
		group = form.save()
		self.assertEqual((group.tns_reporting_group_id, group.tns_data_source_group_id), ('170', None))

	def test_admin_form_refuses_an_id_tns_does_not_list(self):
		form = ObservationGroupForm(instance=self.unknown, data={'name': 'x', 'tns_reporting_group_id': '999999'})
		self.assertFalse(form.is_valid())

	def test_api_shows_the_tns_fields_read_only(self):
		fields = ObservationGroupSerializer().fields
		for name in ('tns_reporting_group_id', 'tns_data_source_group_id'):
			self.assertTrue(fields[name].read_only, name)
		self.assertFalse(fields['name'].read_only)

	def test_unknown_group_id_in_a_payload_is_flagged(self):
		self.login(self.reporter)
		t = self.make('cand_u')
		p = self.point(t, 'F200W', 10, 0.1)
		form = {'t': [t.pk], 'reporting_groupid': '999999', 'data_source_groupid': '171', 'reporter': 'A',
		        'at_type': '1', 'flux_unitid': '1', 'archiveid': '0', 'archival_remarks': 'r',
		        'r%d-discovery' % t.pk: p.pk, 'r%d-phot' % t.pk: [p.pk]}
		data = json.loads(self.client.post(reverse('tns_report_preview'), form).content)
		self.assertEqual(data['entries'][0]['problems']['reporting_groupid'], 'not a TNS id (999999)')
