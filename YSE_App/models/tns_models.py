from django.db import models

from YSE_App.models.base import BaseModel


class TNSBot(BaseModel):
	"""
	A TNS bot that reports go out as (#52, plan 052 amendment 28). A report uses one bot; the
	reporter picks it on the details page.

	Attributes:
		tns_id (PositiveIntegerField): the bot's TNS id. It names the bot's API key in settings.ini:
			[tns_sandbox] or [tns_production], "<tns_id> = <key>". The key is never stored here.
		name (CharField): the bot's name exactly as on TNS; every request carries it, with the id,
			in its User-Agent header.
		description (TextField): what the bot is for, e.g. the survey it reports for.
		active (BooleanField): offered on the details page.

	Not exposed through the API: this mirrors accounts kept on TNS.
	"""
	tns_id = models.PositiveIntegerField(unique=True, help_text="The bot's TNS id; it names its API key in settings.ini")
	name = models.CharField(max_length=64, help_text='Exactly as on TNS')
	description = models.TextField(blank=True, default='')
	active = models.BooleanField(default=True, help_text='Offered on the TNS report page')

	class Meta:
		ordering = ('name',)

	def __str__(self):
		return '%s (%d)' % (self.name, self.tns_id)


class TNSReportAttempt(BaseModel):
	"""
	One transient in one submission to TNS (#52, plan 052 amendments 3, 4 and 29). The rows of one
	submission share a `batch`. The state lives here, not in the page: an attempt is saved as pending,
	with what will be sent, before TNS is called, and TNS's report id the moment it answers, so a crash
	or a closed tab loses nothing.

	Attributes:
		transient, bot: what was reported, and as which bot.
		batch (UUIDField): the submission it belongs to; its results page is /tns/report/<batch>/.
		target, base_url: the TNS it went to ('sandbox' or 'production'), and its address.
		report_id (CharField): TNS's id for the submission; empty until TNS returns it.
		status: pending (also "unknown" while it has no report id), reported, name_differs, failed,
			abandoned. Pending or unknown blocks a new report of the transient; the others do not.
		payload (TextField): this transient's at_report entry as sent, JSON. Never the API key.
		response (TextField): TNS's latest reply for the submission, JSON.
		message (TextField): TNS's message for this transient, or why it failed.
		iau_name (CharField): the name TNS gave or matched. objname_separation: arcsec, for a match.
		last_checked, check_after: when TNS was last asked for the outcome; the earliest the next ask.

	Not exposed through the API (amendment 5).
	"""
	PENDING, REPORTED, NAME_DIFFERS, FAILED, ABANDONED = 'pending', 'reported', 'name_differs', 'failed', 'abandoned'
	STATUSES = ((PENDING, 'pending'), (REPORTED, 'reported'), (NAME_DIFFERS, 'reported, name differs'),
	            (FAILED, 'failed'), (ABANDONED, 'abandoned'))

	transient = models.ForeignKey('YSE_App.Transient', on_delete=models.CASCADE, related_name='tns_attempts')
	bot = models.ForeignKey(TNSBot, on_delete=models.PROTECT, related_name='attempts')
	batch = models.UUIDField(db_index=True)
	target = models.CharField(max_length=16)
	base_url = models.CharField(max_length=200)
	report_id = models.CharField(max_length=32, blank=True, default='')
	status = models.CharField(max_length=16, choices=STATUSES, default=PENDING, db_index=True)
	payload = models.TextField()
	response = models.TextField(blank=True, default='')
	message = models.TextField(blank=True, default='')
	iau_name = models.CharField(max_length=64, blank=True, default='')
	objname_separation = models.FloatField(null=True, blank=True)
	last_checked = models.DateTimeField(null=True, blank=True)
	check_after = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ('-created_date', 'id')

	@property
	def unknown(self):
		"""Pending with no report id: TNS may or may not have the submission."""
		return self.status == self.PENDING and not self.report_id

	def __str__(self):
		return '%s to %s TNS: %s' % (self.transient_id, self.target, self.status)


class TNSValue(models.Model):
	"""
	One of TNS's enumerated values (#52, plan 052 amendment 20): a group, AT type, filter, instrument,
	unit, archive, ... as TNS's /api/get/values lists them. A mirror of TNS, refreshed by
	`tns_values.sync` ("Refresh from TNS", `manage.py sync_tns_values`); seeded from the 2025-06-18
	snapshot by migration 0015. Pages read it, never TNS.

	Attributes:
		kind (CharField): TNS's table name: 'groups', 'at_types', 'filters', 'instruments', ...
		tns_id (CharField): the id, as TNS sends it (a string).
		label (CharField): TNS's label; a sync updates it when TNS renames the value.
		listed (BooleanField): TNS listed it at the last sync. A value TNS drops is kept, unlisted:
			dropdowns leave it out, and a report using it is flagged.
		last_seen (DateTimeField): the last sync (or the snapshot) that listed it.

	Not exposed through the API: it mirrors TNS.
	"""
	kind = models.CharField(max_length=32)
	tns_id = models.CharField(max_length=16)
	label = models.CharField(max_length=255)
	listed = models.BooleanField(default=True)
	last_seen = models.DateTimeField(null=True, blank=True)

	class Meta:
		unique_together = (('kind', 'tns_id'),)

	def __str__(self):
		return '%s %s: %s' % (self.kind, self.tns_id, self.label)


class TNSValueSync(BaseModel):
	"""
	One refresh of TNSValue from TNS (#52): who ran it, as which bot, and what changed. The latest one
	spaces refreshes out (tns_values.REFRESH_GAP) and dates the values ("TNS values as of ...").

	Attributes:
		bot: the bot whose key the request used.
		ok (BooleanField): whether TNS answered; a failed refresh still counts toward the gap.
		summary (TextField): what changed (values added, relabelled, unlisted; obs groups created,
			linked, skipped), as JSON, or why it failed.
	"""
	bot = models.ForeignKey(TNSBot, on_delete=models.PROTECT, related_name='value_syncs')
	ok = models.BooleanField(default=False)
	summary = models.TextField(blank=True, default='')

	class Meta:
		ordering = ('-created_date',)
