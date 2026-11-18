from django.db import models
from django.forms import ModelForm
from django import forms
from YSE_App.models import *
from YSE_App import view_utils
from django.utils import timezone
from datetime import timedelta
from YSE_App.queries.yse_python_queries import python_query_reg
from django.contrib.auth.models import AnonymousUser, Group
from YSE_App.data import ObservingResourceService, TransientService


class UserForm:
    """A form built for one user (#86 part 3b): pass user=request.user (access.UserFormMixin does, for
    the form views). Each form narrows its fields in narrow(user) to what that user may write, using the
    rule in TransientService, so the same filter decides what's offered and what's accepted. Without a
    user, those fields offer nothing."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user if user is not None else AnonymousUser()
        self.narrow(self.user)

    def narrow(self, user):
        pass


def groups_field():
    """A required `groups` field, as checkboxes; narrow_groups fills it in for the user."""
    return forms.ModelMultipleChoiceField(queryset=Group.objects.none(), widget=forms.CheckboxSelectMultiple,
                                          error_messages={'required': 'Choose at least one group.'})


def narrow_groups(form, user, allow_public=False):
    """Offer the groups `user` may set ('Public' too where allowed: comments), their own ticked."""
    form.fields['groups'].queryset = TransientService.settable_groups(user, allow_public).order_by('name')
    form.fields['groups'].initial = list(TransientService.own_data_groups(user).values_list('pk', flat=True))

class TransientForm(ModelForm):
    class Meta:
        model = Transient
        fields = [
            'status',
            'obs_group',
            'non_detect_band',
            'best_spec_class',
            'best_spectrum',
            'host',
            'abs_mag_peak_band',
            'host',
            'name',
            'ra',
            'dec',
            'disc_date',
            'candidate_hosts',
            'redshift',
            'redshift_err',
            'redshift_source',
            'non_detect_date',
            'non_detect_limit',
            'mw_ebv',
            'abs_mag_peak',
            'abs_mag_peak_date',
            'postage_stamp_file']

class TransientFollowupForm(UserForm, ModelForm):
    # Nothing here may query the database: this module is imported when the URLs load (#22).
    # The defaults that need a query are filled in narrow(), once per form instance.
    status = forms.ModelChoiceField(FollowupStatus.objects.all())
    classical_resource = forms.ModelChoiceField(
        queryset=ClassicalResource.objects.none(),
        required=False)
    valid_start = forms.DateTimeField()
    valid_stop = forms.DateTimeField()
    comment = forms.CharField(required=False)
    groups = groups_field()

    def narrow(self, user):
        # #86: curators, on transients they curate, with only their groups' resources (#91)
        self.fields['transient'].queryset = TransientService.editable_transients(user)
        self.fields['transient'].required = True
        current = timezone.now() - timedelta(days=1)
        self.fields['too_resource'].queryset = ObservingResourceService.GetAuthorizedToOResource_ByUser(
            user).filter(end_date_valid__gt=current).order_by('telescope__name')
        self.fields['queued_resource'].queryset = ObservingResourceService.GetAuthorizedQueuedResource_ByUser(
            user).filter(end_date_valid__gt=current).order_by('telescope__name')
        narrow_groups(self, user)
        requested = FollowupStatus.objects.filter(name='Requested').first()
        if requested is not None:
            self.fields['status'].initial = requested
            # a field built with an initial value has no blank choice; this keeps that rendering
            self.fields['status'].empty_label = None
        # classical resources that have not ended more than a day ago, soonest ending first
        qs = ObservingResourceService.GetAuthorizedClassicalResource_ByUser(user).filter(
            end_date_valid__gt=current).order_by('end_date_valid').select_related()
        self.fields['classical_resource'].queryset = qs
        first = qs.first()
        if first is not None:
            self.fields['classical_resource'].initial = first
            self.fields['valid_start'].initial = first.begin_date_valid
            self.fields['valid_stop'].initial = first.end_date_valid

    class Meta:
        model = TransientFollowup
        fields = [
            'status',
            'too_resource',
            'classical_resource',
            'queued_resource',
            'comment',
            'valid_start',
            'valid_stop',
            'spec_priority',
            'phot_priority',
            'offset_star_ra',
            'offset_star_dec',
            'offset_north',
            'offset_east',
            'transient',
            'groups']

class ResourceGroupsForm(UserForm):
    """An observing resource needs at least one data group: the curator's own, never 'Public' (#86, #91).
    Each form declares `groups = groups_field()` itself: a plain mixin's fields aren't collected."""

    def narrow(self, user):
        narrow_groups(self, user)


class ClassicalResourceForm(ResourceGroupsForm, ModelForm):

    observing_date = forms.DateTimeField()
    groups = groups_field()

    class Meta:
        model = ClassicalResource
        fields = [
            'telescope',
            'principal_investigator',
            'groups']

class ToOResourceForm(ResourceGroupsForm, ModelForm):
    groups = groups_field()

    awarded_too_hours = forms.FloatField(initial=0)
    used_too_hours = forms.FloatField(initial=0)
    awarded_too_triggers = forms.FloatField(initial=0)
    used_too_triggers = forms.FloatField(initial=0)

    class Meta:
        model = ToOResource
        fields = [
            'telescope',
            'principal_investigator',
            'begin_date_valid',
            'end_date_valid',
            'awarded_too_hours',
            'used_too_hours',
            'awarded_too_triggers',
            'used_too_triggers',
            'groups']

class SurveyFieldForm(ModelForm):

    valid_start = forms.DateTimeField()
    valid_stop = forms.DateTimeField()
    coord = forms.CharField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # With GPC instruments in the database the field is limited to them and optional. With none,
        # the model's own required field (every instrument) stays, as it always has. Decided per form
        # instance, not at import (#22).
        qs = Instrument.objects.filter(name__startswith='GPC').select_related()
        if qs.exists():
            self.fields['instrument'] = forms.ModelChoiceField(
                queryset=qs,
                initial=qs.first(),
                required=False)

    class Meta:
        model = SurveyField
        fields = ['field_id',
                  'cadence',
                  'ztf_field_id',
                  'instrument']

class SurveyObsForm(ModelForm):

    survey_obs_date = forms.DateTimeField()

    # the choices come from the database, so they are set in __init__ (#22)
    ztf_field_id = forms.MultipleChoiceField(
        choices=[],
        required=True)

    instrument = forms.MultipleChoiceField(
        choices=[['GPC1','GPC1'],['GPC2','GPC2']],
        initial=['GPC1','GPC1'],
        required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(i['ztf_field_id'], i['ztf_field_id']) for i in SurveyField.objects.filter(~Q(obs_group__name='ZTF')).values('ztf_field_id').distinct().order_by('ztf_field_id')]
        self.fields['ztf_field_id'].choices = choices
        if choices:
            self.fields['ztf_field_id'].initial = choices[0]

    class Meta:
        model = SurveyObservation
        fields = ['survey_obs_date','ztf_field_id','priority','instrument']


class OncallForm(ModelForm):

    valid_start = forms.DateTimeField()
    valid_stop = forms.DateTimeField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # the user field exists only when there are YSE group users, as before; decided per form
        # instance, not at import (#22)
        qs = User.objects.all().filter(groups__name='YSE').filter(~Q(username='admin')).order_by('username')
        if qs.exists():
            self.fields['user'] = forms.ModelChoiceField(
                queryset=qs,
                initial=qs.first(),
                required=False)

    class Meta:
        model = YSEOnCallDate
        fields = [] #['field_id',
        #		  'cadence',
        #		  'ztf_field_id',
        #		  'instrument']



class TransientCommentForm(UserForm, ModelForm):
    """Anyone who can see the transient may comment, tagged with their own data groups and/or 'Public'."""
    groups = groups_field()

    def narrow(self, user):
        self.fields['transient'].queryset = TransientService.visible_transients(user)
        self.fields['transient'].required = True  # the model allows none; a comment from this form is on one
        narrow_groups(self, user, allow_public=True)

    class Meta:
        model = Log
        fields = [
            'comment',
            'transient',
            'groups']


class TransientObservationTaskForm(UserForm, ModelForm):
    """An observation task, on a follow-up of a transient the user curates."""

    def narrow(self, user):
        self.fields['followup'].queryset = TransientService.writable(TransientFollowup.objects.all(), user)

    class Meta:
        model = TransientObservationTask
        fields = [
            'status',
            'instrument_config',
            'exposure_time',
            'number_of_exposures',
            'desired_obs_date',
            'actual_obs_date',
            'description',
            'followup']

class QueryModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.__str__

class AddDashboardQueryForm(ModelForm):
    query = QueryModelChoiceField(Query.objects.all(),required=False)
    query_names = [('', '---------')] + [(q,q) for i,q in enumerate(python_query_reg.all.keys())]
    python_query = forms.ChoiceField(choices=query_names,required=False)
    #import pdb; pdb.set_trace()

    class Meta:
        model = UserQuery
        fields = [
            'query','python_query']

class RemoveDashboardQueryForm(ModelForm):
    #query = QueryModelChoiceField(Query.objects.all())

    class Meta:
        model = UserQuery
        fields = ['id']

class AddFollowupNoticeForm(ModelForm):
    telescope = QueryModelChoiceField(Telescope.objects.all())
    #import pdb; pdb.set_trace()
    class Meta:
        model = UserTelescopeToFollow
        fields = ['telescope']
    #		'id']

class RemoveFollowupNoticeForm(ModelForm):
    telescope = QueryModelChoiceField(Telescope.objects.all())

    class Meta:
        model = UserTelescopeToFollow
        fields = [
            'id']


class SpectrumUploadForm(ModelForm):
    filename = forms.FileField()
    obs_date = forms.DateTimeField(input_formats=['%Y-%m-%dT%H:%M'])
    obs_group = forms.ModelChoiceField(
        ObservationGroup.objects.filter(Q(name='SSS') | Q(name='Foundation') |
                                        Q(name='TESS') | Q(name='YSE') |
                                        Q(name='UCSC') |
                                        Q(name='Other')))
    data_quality = forms.ModelChoiceField(
        DataQuality.objects.filter(Q(name='Quicklook')),required=False)

    # the group names come from the database, so the choices are set in __init__ (#22)
    permissions = forms.MultipleChoiceField(
            choices=[],
            required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['permissions'].choices = [(i['name'], i['name']) for i in Group.objects.all().values('name').distinct().order_by('name')]

    spec_instruments = [
        'SED-Machine','P200-TSPEC','SPRAT',
        'LFC','DBSP','MIKE','LDSS-3',
        'aade - MagE','aade - Boller & Chivens',
        'WFC3','STIS','IRS','B&C-Asi-1.22m',
        'IMACS','lay - LDSS-2','ALFOSC',
        'Mod-spec','B&C-duPont',
        'WFCCD','V-grism','UV-grism',
        'X-Shooter','EFOSC-2.2','Sofi',
        'EFOSC2-NTT','EMMI','EFOSC2-3.6',
        'OSIRIS','FLOYDS-N','FLOYDS-S','NIRC2',
        'NIRSPEC','NIRES','KCWI','ESI',
        'DEIMOS','OSIRIS','MOSFIRE','LRIS','LRS2',
        'HIRES','GMOS','Goodman','KAST','WiFeS','WFCCD','DIS','MMT Binospec','SpeX','UVES',
        'GNIRS','FLAMINGOS-2','DOLORES']
    instrument = forms.ModelChoiceField(Instrument.objects.filter(Q(name__in=spec_instruments)))
    #import pdb; pdb.set_trace()
    class Meta:
        model = TransientSpectrum
        fields = ('transient','ra',
                  'dec','spec_phase')#,'obs_group','instrument')

class AutomatedSpectrumRequest(UserForm, ModelForm):

    spec_instruments = ['FLOYDS-N','FLOYDS-S','Goodman']
    instrument = forms.ModelChoiceField(Instrument.objects.filter(Q(name__in=spec_instruments)))
    exp_time = forms.IntegerField(initial=1800) # 1800s seems like a reasonable default
    spectrum_valid_start = forms.DateTimeField()
    spectrum_valid_stop = forms.DateTimeField()

    def narrow(self, user):
        self.fields['transient'].queryset = TransientService.editable_transients(user)

    class Meta:
        model = TransientFollowup
        fields =('transient',)
  
