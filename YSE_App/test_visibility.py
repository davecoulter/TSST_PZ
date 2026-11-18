"""#86 phase 1: the visibility rule in TransientService, and the photometry and spectra services that
call it. Users in group A, group B, no group, and a superuser, against transients restricted to A,
to B, reported to TNS, public, and with no group at all."""
import datetime

from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import TestCase

from .data import PhotometryService, SpectraService, TransientService
from .data.TransientService import FULL, PUBLIC, TNS_OBJECT
from .models import (AlternateTransientNames, Host, HostPhotometry, Instrument, Observatory, ObservationGroup,
                     PhotometricBand, Telescope, Transient, TransientPhotData, TransientPhotometry,
                     TransientSpectrum, TransientStatus)

UTC = datetime.timezone.utc


class VisibilityTestBase(TestCase):

	@classmethod
	def setUpTestData(cls):
		cls.group_a = Group.objects.create(name='Team A')
		cls.group_b = Group.objects.create(name='Team B')
		cls.public = Group.objects.get(name=PUBLIC)  # made by migration 0017
		cls.user_a = User.objects.create_user('in_a', password='pw')
		cls.user_a.groups.add(cls.group_a)
		cls.user_b = User.objects.create_user('in_b', password='pw')
		cls.user_b.groups.add(cls.group_b)
		cls.nobody = User.objects.create_user('in_no_group', password='pw')
		cls.admin = User.objects.create_superuser('visibility_admin', password='pw')
		cls.audit = dict(created_by=cls.admin, modified_by=cls.admin)

		status = TransientStatus.objects.get_or_create(name='Candidate', defaults=cls.audit)[0]
		cls.survey = ObservationGroup.objects.create(name='TSST', **cls.audit)
		observatory = Observatory.objects.create(name='JWST', utc_offset=0, tz_name='UTC', **cls.audit)
		telescope = Telescope.objects.create(name='JWST', observatory=observatory, latitude=0.0, longitude=0.0,
		                                     elevation=0.0, **cls.audit)
		cls.nircam = Instrument.objects.create(name='NIRCam', telescope=telescope, **cls.audit)
		cls.band = PhotometricBand.objects.create(name='F200W', instrument=cls.nircam, **cls.audit)

		cls.host_a = Host.objects.create(name='host of A', ra=150.0, dec=2.0, **cls.audit)
		cls.host_shared = Host.objects.create(name='host of A and the public one', ra=150.1, dec=2.1, **cls.audit)
		cls.host_catalog = Host.objects.create(name='catalog galaxy', ra=150.2, dec=2.2, **cls.audit)

		def transient(name, groups, **fields):
			t = Transient.objects.create(name=name, ra=150.18, dec=2.44, status=status, obs_group=cls.survey,
			                             **dict(cls.audit, **fields))
			t.groups.set(groups)
			return t

		cls.t_a = transient('only_a', [cls.group_a], host=cls.host_a)
		cls.t_b = transient('only_b', [cls.group_b])
		cls.t_reported = transient('reported_a', [cls.group_a], iau_name='2026abc')
		cls.t_public = transient('public_one', [cls.public], host=cls.host_shared)
		cls.t_a_and_public = transient('a_and_public', [cls.group_a, cls.public])
		cls.t_orphan = transient('no_group', [])
		AlternateTransientNames.objects.create(transient=cls.t_a, name='old_name_of_a', **cls.audit)
		transient('also_a', [cls.group_a], host=cls.host_shared)

		def photometry(t, groups):
			p = TransientPhotometry.objects.create(transient=t, instrument=cls.nircam, obs_group=cls.survey,
			                                       **cls.audit)
			p.groups.set(groups)
			TransientPhotData.objects.create(photometry=p, band=cls.band, obs_date=datetime.datetime(2026, 1, 1, tzinfo=UTC),
			                                 mag=24.0, mag_err=0.1, **cls.audit)
			return p

		cls.p_reported_public = photometry(cls.t_reported, [cls.public])
		cls.p_reported_a = photometry(cls.t_reported, [cls.group_a])
		cls.p_hidden_public = photometry(cls.t_a, [cls.public])  # Public, but on a transient B can't see
		cls.p_public_orphan = photometry(cls.t_public, [])  # no group: superusers only

		def spectrum(t, groups):
			s = TransientSpectrum.objects.create(transient=t, instrument=cls.nircam, obs_group=cls.survey, ra=t.ra,
			                                     dec=t.dec, obs_date=datetime.datetime(2026, 1, 2, tzinfo=UTC),
			                                     **cls.audit)
			s.groups.set(groups)
			return s

		cls.s_reported_public = spectrum(cls.t_reported, [cls.public])
		cls.s_hidden_public = spectrum(cls.t_a, [cls.public])

		cls.hp_host_a = HostPhotometry.objects.create(host=cls.host_a, instrument=cls.nircam, obs_group=cls.survey,
		                                              **cls.audit)
		cls.hp_host_a.groups.set([cls.public])


