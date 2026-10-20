"""#52: the TNS values snapshot and the AT report payload builder. No TNS call is made here."""
import datetime
import json
import math

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from . import tns_report, tns_values
from .models import (DataQuality, Host, Instrument, Log, Observatory, ObservationGroup, PhotometricBand,
                     Telescope, Transient, TransientPhotData, TransientPhotometry, TransientStatus)

UTC = datetime.timezone.utc


def at(*args):
	return datetime.datetime(*args, tzinfo=UTC)


class TnsValuesTests(SimpleTestCase):
	"""The committed snapshot and its lookups."""

	def test_snapshot_gives_the_ids_of_daves_bot_script(self):
		self.assertEqual(tns_values.load()['retrieved'], '2025-06-18')
		self.assertEqual(tns_values.find_id('groups', 'TSST_COSMOS_3D'), '170')
		self.assertEqual(tns_values.find_id('instruments', 'JWST - NIRCam'), '185')
		self.assertEqual(tns_values.find_id('units', 'ABMag'), '1')
		self.assertEqual(tns_values.find_id('filters', 'F200W-JWST'), '100')
		self.assertEqual(tns_values.find_id('archives', 'Other'), '0')

	def test_find_id_matches_a_label_or_its_code(self):
		self.assertEqual(tns_values.find_id('at_types', ' psn '), '1')  # 'PSN - Possible SN'
		self.assertEqual(tns_values.find_id('at_types', 'PSN - Possible SN'), '1')
		self.assertIsNone(tns_values.find_id('instruments', 'JWST'))  # NIRCam, NIRSpec, ...: ambiguous
		self.assertIsNone(tns_values.find_id('groups', 'No such group'))
		self.assertIsNone(tns_values.find_id('groups', ''))

	def test_label_and_choices(self):
		self.assertEqual(tns_values.label('groups', 170), 'TSST_COSMOS_3D')
		self.assertIsNone(tns_values.label('groups', '999999'))
		self.assertIsNone(tns_values.label('groups', None))
		labels = [text for _, text in tns_values.choices('archives')]
		self.assertEqual(labels, ['DSS', 'Other', 'SDSS'])

	def test_dump_sorts_by_numeric_id_and_round_trips(self):
		data = {'units': {'10': 'b', '2': 'a'}, 'archives': {'0': 'Other'}}
		text = tns_values.dump(data, '2026-10-20', 'test')
		loaded = json.loads(text)
		self.assertEqual(loaded['data'], data)
		self.assertEqual(list(loaded['data']), ['archives', 'units'])
		self.assertEqual(list(loaded['data']['units']), ['2', '10'])

	def test_committed_snapshot_is_in_dump_format(self):
		"""So `sync_tns_values` rewrites the file without reordering it."""
		snapshot = tns_values.load()
		with open(tns_values.SNAPSHOT) as f:
			self.assertEqual(f.read(), tns_values.dump(snapshot['data'], snapshot['retrieved'], snapshot['source']))




class TnsDateTests(SimpleTestCase):

	def test_tns_date_is_the_utc_day(self):
		self.assertEqual(tns_report.tns_date(at(2026, 1, 2, 23, 59, 59)), '2026-01-02')
		hawaii = datetime.timezone(datetime.timedelta(hours=-10))
		self.assertEqual(tns_report.tns_date(datetime.datetime(2026, 1, 1, 14, tzinfo=hawaii)), '2026-01-02')
		self.assertEqual(tns_report.tns_date(datetime.datetime(2026, 1, 2, 6)), '2026-01-02')  # naive: UTC


SHARED = {
	'reporting_groupid': '170', 'data_source_groupid': '170', 'reporter': 'A. Reporter, on behalf of a survey.',
	'at_type': '1', 'flux_unitid': '1', 'archiveid': '0', 'archival_remarks': ' Not in the reference image. ',
}


