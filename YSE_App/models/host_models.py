from django.db import models
from YSE_App.models.base import *
from YSE_App.models.enum_models import *
from YSE_App.models.photometric_band_models import *
from YSE_App.common.utilities import *

class HostSED(BaseModel):
	### Entity relationships ###
	# Optional
	sed_type = models.ForeignKey(SEDType, null=True, blank=True, on_delete=models.SET_NULL)

	### Properties ###
	# Optional
	metalicity = models.FloatField(null=True, blank=True)
	metalicity_err = models.FloatField(null=True, blank=True)
	log_SFR = models.FloatField(null=True, blank=True)
	log_SFR_err = models.FloatField(null=True, blank=True)
	log_sSFR = models.FloatField(null=True, blank=True)
	log_sSFR_err = models.FloatField(null=True, blank=True)
	log_mass = models.FloatField(null=True, blank=True)
	log_mass_err = models.FloatField(null=True, blank=True)
	ebv = models.FloatField(null=True, blank=True)
	ebv_err = models.FloatField(null=True, blank=True)
	log_age = models.FloatField(null=True, blank=True)
	log_age_err = models.FloatField(null=True, blank=True)
	redshift = models.FloatField(null=True, blank=True)
	redshift_err = models.FloatField(null=True, blank=True)
	fit_chi2 = models.FloatField(null=True, blank=True)
	fit_n = models.IntegerField(null=True, blank=True)
	fit_plot_file = models.TextField(null=True, blank=True)

	def __str__(self):
		name_str = 'HostSED: '
		try:
			name_str += self.sed_type.name
		except NameError:
			name_str += 'Untyped'
		return name_str

	def natural_key(self):
		return self.__str__

class HostCatalog(BaseModel):
	"""A catalog that hosts come from (JADES, COSMOS, ...), identified by its file name.

	A catalog object ID is only unique within its catalog, so a host from a catalog is
	found by (catalog, catalog_object_id). `nickname` is the short name people use
	(set on the server; the pipeline sends the file name).
	"""
	filename = models.CharField(max_length=255, unique=True)
	nickname = models.CharField(max_length=64, null=True, blank=True)

	def __str__(self):
		return self.nickname or self.filename

class Host(BaseModel):
	### Entity relationships ###
	# Optional
	host_morphology = models.ForeignKey(HostMorphology, null=True, blank=True, on_delete=models.SET_NULL)
	host_sed = models.ForeignKey(HostSED, null=True, blank=True, on_delete=models.SET_NULL)
	band_sextract = models.ForeignKey(PhotometricBand, null=True, blank=True, on_delete=models.SET_NULL)
	best_spec = models.ForeignKey('HostSpectrum', related_name='+', null=True, blank=True, on_delete=models.SET_NULL)

	### Properties ###
	# Required
	ra = models.FloatField()
	dec = models.FloatField()

	# Optional
	name = models.CharField(max_length=64, null=True, blank=True)
	redshift = models.FloatField(null=True, blank=True)
	redshift_err = models.FloatField(null=True, blank=True)
	r_a = models.FloatField(null=True, blank=True)
	r_b = models.FloatField(null=True, blank=True)
	theta = models.FloatField(null=True, blank=True)
	eff_offset = models.FloatField(null=True, blank=True)
	photo_z = models.FloatField(null=True, blank=True)
	photo_z_err = models.FloatField(null=True, blank=True)
	photo_z_internal = models.FloatField(null=True, blank=True)
	photo_z_err_internal = models.FloatField(null=True, blank=True)
	photo_z_PSCNN = models.FloatField(null=True, blank=True)
	photo_z_err_PSCNN = models.FloatField(null=True, blank=True)
	photo_z_source = models.CharField(max_length=64, null=True, blank=True)
	# Catalog identity (one catalog per host for now). The integer column is not called
	# `catalog_id` because Django already uses that name for the foreign key's column.
	catalog = models.ForeignKey(HostCatalog, null=True, blank=True, on_delete=models.PROTECT)
	catalog_object_id = models.BigIntegerField(null=True, blank=True)

	class Meta:
		constraints = [
			# catalog_object_id first, so the foreign key on `catalog` keeps its own index (MySQL would
			# otherwise adopt this one for the foreign key, and the migration could not be reversed)
			models.UniqueConstraint(fields=['catalog_object_id', 'catalog'], name='unique_host_catalog_object'),
		]
	transient_host_rank = models.IntegerField(null=True, blank=True)
	panstarrs_objid = models.BigIntegerField(null=True, blank=True)

	def HostString(self):
		ra_str, dec_str = GetSexigesimalString(self.ra, self.dec)

		if self.name:
			return "Host: %s; (%s, %s)" % (self.name, ra_str, dec_str)
		else:
			return "Host: (%s, %s)" % (ra_str, dec_str)

	def CoordString(self):
		return GetSexigesimalString(self.ra, self.dec)

	def RADecimalString(self):
		return '%.7f'%(self.ra)

	def DecDecimalString(self):
		return '%.7f'%(self.dec)

	def __str__(self):
		return self.HostString()

	def natural_key(self):
		return self.HostString()
