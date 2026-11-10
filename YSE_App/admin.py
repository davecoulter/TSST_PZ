from django.contrib import admin
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


@admin.register(ObservationGroup)
class ObservationGroupAdmin(admin.ModelAdmin):
	form = ObservationGroupForm
	list_display = ('name', 'tns_reporting_group_id', 'tns_data_source_group_id')
	fieldsets = (
		(None, {'fields': ('name',)}),
		('TNS reports (#52)', {
			'fields': ('tns_reporting_group_id', 'tns_data_source_group_id'),
			'description': 'The TNS groups a report of this group\'s transients starts with. Leave a field '
			               'empty and the report form asks for it.'}),
	)

	def save_model(self, request, obj, form, change):
		if not change:
			obj.created_by = request.user
		obj.modified_by = request.user
		super().save_model(request, obj, form, change)


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
