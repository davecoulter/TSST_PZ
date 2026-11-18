"""#86: the visibility rule in TransientService (phase 1), and the pages for one transient that go
through it (phase 2, part 1). Users in group A, group B, no group, and a superuser, against transients
restricted to A, to B, reported to TNS, public, and with no group at all."""
import datetime

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from . import table_utils
from .access import transient_access
from .data import PhotometryService, SpectraService, TransientService
from .data.TransientService import FULL, PUBLIC, TNS_OBJECT
from .models import (AlternateTransientNames, FollowupStatus, TagKind, TransientTag, Host, HostPhotometry, Instrument, Log, Observatory,
                     ObservationGroup, PhotometricBand, Telescope, Transient, TransientDiffImage, TransientFollowup,
                     TransientPhotData, TransientPhotometry, TransientSpecData, TransientSpectrum, TransientStatus)

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
		cls.curator_a = User.objects.create_user('curator_in_a', password='pw')  # the role (migration 0020) and the scope
		cls.curator_a.groups.add(cls.group_a, Group.objects.get(name='Transient Curators'))
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
		# at the transients' position, so the detail page lists the transients near it
		cls.host_shared = Host.objects.create(name='host of A and the public one', ra=150.18, dec=2.44, **cls.audit)
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
			TransientSpecData.objects.bulk_create([  # the plots smooth the spectrum, so they need a few points
				TransientSpecData(spectrum=s, wavelength=10000.0 + 200 * i, flux=1e-17 * (1 + i % 5), **cls.audit)
				for i in range(50)])
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

	def test_curating_needs_the_role_and_one_of_the_transients_groups(self):
		can_edit = TransientService.can_edit
		self.assertFalse(can_edit(self.user_a, self.t_reported))  # in A, but only a viewer
		self.assertTrue(can_edit(self.curator_a, self.t_reported))
		self.assertTrue(can_edit(self.curator_a, self.t_a_and_public))
		self.assertFalse(can_edit(self.curator_a, self.t_b))  # the role doesn't reach other groups
		self.assertTrue(can_edit(self.admin, self.t_orphan))

	def test_public_grants_reading_only(self):
		self.assertEqual(TransientService.access_level(self.user_b, self.t_public), FULL)
		self.assertFalse(TransientService.can_edit(self.curator_a, self.t_public))  # everyone reads it; no team owns it

	def test_anyone_who_can_see_a_transient_may_comment_on_it(self):
		self.assertTrue(TransientService.can_comment(self.user_b, self.t_reported))  # a TNS object to B
		self.assertTrue(TransientService.can_comment(self.nobody, self.t_public))
		self.assertFalse(TransientService.can_comment(self.user_b, self.t_a))

	def test_only_its_author_or_a_superuser_changes_an_added_item(self):
		log = Log.objects.create(transient=self.t_public, comment='mine', created_by=self.user_b, modified_by=self.user_b)
		self.assertTrue(TransientService.can_change(self.user_b, log))
		self.assertFalse(TransientService.can_change(self.curator_a, log))
		self.assertTrue(TransientService.can_change(self.admin, log))

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


class RolesTests(VisibilityTestBase):

	def test_groups_that_grant_permissions_are_roles_not_data_groups(self):
		names = set(TransientService.data_groups().values_list('name', flat=True))
		self.assertTrue({'Team A', 'Team B', PUBLIC} <= names)
		self.assertNotIn('TNS Reporters', names)  # granted mutate_tns_metadata by migration 0019
		self.assertNotIn('Transient Curators', names)  # granted curate_transients by migration 0020

	def test_the_tns_permission_comes_from_the_group_and_superusers_have_it(self):
		reporter = User.objects.create_user('reporter', password='pw')
		reporter.groups.add(Group.objects.get(name='TNS Reporters'))
		self.assertTrue(reporter.has_perm('YSE_App.mutate_tns_metadata'))
		self.assertTrue(self.admin.has_perm('YSE_App.mutate_tns_metadata'))
		self.assertFalse(self.user_a.has_perm('YSE_App.mutate_tns_metadata'))


