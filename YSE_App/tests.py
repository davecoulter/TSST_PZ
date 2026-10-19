import importlib
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import forms
from .models import (AlternateTransientNames, ClassicalResource, FollowupStatus, Instrument, Observatory,
                     ObservationGroup, SurveyField, Telescope, Transient, TransientStatus)
from .table_utils import TransientTable
from .transient_names import find_transient, name_q


class TransientNameTests(TestCase):
	"""#29: the internal name plus a nullable IAU name, and the slug that follows it."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user('iau_tester', password='pw', is_staff=True)
		audit = dict(created_by=cls.user, modified_by=cls.user)
		cls.status = TransientStatus.objects.create(name='New', **audit)
		cls.group = ObservationGroup.objects.create(name='TSST', **audit)

	def make(self, name, **fields):
		return Transient.objects.create(name=name, ra=10.0, dec=-5.0, status=self.status, obs_group=self.group,
		                                created_by=self.user, modified_by=self.user, **fields)

	def rename(self, transient, iau_name):
		"""Set the IAU name on a freshly loaded copy, as the API and the admin do."""
		t = Transient.objects.get(pk=transient.pk)
		t.iau_name = iau_name
		t.save()
		return Transient.objects.get(pk=transient.pk)

	# --- the model ---

	def test_without_iau_name_the_internal_name_leads(self):
		t = self.make('jwst_1_a')
		self.assertIsNone(t.iau_name)
		self.assertEqual(t.slug, 'jwst_1_a')
		self.assertEqual(t.display_name, 'jwst_1_a')

	def test_setting_iau_name_moves_slug_and_keeps_old_slug_as_alias(self):
		t = self.rename(self.make('jwst_1_a'), '2026abc')
		self.assertEqual(t.slug, '2026abc')
		self.assertEqual(t.display_name, '2026abc')
		self.assertEqual(t.name, 'jwst_1_a')  # the internal name is untouched
		alias = AlternateTransientNames.objects.get(transient=t)
		self.assertEqual((alias.name, alias.slug), ('jwst_1_a', 'jwst_1_a'))

	def test_resaving_does_not_add_aliases(self):
		t = self.rename(self.make('jwst_1_a'), '2026abc')
		t.redshift = 0.1
		t.save()
		self.assertEqual(Transient.objects.get(pk=t.pk).slug, '2026abc')
		self.assertEqual(AlternateTransientNames.objects.filter(transient=t).count(), 1)

	def test_changing_iau_name_on_an_unloaded_instance_still_moves_slug(self):
		t = self.make('jwst_1_a')  # created in this process, not loaded from the DB
		t.iau_name = '2026abc'
		t.save()
		self.assertEqual(Transient.objects.get(pk=t.pk).slug, '2026abc')

	def test_clearing_iau_name_returns_to_internal_slug(self):
		t = self.rename(self.rename(self.make('jwst_1_a'), '2026abc'), None)
		self.assertEqual(t.slug, 'jwst_1_a')
		self.assertTrue(AlternateTransientNames.objects.filter(transient=t, slug='2026abc').exists())

	def test_created_with_iau_name_uses_it_for_slug(self):
		self.assertEqual(self.make('jwst_1_a', iau_name='2026abc').slug, '2026abc')

	def test_blank_iau_name_is_stored_as_null(self):
		a = self.make('jwst_1_a', iau_name='  ')
		b = self.make('jwst_1_b', iau_name='')  # would break the unique index if stored as ''
		self.assertIsNone(Transient.objects.get(pk=a.pk).iau_name)
		self.assertIsNone(Transient.objects.get(pk=b.pk).iau_name)

	# --- finding a transient ---

	def test_find_transient_by_slug_alias_or_either_name(self):
		t = self.rename(self.make('jwst_1_a'), '2026abc')
		for text in ('2026abc', 'jwst_1_a', 'JWST_1_A', 'AT 2026abc', 'SN2026abc', '2026ABC'):
			self.assertEqual(find_transient(text), t, text)
		self.assertIsNone(find_transient('nothing_here'))

	def test_search_matches_either_name(self):
		t = self.rename(self.make('jwst_1_a'), '2026abc')
		self.make('jwst_2_b')
		self.assertEqual(list(Transient.objects.filter(name_q('6ab'))), [t])
		self.assertEqual(list(Transient.objects.filter(name_q('1_a'))), [t])

	# --- pages ---

	def test_old_url_redirects_to_current_slug(self):
		self.rename(self.make('jwst_1_a'), '2026abc')
		self.client.force_login(self.user)
		response = self.client.get(reverse('transient_detail', kwargs={'slug': 'jwst_1_a'}))
		self.assertRedirects(response, reverse('transient_detail', kwargs={'slug': '2026abc'}),
		                     fetch_redirect_response=False)
		response = self.client.get(reverse('candidate_detail', kwargs={'slug': 'jwst_1_a'}))
		self.assertRedirects(response, reverse('candidate_detail', kwargs={'slug': '2026abc'}),
		                     fetch_redirect_response=False)

	def test_unknown_transient_is_a_friendly_404(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse('transient_detail', kwargs={'slug': '2026zzz'}))
		self.assertEqual(response.status_code, 404)
		self.assertContains(response, 'wis-tns.org/search?name=2026zzz', status_code=404)
		response = self.client.get(reverse('candidate_detail', kwargs={'slug': 'jwst_9_z'}))
		self.assertContains(response, 'wis-tns.org/search?internal_name=jwst_9_z', status_code=404)

	def test_name_column_sorts_by_display_name(self):
		renamed = self.rename(self.make('zzz_internal'), '2026aaa')
		plain = self.make('aaa_internal')
		table = TransientTable(Transient.objects.all(), order_by=('name_string',))
		self.assertEqual([row.record for row in table.rows], [renamed, plain])  # '2026aaa' < 'aaa_internal'


class FormsDoNotQueryAtImportTests(TestCase):
	"""#22: form defaults that need a query are computed per form instance, never when the module is imported."""

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user('forms_tester', password='pw')
		cls.audit = dict(created_by=cls.user, modified_by=cls.user)
		observatory = Observatory.objects.create(name='Obs', utc_offset=0, tz_name='UTC', **cls.audit)
		cls.telescope = Telescope.objects.create(name='Tel', observatory=observatory, latitude=0.0,
												 longitude=0.0, elevation=0.0, **cls.audit)

	def test_importing_the_forms_makes_no_queries(self):
		with CaptureQueriesContext(connection) as queries:
			importlib.reload(forms)
		self.assertEqual(len(queries), 0, [q['sql'] for q in queries])

	# --- TransientFollowupForm ---

	def test_followup_status_defaults_to_requested_without_a_blank_choice(self):
		FollowupStatus.objects.create(name='Other', **self.audit)
		requested = FollowupStatus.objects.create(name='Requested', **self.audit)
		field = forms.TransientFollowupForm().fields['status']
		self.assertEqual(field.initial, requested)
		self.assertIsNone(field.empty_label)  # as when the initial value is given to the field itself

	def test_followup_form_works_when_there_is_no_requested_status(self):
		field = forms.TransientFollowupForm().fields['status']
		self.assertIsNone(field.initial)
		self.assertEqual(field.empty_label, '---------')

	def test_a_classical_resource_added_while_running_shows_up_in_a_new_form(self):
		before = forms.TransientFollowupForm()
		self.assertEqual(before.fields['classical_resource'].queryset.count(), 0)
		self.assertIsNone(before.fields['valid_start'].initial)
		now = timezone.now()
		resource = ClassicalResource.objects.create(telescope=self.telescope, begin_date_valid=now,
													end_date_valid=now + timedelta(days=3), **self.audit)
		after = forms.TransientFollowupForm()
		self.assertEqual(list(after.fields['classical_resource'].queryset), [resource])
		self.assertEqual(after.fields['classical_resource'].initial, resource)
		self.assertEqual(after.fields['valid_start'].initial, resource.begin_date_valid)
		self.assertEqual(after.fields['valid_stop'].initial, resource.end_date_valid)

	def test_a_classical_resource_that_ended_days_ago_is_not_offered(self):
		now = timezone.now()
		ClassicalResource.objects.create(telescope=self.telescope, begin_date_valid=now - timedelta(days=10),
										 end_date_valid=now - timedelta(days=3), **self.audit)
		self.assertEqual(forms.TransientFollowupForm().fields['classical_resource'].queryset.count(), 0)

	# --- the fields that exist only when matching rows exist ---

	def test_survey_field_form_keeps_the_models_own_instrument_field_without_gpc_instruments(self):
		Instrument.objects.create(name='Other', telescope=self.telescope, **self.audit)
		field = forms.SurveyFieldForm().fields['instrument']
		self.assertTrue(field.required)  # the model's required foreign key, every instrument
		self.assertEqual(field.queryset.count(), 1)

	def test_survey_field_form_limits_instrument_to_gpc_when_they_exist(self):
		gpc = Instrument.objects.create(name='GPC1', telescope=self.telescope, **self.audit)
		Instrument.objects.create(name='Other', telescope=self.telescope, **self.audit)
		form = forms.SurveyFieldForm()
		field = form.fields['instrument']
		self.assertFalse(field.required)
		self.assertEqual(list(field.queryset), [gpc])
		self.assertEqual(field.initial, gpc)
		self.assertEqual(list(form.fields).index('instrument'), 3)  # keeps its place from Meta.fields

	def test_oncall_form_has_a_user_field_only_when_yse_users_exist(self):
		self.assertNotIn('user', forms.OncallForm().fields)
		member = User.objects.create_user('yse_member', password='pw')
		member.groups.add(Group.objects.create(name='YSE'))
		field = forms.OncallForm().fields['user']
		self.assertEqual(list(field.queryset), [member])
		self.assertEqual(field.initial, member)

	# --- choices that come from the database ---

	def test_survey_obs_choices_follow_the_database(self):
		self.assertEqual(forms.SurveyObsForm().fields['ztf_field_id'].choices, [])
		group = ObservationGroup.objects.create(name='Other', **self.audit)
		instrument = Instrument.objects.create(name='GPC1', telescope=self.telescope, **self.audit)
		SurveyField.objects.create(obs_group=group, field_id='f1', ztf_field_id='ztf100', instrument=instrument,
								   ra_cen=1.0, dec_cen=2.0, width_deg=1.0, height_deg=1.0, **self.audit)
		field = forms.SurveyObsForm().fields['ztf_field_id']
		self.assertEqual(field.choices, [('ztf100', 'ztf100')])
		self.assertEqual(field.initial, ('ztf100', 'ztf100'))

	def test_spectrum_upload_permissions_follow_the_groups_in_the_database(self):
		self.assertNotIn(('alpha', 'alpha'), forms.SpectrumUploadForm().fields['permissions'].choices)
		Group.objects.create(name='alpha')
		self.assertIn(('alpha', 'alpha'), forms.SpectrumUploadForm().fields['permissions'].choices)