def fields(**overrides):
	f = {
		'transient_id': 42, 'internal_name': 'jwst_cand_1', 'ra': 150.180166667, 'dec': 2.445291667,
		'discovery_date': at(2023, 12, 24, 6),
		'photometry': [
			{'obs_date': at(2023, 12, 24, 6), 'band': 'F115W', 'mag': 26.6, 'mag_err': 0.1, 'instrumentid': '185'},
			{'obs_date': at(2023, 12, 24, 7), 'band': 'F090W', 'mag': 27.94, 'mag_err': 0.312, 'instrumentid': '185'},
		],
		'host_name': 'COSMOS2020 1234', 'host_redshift': 0.51234, 'host_redshift_source': tns_report.HOST_SPEC_Z,
		'remarks': '  Bright.  ',
	}
	f.update(overrides)
	return f


class AtReportEntryTests(SimpleTestCase):
	"""The pure builder: fields + batch values -> one TNS at_report entry."""

	def test_full_entry(self):
		self.assertEqual(tns_report.at_report_entry(fields(), SHARED), {
			'ra': {'value': '10:00:43.24'},
			'dec': {'value': '+02:26:43.05'},
			'reporting_groupid': '170',
			'data_source_groupid': '170',
			'reporter': 'A. Reporter, on behalf of a survey.',
			'discovery_datetime': '2023-12-24',
			'at_type': '1',
			'internal_name': 'jwst_cand_1',
			'internal_ids': {'tsst_id': '42'},
			'host_name': 'COSMOS2020 1234',
			'host_redshift': '0.5123',
			'remarks': 'Bright.',
			'non_detection': {'archiveid': '0', 'archival_remarks': 'Not in the reference image.'},
			'photometry': {
				'0': {'obsdate': '2023-12-24', 'flux': '26.60', 'flux_error': '0.10', 'flux_unitid': '1',
				      'filterid': '102', 'instrumentid': '185'},
				'1': {'obsdate': '2023-12-24', 'flux': '27.94', 'flux_error': '0.31', 'flux_unitid': '1',
				      'filterid': '0', 'instrumentid': '185', 'comments': 'Filter is JWST-NIRCam-F090W.'},
			},
		})
		self.assertEqual(tns_report.problems(tns_report.at_report_entry(fields(), SHARED)), {})

	def test_optional_values_are_left_out(self):
		entry = tns_report.at_report_entry(fields(host_name='', host_redshift=None, remarks=' '), SHARED)
		for key in ('host_name', 'host_redshift', 'remarks'):
			self.assertNotIn(key, entry)
		point = dict(fields()['photometry'][0], mag_err=None)
		entry = tns_report.at_report_entry(fields(photometry=[point]), SHARED)
		self.assertNotIn('flux_error', entry['photometry']['0'])

	def test_redshift_precision_follows_its_source(self):
		"""A photo-z to 2 decimals; a spec-z to 4 (more digits read as spectroscopic)."""
		entry = tns_report.at_report_entry(fields(host_redshift=1.2468, host_redshift_source=tns_report.HOST_PHOTO_Z), SHARED)
		self.assertEqual(entry['host_redshift'], '1.25')
		for source in (tns_report.TRANSIENT_SPEC_Z, tns_report.HOST_SPEC_Z):
			entry = tns_report.at_report_entry(fields(host_redshift=0.51, host_redshift_source=source), SHARED)
			self.assertEqual(entry['host_redshift'], '0.5100')

	def test_a_new_batch_must_be_filled_in(self):
		"""default_shared leaves the per-survey values empty: the reporter supplies them."""
		shared = tns_report.default_shared()
		self.assertEqual((shared['at_type'], shared['flux_unitid'], shared['archiveid']), ('1', '1', '0'))
		entry = tns_report.at_report_entry(fields(), shared)
		self.assertEqual(tns_report.problems(entry), {
			'reporting_groupid': 'required',
			'data_source_groupid': 'required',
			'reporter': 'required',
			'non_detection.archival_remarks': 'required',
		})

	def test_problems_names_what_tns_would_reject(self):
		point = dict(fields()['photometry'][0], instrumentid=None)
		entry = tns_report.at_report_entry(fields(discovery_date=None, photometry=[point], remarks='x' * 513), SHARED)
		self.assertEqual(tns_report.problems(entry), {
			'discovery_datetime': 'required',
			'remarks': 'at most 512 characters',
			'photometry.0.instrumentid': 'required',
		})
		entry = tns_report.at_report_entry(fields(photometry=[]), SHARED)
		self.assertEqual(tns_report.problems(entry),
		                 {'photometry': 'at least the discovery point is required (no point at S/N >= 5)'})

	def test_problems_too_much_photometry_and_missing_magnitude(self):
		points = [fields()['photometry'][0]] * 11
		points[3] = dict(points[3], mag=None)
		problems = tns_report.problems(tns_report.at_report_entry(fields(photometry=points), SHARED))
		self.assertEqual(problems, {'photometry': 'TNS takes at most 10 points, not 11', 'photometry.3.flux': 'required'})

	def test_bulk_report_numbers_the_entries(self):
		self.assertEqual(tns_report.bulk_report([{'a': 1}, {'b': 2}]), {'at_report': {'0': {'a': 1}, '1': {'b': 2}}})
		with self.assertRaises(ValueError):
			tns_report.bulk_report([])
		with self.assertRaises(ValueError):
			tns_report.bulk_report([{}] * (tns_report.MAX_ENTRIES + 1))