class MetadataRuleTests(VisibilityTestBase):
	"""Comments (Log) and follow-ups have their own groups, and need what they're attached to visible."""

	def comment(self, text, groups, **target):
		log = Log.objects.create(comment=text, **dict(self.audit, **target))
		log.groups.set(groups)
		return log

	def test_comments_need_their_group_and_a_visible_target(self):
		public = self.comment('public note', [self.public], transient=self.t_reported)
		self.comment('A note', [self.group_a], transient=self.t_reported)
		self.comment('public note on a hidden transient', [self.public], transient=self.t_a)
		on_phot = self.comment('public note on A-only photometry', [self.public], transient_photometry=self.p_reported_a)
		orphan = self.comment('no group', [], transient=self.t_public)
		self.assertEqual(set(TransientService.authorized_logs(Log.objects.all(), self.user_b)), {public})
		self.assertIn(on_phot, TransientService.authorized_logs(Log.objects.all(), self.user_a))
		self.assertNotIn(orphan, TransientService.authorized_logs(Log.objects.all(), self.user_a))
		self.assertIn(orphan, TransientService.authorized_logs(Log.objects.all(), self.admin))

	def test_follow_ups_need_their_group_and_a_visible_transient(self):
		status = FollowupStatus.objects.create(name='Requested', **self.audit)
		window = dict(valid_start=datetime.datetime(2026, 1, 1, tzinfo=UTC),
		              valid_stop=datetime.datetime(2026, 2, 1, tzinfo=UTC), status=status, **self.audit)
		ours = TransientFollowup.objects.create(transient=self.t_reported, **window)
		ours.groups.set([self.group_a])
		shared = TransientFollowup.objects.create(transient=self.t_reported, **window)
		shared.groups.set([self.public])
		on_hidden = TransientFollowup.objects.create(transient=self.t_a, **window)
		on_hidden.groups.set([self.public])
		allowed = TransientService.authorized_data(TransientFollowup.objects.all(), self.user_b)
		self.assertEqual(set(allowed), {shared})


class AccessDecoratorTests(VisibilityTestBase):

	def call(self, user, transient, level):
		@transient_access(level=level, by='transient_id')
		def view(request, transient):
			return HttpResponse(transient.name)
		request = RequestFactory().get('/')
		request.user = user
		return view(request, transient_id=transient.pk)

	def test_a_hidden_id_is_a_404_and_a_tns_object_is_403_where_full_access_is_needed(self):
		self.assertEqual(self.call(self.user_b, self.t_reported, TNS_OBJECT).content, b'reported_a')
		with self.assertRaises(PermissionDenied):
			self.call(self.user_b, self.t_reported, FULL)
		with self.assertRaises(Http404):
			self.call(self.user_b, self.t_a, TNS_OBJECT)
		with self.assertRaises(PermissionDenied):
			self.call(self.user_a, self.t_reported, FULL)  # in A, but not a curator
		self.assertEqual(self.call(self.curator_a, self.t_reported, FULL).content, b'reported_a')


