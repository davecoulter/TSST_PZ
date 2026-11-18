from django.http import HttpResponse, HttpResponseRedirect, Http404, JsonResponse
from rest_framework import serializers, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework import generics
from rest_framework import viewsets
from YSE_App.common import custom_viewsets
from rest_framework.reverse import reverse

from .models import *
from .serializers import *
from .data import PhotometryService, SpectraService, ObservingResourceService
from .access import IsSuperuser, ReadableQuerysetMixin

from django_filters.rest_framework import DjangoFilterBackend,filters
import django_filters

### `Additional Info` ViewSets ###
class TransientWebResourceViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = TransientWebResource.objects.all()
    serializer_class = TransientWebResourceSerializer

class HostWebResourceViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = HostWebResource.objects.all()
    serializer_class = HostWebResourceSerializer

### `HostCatalog` and `TagKind` ViewSets (read-only lookups) ###
class HostCatalogViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = HostCatalog.objects.all()
    serializer_class = HostCatalogSerializer

class TagKindViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TagKind.objects.all()
    serializer_class = TagKindSerializer

### `Enum` ViewSets ###
# Only exposing GET
class TransientStatusViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TransientStatus.objects.all()
    serializer_class = TransientStatusSerializer

class FollowupStatusViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = FollowupStatus.objects.all()
    serializer_class = FollowupStatusSerializer

### `SurveyField` Filter Set ###
class SurveyFieldFilter(django_filters.FilterSet):
    field_id = django_filters.Filter(field_name="field_id")
    obs_group = django_filters.Filter(field_name="obs_group__name")
    instrument = django_filters.Filter(field_name="instrument__name")
    class Meta:
        model = SurveyField
        fields = ()

### `SurveyFieldMSB` Filter Set ###
class SurveyFieldMSBFilter(django_filters.FilterSet):
    name = django_filters.Filter(field_name="name")
    active = django_filters.Filter(field_name="active")
    instrument = django_filters.Filter(field_name='survey_fields__instrument__name')
    class Meta:
        model = SurveyFieldMSB
        fields = ('name','active')

### `SurveyField ViewSets` ###
class SurveyFieldViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    permission_classes = (IsSuperuser,)  # #86: obsolete YSE table
    queryset = SurveyField.objects.all()
    serializer_class = SurveyFieldSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = SurveyFieldFilter


class SurveyFieldMSBViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet): #viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsSuperuser,)  # #86: obsolete YSE table
    queryset = SurveyFieldMSB.objects.all()
    serializer_class = SurveyFieldMSBSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = SurveyFieldMSBFilter


### `Transient` Filter Set ###
class SurveyObsFilter(django_filters.FilterSet):
    status_in = django_filters.BaseInFilter(field_name="status__name")#, lookup_expr='in')
    obs_mjd_gte = django_filters.Filter(field_name="obs_mjd", lookup_expr='gte')
    obs_mjd_lte = django_filters.Filter(field_name="obs_mjd", lookup_expr='lte')
    mjd_requested_gte = django_filters.Filter(field_name="mjd_requested", lookup_expr='gte')
    mjd_requested_lte = django_filters.Filter(field_name="mjd_requested", lookup_expr='lte')
    survey_field = django_filters.BaseInFilter(field_name="survey_field__field_id")
    obs_group = django_filters.BaseInFilter(field_name="survey_field__obs_group__name")
    ra_gt = django_filters.Filter(field_name="survey_field__ra_cen", lookup_expr='gt')
    ra_lt = django_filters.Filter(field_name="survey_field__ra_cen", lookup_expr='lt')
    dec_gt = django_filters.Filter(field_name="survey_field__dec_cen", lookup_expr='gt')
    dec_lt = django_filters.Filter(field_name="survey_field__dec_cen", lookup_expr='lt')
    instrument = django_filters.Filter(field_name="survey_field__instrument__name")
    
    class Meta:
        model = SurveyObservation
        fields = ()


class SurveyObservationViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    permission_classes = (IsSuperuser,)  # #86: obsolete YSE table
    queryset = SurveyObservation.objects.all()
    serializer_class = SurveyObservationSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = SurveyObsFilter

class TaskStatusViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TaskStatus.objects.all()
    serializer_class = TaskStatusSerializer

class AntaresClassificationViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AntaresClassification.objects.all()
    serializer_class = AntaresClassificationSerializer

class InternalSurveyViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = InternalSurvey.objects.all()
    serializer_class = InternalSurveySerializer

### `ObservationGroup` Filter Set ###
class ObservationGroupFilter(django_filters.FilterSet):
    name = django_filters.Filter(field_name="name")

    class Meta:
        model = ObservationGroup
        fields = ()
    
class ObservationGroupViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ObservationGroup.objects.all()
    serializer_class = ObservationGroupSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = ObservationGroupFilter
    
class SEDTypeViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = SEDType.objects.all()
    serializer_class = SEDTypeSerializer

class HostMorphologyViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = HostMorphology.objects.all()
    serializer_class = HostMorphologySerializer

class PhaseViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Phase.objects.all()
    serializer_class = PhaseSerializer

class TransientClassViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TransientClass.objects.all()
    serializer_class = TransientClassSerializer
    lookup_field = "id"

class ClassicalNightTypeViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ClassicalNightType.objects.all()
    serializer_class = ClassicalNightTypeSerializer

class WebAppColorViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = WebAppColor.objects.all()
    serializer_class = WebAppColorSerializer

class UnitViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer

class DataQualityViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
        queryset = DataQuality.objects.all()
        serializer_class = DataQualitySerializer

class InformationSourceViewSet(ReadableQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = InformationSource.objects.all()
    serializer_class = InformationSourceSerializer

### `Followup` ViewSets ###
#class SimpleTransientSpecRequestViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
#	queryset = SimpleTransientSpecRequest.objects.all()
#	serializer_class = SimpleTransientSpecRequestSerializer
#	permission_classes = (permissions.IsAuthenticated,)

class TransientFollowupViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = TransientFollowup.objects.all()
    serializer_class = TransientFollowupSerializer

class HostFollowupViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = HostFollowup.objects.all()
    serializer_class = HostFollowupSerializer

### `Host` ViewSets ###
class HostViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    lookup_field = "id"

class HostSEDViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = HostSED.objects.all()
    serializer_class = HostSEDSerializer

### `Instrument` Filter Set ###
class InstrumentFilter(django_filters.FilterSet):
    name = django_filters.Filter(field_name="name")
    class Meta:
        model = Instrument
        fields = ()
    
### `Instrument` ViewSets ###
class InstrumentViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateDestroyViewSet):
    queryset = Instrument.objects.all()
    serializer_class = InstrumentSerializer
    lookup_field = "id"
    filter_backends = (DjangoFilterBackend,)
    filter_class = InstrumentFilter

    
class InstrumentConfigViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = InstrumentConfig.objects.all()
    serializer_class = InstrumentConfigSerializer

class ConfigElementViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = ConfigElement.objects.all()
    serializer_class = ConfigElementSerializer

### `Log` ViewSets ###
class LogViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    write_rule = 'comment'  # #86: anyone who can see a transient may comment; its author changes it
    queryset = Log.objects.all()
    serializer_class = LogSerializer

### `Observation Task` ViewSets ###
class TransientObservationTaskViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = TransientObservationTask.objects.all()
    serializer_class = TransientObservationTaskSerializer

class HostObservationTaskViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = HostObservationTask.objects.all()
    serializer_class = HostObservationTaskSerializer

### `Observatory` ViewSets ###
class ObservatoryViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateDestroyViewSet):
    queryset = Observatory.objects.all()
    serializer_class = ObservatorySerializer

### `On Call Date` ViewSets ###
class OnCallDateViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    permission_classes = (IsSuperuser,)  # #86: obsolete YSE table
    queryset = OnCallDate.objects.all()
    serializer_class = OnCallDateSerializer

class YSEOnCallDateViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    permission_classes = (IsSuperuser,)  # #86: obsolete YSE table
    queryset = YSEOnCallDate.objects.all()
    serializer_class = YSEOnCallDateSerializer

### `Phot` ViewSets ###
class TransientPhotometryViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = TransientPhotometrySerializer
    lookup_field = "id"

    def get_queryset(self):
        allowed_phot = PhotometryService.GetAuthorizedTransientPhotometry_ByUser(self.request.user)
        return allowed_phot

class HostPhotometryViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = HostPhotometrySerializer
    lookup_field = "id"

    def get_queryset(self):
        allowed_phot = PhotometryService.GetAuthorizedHostPhotometry_ByUser(self.request.user)
        return allowed_phot

class TransientPhotDataViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = TransientPhotDataSerializer

    def get_queryset(self):
        allowed_phot_data = PhotometryService.GetAuthorizedTransientPhotData_ByUser(self.request.user)
        return allowed_phot_data


class HostPhotDataViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = HostPhotDataSerializer

    def get_queryset(self):
        allowed_phot_data = PhotometryService.GetAuthorizedHostPhotData_ByUser(self.request.user)
        return allowed_phot_data



class TransientImageViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = TransientImage.objects.all()
    serializer_class = TransientImageSerializer

class HostImageViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = HostImage.objects.all()
    serializer_class = HostImageSerializer

### `Photometric Band` ViewSets ###
class PhotometricBandViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateDestroyViewSet):
    queryset = PhotometricBand.objects.all()
    serializer_class = PhotometricBandSerializer
    lookup_field = "id"

### `Principal Investigator` ViewSets ###
class PrincipalInvestigatorViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    write_rule = 'vocabulary'
    queryset = PrincipalInvestigator.objects.all()
    serializer_class = PrincipalInvestigatorSerializer

### `Profile` ViewSets ###
class ProfileViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    owner_field, write_rule = 'user', 'own'  # each user's own row only
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer

### `UserQuery` ViewSets ###
class UserQueryViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    owner_field, write_rule = 'user', 'own'
    queryset = UserQuery.objects.all()
    serializer_class = UserQuerySerializer

