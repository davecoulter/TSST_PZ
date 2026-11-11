from django.contrib import admin, messages
from django import forms

# Register your models here.
from YSE_App.models import *

class QueryModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.__unicode__

class QueryModelForm(forms.ModelForm):
	query = QueryModelChoiceField(Query.objects.all())
	
	class Meta:
		model = UserQuery
		fields = ('created_by','modified_by','user')
		
@admin.register(UserQuery)
class UserQueryAdmin(admin.ModelAdmin):
	form = QueryModelForm
	
def _tns_group_choices():
	"""The TNS groups of the values snapshot (#52), read when the form is built, not at import."""
	from YSE_App import tns_values
	return [('', '---------')] + [(i, '%s (%s)' % (label, i)) for i, label in tns_values.choices('groups')]


class ObservationGroupForm(forms.ModelForm):
	"""The TNS group fields as dropdowns of TNS's groups; the TNS id is what is stored."""
	tns_reporting_group_id = forms.ChoiceField(choices=_tns_group_choices, required=False, label='TNS reporting group')
	tns_data_source_group_id = forms.ChoiceField(choices=_tns_group_choices, required=False,
	                                             label='TNS data source group')

	class Meta:
		model = ObservationGroup
		fields = ('name', 'tns_reporting_group_id', 'tns_data_source_group_id')

	def _clean_optional(self, name):
		value = (self.cleaned_data.get(name) or '').strip()
		return value or None  # empty is NULL: the report form then asks for it

	def clean_tns_reporting_group_id(self):
		return self._clean_optional('tns_reporting_group_id')

	def clean_tns_data_source_group_id(self):
		return self._clean_optional('tns_data_source_group_id')


class AuditedAdmin(admin.ModelAdmin):
	"""Fills BaseModel's created_by / modified_by with the admin user."""

	def save_model(self, request, obj, form, change):
		if not change:
			obj.created_by = request.user
		obj.modified_by = request.user
		super().save_model(request, obj, form, change)


@admin.register(ObservationGroup)
class ObservationGroupAdmin(AuditedAdmin):
	form = ObservationGroupForm
	list_display = ('name', 'tns_reporting_group_id', 'tns_data_source_group_id')
	fieldsets = (
		(None, {'fields': ('name',)}),
		('TNS reports (#52)', {
			'fields': ('tns_reporting_group_id', 'tns_data_source_group_id'),
			'description': 'The TNS groups a report of this group\'s transients starts with. Leave a field '
			               'empty and the report form asks for it.'}),
	)


@admin.register(TNSBot)
class TNSBotAdmin(AuditedAdmin):
	"""The bots TNS reports go out as (#52, amendment 28). The API key is not here: it is in settings.ini,
	in this deployment's [tns_sandbox] or [tns_production] section, as "<TNS id> = <key>"."""
	list_display = ('name', 'tns_id', 'active', 'has_key')
	fields = ('name', 'tns_id', 'description', 'active')

	@admin.display(boolean=True, description='Key in settings.ini')
	def has_key(self, bot):
		from YSE_App import tns_client
		return tns_client.has_key(bot)


