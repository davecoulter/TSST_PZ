from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import AlternateTransientNames, ObservationGroup, Transient, TransientStatus
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