class TransientFieldsTests(TestCase):
	"""Prefilled values from stored photometry, host and comments."""

	ZP = 23.9  # uJy

	@classmethod
	def setUpTestData(cls):
		cls.user = User.objects.create_user('tns_tester', password='pw')
		cls.audit = dict(created_by=cls.user, modified_by=cls.user)
		status = TransientStatus.objects.create(name='Candidate', **cls.audit)
		cls.group = ObservationGroup.objects.create(name='JWST', **cls.audit)
		observatory = Observatory.objects.create(name='JWST', utc_offset=0, tz_name='UTC', **cls.audit)
		telescope = Telescope.objects.create(name='JWST', observatory=observatory, latitude=0.0, longitude=0.0,
		                                     elevation=0.0, **cls.audit)
		cls.nircam = Instrument.objects.create(name='NIRCam', telescope=telescope, **cls.audit)
		cls.bands = {name: PhotometricBand.objects.create(name=name, instrument=cls.nircam, **cls.audit)
		             for name in ('F090W', 'F150W', 'F200W', 'F444W')}
		cls.superseded = DataQuality.objects.create(name='Superseded', **cls.audit)
		cls.transient = Transient.objects.create(name='jwst_cand_1', ra=150.18, dec=2.44, status=status,
		                                         obs_group=cls.group, **cls.audit)
		cls.photometry = TransientPhotometry.objects.create(transient=cls.transient, instrument=cls.nircam,
		                                                    obs_group=cls.group, **cls.audit)

	def point(self, band, day, flux, flux_err, superseded=False, photometry=None):
		"""A point `day` days into 2026, stored as candidate ingest stores it: a detection gets a mag
		from its flux, an upper limit (flux None) gets none."""
		mag = mag_err = None
		if flux is not None and flux > 0:
			mag = self.ZP - 2.5 * math.log10(flux)
			mag_err = 2.5 * math.log10(1 + flux_err / flux)
		p = TransientPhotData.objects.create(
			photometry=photometry or self.photometry, band=self.bands[band],
			obs_date=at(2026, 1, 1) + datetime.timedelta(days=day),
			flux=flux, flux_err=flux_err, flux_zero_point=self.ZP, mag=mag, mag_err=mag_err, **self.audit)
		if superseded:
			p.data_quality.add(self.superseded)
		return p

	def test_discovery_is_preselected_and_detections_are_offered(self):
		self.point('F200W', 0, None, 0.01)  # an upper limit: not offered
		early = self.point('F200W', 10, 0.04, 0.01)  # S/N 4: a detection, below the discovery threshold
		discovery = self.point('F444W', 20, 0.08, 0.01)  # S/N 8: the discovery
		self.point('F150W', 20.3, 0.02, 0.01)  # S/N 2: not a detection
		self.point('F090W', 20.5, 0.09, 0.01, superseded=True)
		later = self.point('F090W', 20.6, 0.05, 0.01)

		f = tns_report.transient_fields(self.transient)
		self.assertEqual(f['discovery_date'], discovery.obs_date)
		self.assertEqual([p['id'] for p in f['photometry']], [discovery.pk])
		self.assertEqual([p['id'] for p in f['detections']], [early.pk, discovery.pk, later.pk])
		first = f['photometry'][0]
		self.assertEqual((first['band'], first['instrumentid']), ('F444W', '185'))
		self.assertAlmostEqual(first['mag'], self.ZP - 2.5 * math.log10(0.08))
		self.assertAlmostEqual(first['snr'], 8.0)
		shared = dict(tns_report.default_shared(), reporting_groupid='170', data_source_groupid='170',
		              reporter='A. Reporter', archival_remarks='Not in the reference.')
		self.assertEqual(tns_report.problems(tns_report.at_report_entry(f, shared)), {})

	def test_discovery_is_the_strongest_detection_of_the_first_day(self):
		"""JWST filters of one visit share the day: the highest S/N one is the discovery, even when
		another band crossed the threshold first."""
		self.point('F200W', 20, 0.06, 0.01)  # S/N 6, first over the threshold
		strongest = self.point('F444W', 20.2, 0.12, 0.01)  # S/N 12, same UTC day
		self.point('F150W', 21.1, 0.30, 0.01)  # S/N 30, the next day: not the discovery
		f = tns_report.transient_fields(self.transient)
		self.assertEqual([p['id'] for p in f['photometry']], [strongest.pk])
		self.assertEqual(f['discovery_date'], strongest.obs_date)

	def test_superseded_points_are_ignored(self):
		self.point('F200W', 5, 0.09, 0.01, superseded=True)
		current = self.point('F200W', 6, 0.06, 0.01)
		f = tns_report.transient_fields(self.transient)
		self.assertEqual(f['discovery_date'], current.obs_date)
		self.assertEqual([p['id'] for p in f['detections']], [current.pk])

	def test_no_point_reaches_the_threshold(self):
		self.point('F200W', 5, 0.04, 0.01)
		f = tns_report.transient_fields(self.transient)
		self.assertEqual((f['discovery_date'], f['photometry'], len(f['detections'])), (None, [], 1))

	def test_an_instrument_tns_does_not_list_has_no_id(self):
		telescope = Telescope.objects.create(name='Backyard', observatory=self.nircam.telescope.observatory,
		                                     latitude=0.0, longitude=0.0, elevation=0.0, **self.audit)
		camera = Instrument.objects.create(name='Webcam', telescope=telescope, **self.audit)
		photometry = TransientPhotometry.objects.create(transient=self.transient, instrument=camera,
		                                                obs_group=self.group, **self.audit)
		self.point('F200W', 5, 0.09, 0.01, photometry=photometry)
		self.assertIsNone(tns_report.transient_fields(self.transient)['photometry'][0]['instrumentid'])

	def test_redshift_prefers_transient_spec_z_then_host_spec_z_then_host_photo_z(self):
		host = Host.objects.create(name=' COSMOS2020 1234 ', ra=150.18, dec=2.44, photo_z=0.6, **self.audit)
		t = self.transient
		t.host = host
		self.assertEqual(tns_report.host_redshift(t), (0.6, 'host photo-z'))
		host.redshift = 0.55
		self.assertEqual(tns_report.host_redshift(t), (0.55, 'host spec-z'))
		t.redshift = 0.51
		self.assertEqual(tns_report.host_redshift(t), (0.51, 'transient spec-z'))
		f = tns_report.transient_fields(t)
		self.assertEqual((f['host_name'], f['host_redshift'], f['host_redshift_source']),
		                 ('COSMOS2020 1234', 0.51, 'transient spec-z'))
		t.redshift = host.redshift = host.photo_z = -99.0  # catalog sentinels
		self.assertEqual(tns_report.host_redshift(t), (None, None))

	def test_identity_and_no_remarks(self):
		"""Our comments judge whether a candidate is real; they are not TNS remarks."""
		Log.objects.create(transient=self.transient, comment='quality_flag: 2; notes: looks real', **self.audit)
		f = tns_report.transient_fields(self.transient)
		self.assertEqual((f['transient_id'], f['internal_name'], f['ra'], f['dec'], f['remarks']),
		                 (self.transient.pk, 'jwst_cand_1', 150.18, 2.44, ''))