class TransientRuleTests(VisibilityTestBase):

	def visible(self, user):
		return set(TransientService.visible_transients(user).values_list('name', flat=True))

	def test_each_user_sees_their_groups_public_and_tns_objects(self):
		shared = {'reported_a', 'public_one', 'a_and_public'}
		self.assertEqual(self.visible(self.user_a), shared | {'only_a', 'also_a'})
		self.assertEqual(self.visible(self.user_b), shared | {'only_b'})
		self.assertEqual(self.visible(self.nobody), shared)

	def test_no_group_means_superusers_only(self):
		self.assertIn('no_group', self.visible(self.admin))
		for user in (self.user_a, self.user_b, self.nobody):
			self.assertNotIn('no_group', self.visible(user))

	def test_anonymous_users_get_only_public_and_tns_objects(self):
		self.assertEqual(self.visible(AnonymousUser()), {'reported_a', 'public_one', 'a_and_public'})

	def test_full_access_leaves_out_tns_objects_of_other_groups(self):
		full = set(TransientService.full_access_transients(self.user_b).values_list('name', flat=True))
		self.assertEqual(full, {'only_b', 'public_one', 'a_and_public'})

	def test_access_levels(self):
		level = TransientService.access_level
		self.assertEqual(level(self.user_a, self.t_reported), FULL)
		self.assertEqual(level(self.user_b, self.t_reported), TNS_OBJECT)
		self.assertIsNone(level(self.user_b, self.t_a))
		self.assertEqual(level(self.user_b, self.t_public), FULL)
		self.assertIsNone(level(self.user_a, self.t_orphan))
		self.assertEqual(level(self.admin, self.t_orphan), FULL)

	def test_no_duplicate_rows_for_a_transient_in_several_of_the_users_groups(self):
		visible = TransientService.visible_transients(self.user_a).filter(name='a_and_public')
		self.assertEqual(visible.count(), 1)
		self.assertEqual(len(list(visible)), 1)

	def test_a_queryset_passed_in_is_narrowed_not_replaced(self):
		some = Transient.objects.filter(name__in=['only_a', 'only_b'])
		self.assertEqual(list(TransientService.visible_transients(self.user_b, some)), [self.t_b])

	def test_a_hidden_transient_is_not_found_by_slug_alias_or_name(self):
		find = TransientService.find_visible_transient
		for slug in (self.t_a.slug, 'old_name_of_a', 'only_a'):
			self.assertIsNone(find(self.user_b, slug), slug)
			self.assertEqual(find(self.user_a, slug), self.t_a, slug)
		self.assertEqual(find(self.user_b, 'AT 2026abc'), self.t_reported)

	def test_rows_hanging_off_a_transient_follow_it(self):
		aliases = AlternateTransientNames.objects.all()
		self.assertFalse(TransientService.filter_by_transient(aliases, self.user_b).exists())
		self.assertEqual(TransientService.filter_by_transient(aliases, self.user_a).count(), 1)


class DataRuleTests(VisibilityTestBase):

	def test_photometry_needs_its_group_and_a_visible_transient(self):
		allowed = set(PhotometryService.GetAuthorizedTransientPhotometry_ByUser(self.user_b))
		self.assertEqual(allowed, {self.p_reported_public})

	def test_group_members_see_their_photometry_public_or_not(self):
		allowed = set(PhotometryService.GetAuthorizedTransientPhotometry_ByUser(self.user_a))
		self.assertEqual(allowed, {self.p_reported_public, self.p_reported_a, self.p_hidden_public})

	def test_photometry_with_no_group_is_for_superusers_only(self):
		self.assertIn(self.p_public_orphan, PhotometryService.GetAuthorizedTransientPhotometry_ByUser(self.admin))
		for user in (self.user_a, self.user_b, self.nobody):
			self.assertNotIn(self.p_public_orphan, PhotometryService.GetAuthorizedTransientPhotometry_ByUser(user))

	def test_phot_data_follows_its_photometry(self):
		data = PhotometryService.GetAuthorizedTransientPhotData_ByUser(self.user_b)
		self.assertEqual({d.photometry_id for d in data}, {self.p_reported_public.pk})
		by_transient = PhotometryService.GetAuthorizedTransientPhotData_ByUser_ByTransient(self.user_b, self.t_a.pk)
		self.assertFalse(by_transient.exists())

	def test_spectra_follow_the_same_rule(self):
		self.assertEqual(set(SpectraService.GetAuthorizedTransientSpectrum_ByUser(self.user_b)), {self.s_reported_public})
		self.assertEqual(set(SpectraService.GetAuthorizedTransientSpectrum_ByUser(self.user_a)),
		                 {self.s_reported_public, self.s_hidden_public})


class HostRuleTests(VisibilityTestBase):

	def hosts(self, user):
		return set(TransientService.visible_hosts(user))

	def test_hosts_follow_their_transients_and_catalog_hosts_are_open(self):
		self.assertEqual(self.hosts(self.user_b), {self.host_shared, self.host_catalog})
		self.assertEqual(self.hosts(self.user_a), {self.host_a, self.host_shared, self.host_catalog})
		self.assertEqual(self.hosts(self.admin), {self.host_a, self.host_shared, self.host_catalog})

	def test_host_photometry_needs_a_visible_host(self):
		self.assertFalse(PhotometryService.GetAuthorizedHostPhotometry_ByUser(self.user_b).exists())
		self.assertEqual(list(PhotometryService.GetAuthorizedHostPhotometry_ByUser(self.user_a)), [self.hp_host_a])