admin.site.register(TransientStatus)
admin.site.register(FollowupStatus)
admin.site.register(TaskStatus)
admin.site.register(AntaresClassification)
admin.site.register(InternalSurvey)
admin.site.register(SEDType)
admin.site.register(HostMorphology)
admin.site.register(Phase)
admin.site.register(TransientClass)
admin.site.register(Observatory)
admin.site.register(OnCallDate)
admin.site.register(YSEOnCallDate)
admin.site.register(Telescope)
admin.site.register(Instrument)
admin.site.register(ToOResource)
admin.site.register(ClassicalResource)
admin.site.register(QueuedResource)
admin.site.register(ClassicalObservingDate)
admin.site.register(InstrumentConfig)
admin.site.register(ConfigElement)
admin.site.register(PhotometricBand)
admin.site.register(PrincipalInvestigator)
admin.site.register(Profile)
admin.site.register(UserTelescopeToFollow)
#admin.site.register(UserQuery)
admin.site.register(Host)
@admin.register(Transient)
class TransientAdmin(admin.ModelAdmin):
	# The detail pages' "Edit in admin" popup (#29) opens this form. Raw ID widgets keep it from
	# rendering every host and spectrum in a dropdown.
	raw_id_fields = ('host', 'best_spectrum')
	search_fields = ('name', 'iau_name')

	def get_readonly_fields(self, request, obj=None):
		"""The IAU name is read-only while a TNS report of the transient is in flight (#52, amendment 2)."""
		from YSE_App import tns_attempts
		fields = tuple(super().get_readonly_fields(request, obj))
		return fields + ('iau_name',) if tns_attempts.in_flight(obj) else fields

	def change_view(self, request, object_id, form_url='', extra_context=None):
		from YSE_App import tns_attempts
		if tns_attempts.in_flight(self.get_object(request, object_id)):
			messages.warning(request, 'The IAU name cannot be edited now: a TNS report of this transient is in flight. '
			                          'It is set when TNS answers, or editable again if the report is abandoned.')
		return super().change_view(request, object_id, form_url, extra_context)


@admin.register(TNSReportAttempt)
class TNSReportAttemptAdmin(admin.ModelAdmin):
	"""TNS report attempts (#52): a record, so read-only; superusers can abandon a pending or unknown one
	(amendments 3, 29), which lets its transient be reported again."""
	list_display = ('transient', 'status', 'report_id', 'bot', 'target', 'created_by', 'created_date', 'last_checked')
	list_filter = ('status', 'target', 'bot')
	search_fields = ('transient__name', 'report_id', 'iau_name', 'batch')
	actions = ('abandon',)

	def get_readonly_fields(self, request, obj=None):
		return [f.name for f in self.model._meta.fields]

	def has_add_permission(self, request):
		return False

	def has_delete_permission(self, request, obj=None):
		return False

	def get_actions(self, request):
		actions = super().get_actions(request)
		if not request.user.is_superuser:
			actions.pop('abandon', None)
		return actions

	@admin.action(description='Abandon the selected pending or unknown attempts (their transients can be reported again)')
	def abandon(self, request, queryset):
		from YSE_App import tns_attempts
		if not request.user.is_superuser:
			return
		n = tns_attempts.abandon(list(queryset), request.user)
		self.message_user(request, '%d attempt%s abandoned.' % (n, '' if n == 1 else 's'))

#admin.site.register(SimpleTransientSpecRequest)
admin.site.register(TransientFollowup)
admin.site.register(HostFollowup)
admin.site.register(TransientObservationTask)
admin.site.register(HostObservationTask)
admin.site.register(TransientSpectrum)
admin.site.register(HostSpectrum)
admin.site.register(TransientPhotometry)
admin.site.register(HostPhotometry)
admin.site.register(InformationSource)
admin.site.register(TransientWebResource)
admin.site.register(HostWebResource)
admin.site.register(AlternateTransientNames)
admin.site.register(TransientSpecData)
admin.site.register(HostSpecData)
admin.site.register(TransientPhotData)
admin.site.register(HostPhotData)
admin.site.register(TransientImage)
admin.site.register(TransientDiffImage)
admin.site.register(ClassicalNightType)
admin.site.register(WebAppColor)
admin.site.register(Unit)
admin.site.register(DataQuality)
admin.site.register(HostImage)
admin.site.register(HostSED)
admin.site.register(Log)
admin.site.register(TransientTag)
admin.site.register(TagKind)
admin.site.register(HostCatalog)
admin.site.register(GWCandidate)
admin.site.register(GWCandidateImage)
admin.site.register(SurveyField)
admin.site.register(SurveyFieldMSB)
admin.site.register(SurveyObservation)
admin.site.register(CanvasFOV)