class TransientPagesTests(VisibilityTestBase):
	"""One detail page for every level: what B gets of A's transients is decided by the data, not the page."""

	@classmethod
	def setUpTestData(cls):
		super().setUpTestData()
		for name in ('Following', 'Watch', 'Interesting', 'Ignore'):  # the legacy transient page needs them
			TransientStatus.objects.get_or_create(name=name, defaults=cls.audit)
		for text, groups in (('a public note', [cls.public]), ('a secret A note', [cls.group_a])):
			log = Log.objects.create(transient=cls.t_reported, comment=text, **cls.audit)
			log.groups.set(groups)
		TransientDiffImage.objects.create(phot_data=TransientPhotData.objects.get(photometry=cls.p_reported_a),
		                                  postage_stamp_file='https://example.org/secret_a_stamp.png',
		                                  valid_pixels=True, **cls.audit)

	def get(self, user, name, *args):
		self.client.force_login(user)
		return self.client.get(reverse(name, args=args))

	def test_a_hidden_transient_is_the_not_found_page_by_slug_alias_or_name(self):
		for page in ('transient_detail', 'candidate_detail'):
			for slug in (self.t_a.slug, 'old_name_of_a', 'only_a'):
				response = self.get(self.user_b, page, slug)
				self.assertContains(response, 'that you can see', status_code=404)
				self.assertNotContains(response, '150.18', status_code=404)
			missing = self.get(self.user_b, page, 'no_such_transient')
			self.assertContains(missing, 'that you can see', status_code=404)

	def test_a_tns_object_shows_its_facts_and_only_the_data_its_viewer_may_see(self):
		response = self.get(self.user_b, 'transient_detail', self.t_reported.slug)
		self.assertContains(response, '2026abc')
		self.assertContains(response, 'a public note')
		self.assertNotContains(response, 'a secret A note')
		self.assertNotContains(response, 'secret_a_stamp.png')
		mine = self.get(self.user_a, 'transient_detail', self.t_reported.slug)
		self.assertContains(mine, 'a secret A note')
		self.assertContains(mine, 'secret_a_stamp.png')

	def test_the_transients_near_the_host_leave_out_hidden_ones(self):
		response = self.get(self.user_b, 'transient_detail', self.t_public.slug)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'only_b')
		for hidden in ('only_a', 'also_a', 'no_group'):
			self.assertNotContains(response, hidden)

	def test_the_candidate_dashboard_lists_only_visible_candidates(self):
		response = self.get(self.user_b, 'candidate_dashboard')
		self.assertContains(response, 'only_b')
		for hidden in ('only_a', 'also_a', 'no_group'):
			self.assertNotContains(response, hidden)

	def test_plots_by_id_need_a_login_and_a_visible_transient(self):
		for page in ('spectrumplot', 'spectrumplot_summary', 'candidate_sed'):
			self.assertEqual(self.get(self.user_b, page, self.t_a.pk).status_code, 404, page)
			self.assertEqual(self.get(self.user_b, page, self.t_reported.pk).status_code, 200, page)
		self.client.logout()
		for page in ('spectrumplot', 'spectrumplot_summary'):
			self.assertEqual(self.client.get(reverse(page, args=[self.t_reported.pk])).status_code, 302, page)
		self.client.force_login(self.user_b)
		single = reverse('spectrumplotsingle', args=[self.t_a.pk, self.s_hidden_public.pk])
		self.assertEqual(self.client.get(single).status_code, 404)


class ListsTests(VisibilityTestBase):
	"""Phase 2, part 2: lists, counts and search show only visible transients, and their photometry
	columns only the photometry the viewer may see."""

	@classmethod
	def setUpTestData(cls):
		super().setUpTestData()
		# a newer, brighter point that only A may see, on the transient B sees as a TNS object
		TransientPhotData.objects.create(photometry=cls.p_reported_a, band=cls.band, mag=21.11, mag_err=0.1,
		                                 obs_date=datetime.datetime(2026, 2, 1, tzinfo=UTC), **cls.audit)
		# off the candidate list and onto the main dashboard (Needs review: no tag yet)
		watch = TransientStatus.objects.get_or_create(name='Watch', defaults=cls.audit)[0]
		Transient.objects.filter(pk__in=[cls.t_a.pk, cls.t_b.pk, cls.t_reported.pk]).update(status=watch)
		kind = TagKind.objects.create(name='Candidate', **cls.audit)
		new = TransientTag.objects.create(name='New', kind=kind, **cls.audit)
		cls.t_also_a = Transient.objects.get(name='also_a')
		cls.t_also_a.tags.add(new)  # a new candidate only A may see
		cls.t_public.tags.add(new)

	def get(self, user, url):
		self.client.force_login(user)
		return self.client.get(url)

	def test_photometry_columns_show_only_what_the_viewer_may_see(self):
		rows = lambda user: {t.name: t for t in table_utils.visible_rows(user, Transient.objects.all())}
		self.assertEqual(rows(self.user_b)['reported_a'].recent_mag, 24.0)  # B's only point is the Public one
		self.assertEqual(rows(self.user_a)['reported_a'].recent_mag, 21.11)
		self.assertNotIn('only_a', rows(self.user_b))
		page = self.get(self.user_b, reverse('search') + '?q=reported_a')
		self.assertContains(page, '24.00')
		self.assertNotContains(page, '21.11')
		self.assertContains(self.get(self.user_a, reverse('search') + '?q=reported_a'), '21.11')

	def test_sorting_by_last_mag_uses_the_visible_values(self):
		page = self.get(self.user_b, reverse('search') + '?q=a&sort=-recent_mag')
		self.assertEqual(page.status_code, 200)
		self.assertNotContains(page, '21.11')

	def test_search_and_the_dashboard_leave_out_hidden_transients(self):
		for url in (reverse('search') + '?q=only', reverse('dashboard')):
			page = self.get(self.user_b, url)
			self.assertContains(page, 'only_b')
			self.assertNotContains(page, 'only_a')
		self.assertContains(self.get(self.user_a, reverse('dashboard')), 'only_a')

	def test_search_by_coordinates_leaves_out_hidden_transients(self):
		page = self.get(self.user_b, reverse('search') + '?q=150.18,2.44')
		self.assertContains(page, 'only_b')
		for hidden in ('only_a', 'also_a', 'no_group'):
			self.assertNotContains(page, hidden)

	def test_the_sidebar_counts_only_visible_candidates(self):
		from .templatetags.candidate_extras import candidate_count
		request = RequestFactory().get('/')
		request.user = self.user_b
		self.assertEqual(candidate_count({'request': request}), 1)  # the public one, not A's
		request.user = self.user_a
		self.assertEqual(candidate_count({'request': request}), 2)

	def test_search_by_tag_leaves_out_hidden_transients(self):
		tag = TransientTag.objects.get(name='New')
		data = self.get(self.user_b, reverse('get_transient_tags') + '?tagid=%d' % tag.pk).json()
		self.assertEqual({row['name'] for row in data.values()}, {'public_one'})

	def test_saved_query_results_are_narrowed_to_what_the_user_may_see(self):
		rows = [('only_a', 1), ('only_b', 2), ('no_group', 3)]
		self.assertEqual({t.name for t in TransientService.filter_query_results(self.user_b, rows)}, {'only_b'})
		self.assertEqual({t.name for t in TransientService.filter_query_results(self.admin, rows)},
		                 {'only_a', 'only_b', 'no_group'})