### `UserTelescopeToFollow` ViewSets ###
class UserTelescopeToFollowViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    owner_field, write_rule = 'profile__user', 'own'
    queryset = UserTelescopeToFollow.objects.all()
    serializer_class = UserTelescopeToFollowSerializer


### `Spectra` ViewSets ###
class TransientSpectrumViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = TransientSpectrumSerializer
    lookup_field = "id"

    def get_queryset(self):
        allowed_spec = SpectraService.GetAuthorizedTransientSpectrum_ByUser(self.request.user)
        return allowed_spec

class HostSpectrumViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = HostSpectrumSerializer
    lookup_field = "id"

    def get_queryset(self):
        allowed_spec = SpectraService.GetAuthorizedHostSpectrum_ByUser(self.request.user)
        return allowed_spec

class TransientSpecDataViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = TransientSpecDataSerializer

    def get_queryset(self):
        allowed_spec_data = SpectraService.GetAuthorizedTransientSpecData_ByUser(self.request.user)
        return allowed_spec_data

class HostSpecDataViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = HostSpecDataSerializer

    def get_queryset(self):
        allowed_spec_data = SpectraService.GetAuthorizedHostSpecData_ByUser(self.request.user)
        return allowed_spec_data

### `Telescope Resource` ViewSets ###
class ToOResourceViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = ToOResourceSerializer

    def get_queryset(self):
        allowed_resource = ObservingResourceService.GetAuthorizedToOResource_ByUser(self.request.user)
        return allowed_resource

class QueuedResourceViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = QueuedResourceSerializer

    def get_queryset(self):
        allowed_resource = ObservingResourceService.GetAuthorizedQueuedResource_ByUser(self.request.user)
        return allowed_resource

### `ClassicalResource` Filter Set ###
class ClassicalResourceFilter(django_filters.FilterSet):
    telescope_name = django_filters.Filter(field_name="telescope__name")

    class Meta:
        model = ClassicalResource
        fields = ()

class ClassicalResourceViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = ClassicalResourceSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = ClassicalResourceFilter

    def get_queryset(self):
        allowed_resource = ObservingResourceService.GetAuthorizedClassicalResource_ByUser(self.request.user)
        return allowed_resource

class ClassicalObservingDateViewSet(custom_viewsets.ListCreateRetrieveUpdateViewSet):
    serializer_class = ClassicalObservingDateSerializer

    def get_queryset(self):
        allowed_resource = ObservingResourceService.GetAuthorizedClassicalObservingDate_ByUser(self.request.user)
        return allowed_resource

### `Telescope` ViewSets ###
class TelescopeViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateDestroyViewSet):
    queryset = Telescope.objects.all()
    serializer_class = TelescopeSerializer

### `Transient` Filter Set ###
class TransientFilter(django_filters.FilterSet):
    created_date_gte = django_filters.DateTimeFilter(field_name="created_date", lookup_expr='gte')
    modified_date_gte = django_filters.DateTimeFilter(field_name="modified_date", lookup_expr='gte')
    status_in = django_filters.BaseInFilter(field_name="status__name")#, lookup_expr='in')
    ra_gte = django_filters.Filter(field_name="ra", lookup_expr='gte')
    ra_lte = django_filters.Filter(field_name="ra", lookup_expr='lte')
    dec_gte = django_filters.Filter(field_name="dec", lookup_expr='gte')
    dec_lte = django_filters.Filter(field_name="dec", lookup_expr='lte')
    tag_in = django_filters.BaseInFilter(field_name="tags__name")
    name = django_filters.Filter(field_name="name")
    # #86: ?group_in=TSST,Public; within the transients the user may see anyway
    group_in = django_filters.BaseInFilter(field_name="groups__name", distinct=True)

    class Meta:
        model = Transient
        fields = ('created_date','modified_date')

### `Transient` ViewSets ###
class TransientViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateDestroyViewSet):
    queryset = Transient.objects.all()
    serializer_class = TransientSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = TransientFilter
    #filter_fields = ('status','created_date','modified_date','mw_ebv','status__name')

class AlternateTransientNamesViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = AlternateTransientNames.objects.all()
    serializer_class = AlternateTransientNamesSerializer

### `User` ViewSets ###
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsSuperuser,)  # #92: never a user list, or user details, for anyone else
    queryset = User.objects.all()
    serializer_class = UserSerializer

### `Group` ViewSets ###
class GroupViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsSuperuser,)  # #92
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

### `Tag` ViewSets ###
class TransientTagViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateDestroyViewSet):
    write_rule = 'vocabulary'  # #86: anyone adds a tag; its creator changes it; superusers delete
    queryset = TransientTag.objects.all()
    serializer_class = TransientTagSerializer

### `GW` ViewSets ###
class GWCandidateViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = GWCandidate.objects.all()
    serializer_class = GWCandidateSerializer

class GWCandidateImageViewSet(ReadableQuerysetMixin, custom_viewsets.ListCreateRetrieveUpdateViewSet):
    queryset = GWCandidateImage.objects.all()
    serializer_class = GWCandidateImageSerializer