class EndpointsTests(VisibilityTestBase):
	"""Phase 2, part 2 (second half): exports, the lookups scripts call, the plot and image endpoints,
	transient_summary, the archived page, and the TNS form."""

	@classmethod
	def setUpTestData(cls):
		super().setUpTestData()
		for name in ('Following', 'FollowupRequested', 'Watch', 'Interesting', 'Ignore'):  # transient_summary needs them
			TransientStatus.objects.get_or_create(name=name, defaults=cls.audit)
		cls.watch = TransientStatus.objects.get(name='Watch')
		cls.archived = TransientStatus.objects.get_or_create(name='Archived', defaults=cls.audit)[0]
		# a detection only A may see, on the transient B sees as a TNS object
		cls.private_point = TransientPhotData.objects.create(
			photometry=cls.p_reported_a, band=cls.band, flux=1.0, flux_err=0.01, mag=23.9, mag_err=0.01,
			obs_date=datetime.datetime(2026, 2, 1, tzinfo=UTC), **cls.audit)

	def get(self, user, name, *args, query=''):
		self.client.force_login(user)
		return self.client.get(reverse(name, args=args) + query)

	def test_exports_hide_hidden_transients_and_private_photometry(self):
		for page in ('download_data', 'download_photometry', 'download_spectra'):
			self.assertEqual(self.get(self.user_b, page, self.t_a.slug).status_code, 404, page)
		data = self.get(self.user_b, 'download_data', self.t_reported.slug).json()['reported_a']
		self.assertEqual({p['pk'] for p in data['photometry']}, {self.p_reported_public.pk})
		mine = self.get(self.user_a, 'download_data', self.t_reported.slug).json()['reported_a']
		self.assertEqual({p['pk'] for p in mine['photometry']}, {self.p_reported_public.pk, self.p_reported_a.pk})

	def test_lookups_leave_out_hidden_transients_and_their_hosts(self):
		self.assertEqual(self.get(self.user_b, 'get_transient', self.t_a.slug).json(), {'transient': ''})
		self.assertNotEqual(self.get(self.user_a, 'get_transient', self.t_a.slug).json()['transient'], '')
		recent = datetime.datetime.now(UTC) - datetime.timedelta(days=1)  # the box lists recent ones in these statuses
		Transient.objects.filter(pk__in=[self.t_a.pk, self.t_b.pk]).update(status=self.watch, disc_date=recent)
		box = self.get(self.user_b, 'get_new_transients_box', '150.18', '2.44', '1.0', '1.0').json()
		names = {t['transient_name'] for t in box['transients']}
		self.assertIn('only_b', names)
		self.assertFalse({'only_a', 'also_a', 'no_group'} & names)
		hosts = self.get(self.user_b, 'get_host', '150.1', '2.2', '60.0').json()['host candidates']
		self.assertEqual({h['host_name'] for h in hosts}, {'host of A and the public one', 'catalog galaxy'})

	def test_plot_and_image_endpoints_need_a_login_and_a_visible_transient(self):
		pages = [('lightcurveplot_detail', self.t_a.pk), ('lightcurveplot_flux', self.t_a.pk),
		         ('lightcurveplot_summary', self.t_a.pk), ('salt2plot', self.t_a.pk, 0), ('finderchart', self.t_a.pk),
		         ('finderim', self.t_a.pk), ('get_ps1_image', self.t_a.pk), ('get_legacy_image', self.t_a.pk),
		         ('get_hst_image', self.t_a.pk), ('get_chandra_image', self.t_a.pk)]
		for name, *args in pages:
			self.assertEqual(self.get(self.user_b, name, *args).status_code, 404, name)
		self.client.logout()
		for name, *args in pages:
			self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 302, name)
		self.assertEqual(self.get(self.user_b, 'lightcurveplot_detail', self.t_reported.pk).status_code, 200)

	def test_transient_summary_lists_and_sorts_only_what_the_user_may_see(self):
		Transient.objects.filter(pk__in=[self.t_a.pk, self.t_b.pk, self.t_reported.pk]).update(status=self.watch)
		for sort in ('', '?sort=-last_mag', '?sort=last_obs_date'):
			page = self.get(self.user_b, 'transient_summary', 'Watch', query=sort)
			self.assertContains(page, 'only_b')
			self.assertNotContains(page, 'only_a')

	def test_the_archived_page_and_count_leave_out_hidden_transients(self):
		from .templatetags.candidate_extras import archived_count
		Transient.objects.filter(pk__in=[self.t_a.pk, self.t_b.pk]).update(status=self.archived)
		page = self.get(self.user_b, 'archived_dashboard')
		self.assertContains(page, 'only_b')
		self.assertNotContains(page, 'only_a')
		request = RequestFactory().get('/')
		request.user = self.user_b
		self.assertEqual(archived_count({'request': request}), 1)

	def test_the_tns_form_offers_only_photometry_the_reporter_can_see(self):
		from . import tns_report
		offered = lambda user: {d['id'] for d in tns_report.transient_fields(user, self.t_reported)['detections']}
		self.assertNotIn(self.private_point.pk, offered(self.user_b))
		self.assertIn(self.private_point.pk, offered(self.user_a))


class ApiTests(VisibilityTestBase):
	"""Phase 2, part 3a: the API. Reads by the group rule; comments by anyone who can see; curating by
	the role and the transient's groups; links in writes by the same rules; #92."""

	@classmethod
	def setUpTestData(cls):
		super().setUpTestData()
		cls.curator_b = User.objects.create_user('curator_in_b', password='pw')
		cls.curator_b.groups.add(cls.group_b, Group.objects.get(name='Transient Curators'))

	def api(self, user=None):
		from rest_framework.test import APIClient
		client = APIClient()
		if user is not None:
			client.force_authenticate(user)
		return client

	def url(self, name, *args):
		return reverse(name, args=args)

	def test_without_credentials_only_the_root_and_schema_answer(self):
		anonymous = self.api()
		self.assertIn(anonymous.get(self.url('transient-list')).status_code, (401, 403))
		self.assertIn(anonymous.get(self.url('hostcatalog-list')).status_code, (401, 403))  # was open to anonymous reads
		self.assertEqual(anonymous.get(self.url('api-root')).status_code, 200)
		self.assertNotIn(anonymous.get('/api/schema/').status_code, (401, 403))

	def test_users_and_groups_are_for_superusers_and_never_show_hashes_or_emails(self):
		for name, args in (('user-list', ()), ('user-detail', (self.user_a.pk,)), ('group-list', ()),
		                   ('group-detail', (self.group_a.pk,))):
			self.assertEqual(self.api(self.user_b).get(self.url(name, *args)).status_code, 403, name)
		body = self.api(self.admin).get(self.url('user-detail', self.user_a.pk)).json()
		self.assertEqual(set(body), {'url', 'username', 'first_name', 'last_name'})
		self.assertEqual(set(self.api(self.admin).get(self.url('group-detail', self.group_a.pk)).json()), {'url', 'name'})

	def test_reads_follow_the_group_rule(self):
		names = {t['name'] for t in self.api(self.user_b).get(self.url('transient-list') + '?limit=100').json()['results']}
		self.assertEqual(names, {'only_b', 'reported_a', 'public_one', 'a_and_public'})
		self.assertEqual(self.api(self.user_b).get(self.url('transient-detail', self.t_a.pk)).status_code, 404)
		filtered = self.api(self.user_a).get(self.url('transient-list') + '?group_in=Public&limit=100').json()['results']
		self.assertEqual({t['name'] for t in filtered}, {'public_one', 'a_and_public'})
		self.assertEqual(self.api(self.user_b).get(self.url('transient-detail', self.t_public.pk)).json()['groups'], ['Public'])

	def test_anyone_who_can_see_a_transient_may_comment_with_their_own_groups_or_public(self):
		client = self.api(self.user_b)
		on = lambda t, groups: client.post(self.url('log-list'), {'comment': 'hi', 'groups': groups,
		                                    'transient': self.url('transient-detail', t.pk)}, format='json')
		self.assertEqual(on(self.t_reported, ['Team B']).status_code, 201)  # a TNS object to B
		self.assertEqual(on(self.t_reported, ['Public']).status_code, 201)
		self.assertEqual(on(self.t_reported, ['Team A']).status_code, 400)  # not B's group
		self.assertEqual(on(self.t_reported, []).status_code, 400)  # at least one group
		hidden = on(self.t_a, ['Team B'])
		self.assertEqual(hidden.status_code, 400)
		self.assertIn('does not exist', str(hidden.json()['transient']))  # the same as a missing transient

	def test_only_the_author_changes_a_comment(self):
		self.api(self.user_b).post(self.url('log-list'), {'comment': 'mine', 'groups': ['Public'],
		                           'transient': self.url('transient-detail', self.t_public.pk)}, format='json')
		log = Log.objects.get(comment='mine')
		self.assertEqual(self.api(self.curator_a).patch(self.url('log-detail', log.pk), {'comment': 'x'}, format='json').status_code, 403)
		self.assertEqual(self.api(self.user_b).patch(self.url('log-detail', log.pk), {'comment': 'edited'}, format='json').status_code, 200)

	def test_curating_needs_the_role_and_the_transients_group(self):
		status = self.url('transientstatus-detail', TransientStatus.objects.get(name='Candidate').pk)
		patch = lambda user, t: self.api(user).patch(self.url('transient-detail', t.pk), {'status': status}, format='json')
		self.assertEqual(patch(self.user_a, self.t_reported).status_code, 403)  # in A, but a viewer
		self.assertEqual(patch(self.curator_b, self.t_reported).status_code, 403)  # a curator, but not of A's
		self.assertEqual(patch(self.curator_a, self.t_reported).status_code, 200)
		self.assertEqual(patch(self.curator_a, self.t_b).status_code, 404)  # hidden from A

	def test_only_a_superuser_changes_who_may_see_a_transient(self):
		groups = lambda user: self.api(user).patch(self.url('transient-detail', self.t_reported.pk),
		                                           {'groups': ['Team A', 'Public']}, format='json')
		self.assertEqual(groups(self.curator_a).status_code, 400)  # Public isn't a group a curator can set
		self.assertEqual(self.api(self.curator_a).patch(self.url('transient-detail', self.t_reported.pk),
		                                                {'groups': ['Team A']}, format='json').status_code, 403)
		self.assertEqual(groups(self.admin).status_code, 200)

	def test_uploads_need_the_role_own_groups_and_never_public(self):
		def upload(user, t, groups):
			return self.api(user).post(self.url('transientphotometry-list'), {
				'transient': self.url('transient-detail', t.pk), 'groups': groups,
				'instrument': self.url('instrument-detail', self.nircam.id),
				'obs_group': self.url('observationgroup-detail', self.survey.pk)}, format='json')
		self.assertEqual(upload(self.user_a, self.t_reported, ['Team A']).status_code, 403)  # no role
		self.assertEqual(upload(self.curator_a, self.t_reported, ['Team A']).status_code, 201)
		self.assertEqual(upload(self.curator_a, self.t_reported, ['Public']).status_code, 400)  # releasing is a superuser's
		self.assertEqual(upload(self.curator_b, self.t_reported, ['Team B']).status_code, 400)  # not B's transient

	def test_a_point_on_photometry_the_writer_may_not_use_is_refused_and_not_saved(self):
		before = TransientPhotData.objects.count()
		response = self.api(self.curator_b).post(self.url('transientphotdata-list'), {
			'photometry': self.url('transientphotometry-detail', self.p_reported_a.id), 'band': self.url('photometricband-detail', self.band.id),
			'obs_date': '2026-03-01T00:00:00Z', 'mag': 20.0, 'data_quality': []}, format='json')
		self.assertEqual(response.status_code, 400)
		self.assertEqual(TransientPhotData.objects.count(), before)

	def test_per_user_tables_show_only_the_users_own_rows(self):
		from .models import Profile
		for user in (self.user_a, self.user_b):
			Profile.objects.get_or_create(user=user, defaults=self.audit)
		rows = self.api(self.user_b).get(self.url('profile-list')).json()['results']
		self.assertEqual(len(rows), 1)

	# --- the shared tables and tags (plan review 12) ---

	def test_site_wide_tables_are_written_only_by_superusers(self):
		body = {'name': 'NewCam', 'telescope': self.url('telescope-detail', self.nircam.telescope.pk)}
		self.assertEqual(self.api(self.curator_a).post(self.url('instrument-list'), body, format='json').status_code, 403)
		self.assertEqual(self.api(self.curator_a).delete(self.url('instrument-detail', self.nircam.id)).status_code, 403)
		self.assertEqual(self.api(self.admin).post(self.url('instrument-list'), body, format='json').status_code, 201)
		self.assertEqual(self.api(self.user_b).get(self.url('instrument-list')).status_code, 200)  # reading is open

	def test_anyone_creates_a_tag_its_creator_changes_it_superusers_delete_it(self):
		created = self.api(self.user_b).post(self.url('transienttag-list'), {'name': 'interesting to B'}, format='json')
		self.assertEqual(created.status_code, 201, created.content)
		tag = TransientTag.objects.get(name='interesting to B')
		rename = lambda user: self.api(user).patch(self.url('transienttag-detail', tag.pk), {'name': 'renamed'}, format='json')
		self.assertEqual(rename(self.curator_a).status_code, 403)
		self.assertEqual(rename(self.user_b).status_code, 200)
		self.assertEqual(self.api(self.user_b).delete(self.url('transienttag-detail', tag.pk)).status_code, 403)

	def test_the_obsolete_yse_tables_are_for_superusers_only(self):
		for name in ('surveyfield-list', 'surveyobservation-list', 'oncalldate-list'):
			self.assertEqual(self.api(self.user_b).get(self.url(name)).status_code, 403, name)
			self.assertEqual(self.api(self.admin).get(self.url(name)).status_code, 200, name)

	def test_anyone_who_can_see_a_transient_adds_tags_and_a_curator_removes_them(self):
		tag = TransientTag.objects.create(name='seen by B', **self.audit)
		link = self.url('transienttag-detail', tag.pk)
		tags = lambda user, t, links: self.api(user).patch(self.url('transient-detail', t.pk), {'tags': links}, format='json')
		self.assertEqual(tags(self.user_b, self.t_reported, [link]).status_code, 200)  # B sees it as a TNS object
		self.assertEqual(list(self.t_reported.tags.all()), [tag])
		self.assertEqual(tags(self.user_b, self.t_reported, []).status_code, 403)  # removing is curating
		self.assertEqual(tags(self.user_b, self.t_a, [link]).status_code, 404)  # hidden
		self.assertEqual(tags(self.curator_a, self.t_reported, []).status_code, 200)
		self.assertFalse(self.t_reported.tags.exists())
		status = self.url('transientstatus-detail', TransientStatus.objects.get(name='Candidate').pk)
		mixed = self.api(self.user_b).patch(self.url('transient-detail', self.t_reported.pk),
		                                    {'tags': [link], 'status': status}, format='json')
		self.assertEqual(mixed.status_code, 403)  # anything beyond adding tags is curating
