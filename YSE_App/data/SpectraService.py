from YSE_App.models import *
from django.db.models import Q
from YSE_App.data import TransientService

# Who may see which spectrum is decided in TransientService (#86); these keep their old names.

def GetAuthorizedTransientSpectrum_ByUser(user, includeBadData=True):
    return TransientService.authorized_data(_GetTransientSpectrum(includeBadData, Q()), user)

def GetAuthorizedTransientSpectrum_ByUser_ByTransient(user, transient_id, includeBadData=True):

    allowed_spec_by_group = GetAuthorizedTransientSpectrum_ByUser(user, includeBadData)
    transient_query = Q(transient=transient_id)
    allowed_spec_by_group_by_transient = allowed_spec_by_group.filter(transient_query).distinct()

    return allowed_spec_by_group_by_transient

def GetAuthorizedHostSpectrum_ByUser(user, includeBadData=True):
    return TransientService.authorized_data(_GetHostSpectrum(includeBadData, Q()), user)

def GetAuthorizedHostSpectrum_ByUser_ByHost(user, host_id, includeBadData=True):
    allowed_spec_by_group = GetAuthorizedHostSpectrum_ByUser(user, includeBadData)
    host_query = Q(host=host_id)
    allowed_spec_by_group_by_host = allowed_spec_by_group.filter(host_query).distinct()

    return allowed_spec_by_group_by_host

def GetAuthorizedTransientSpecData_ByUser(user, includeBadData=True):
    allowed_spec = GetAuthorizedTransientSpectrum_ByUser(user, includeBadData)
    spec_ids = allowed_spec.values('id')
    allowed_spec_data_query = Q(spectrum__id__in=spec_ids)
    allowed_spec_data = TransientSpecData.objects.filter(allowed_spec_data_query)

    return allowed_spec_data

def GetAuthorizedHostSpecData_ByUser(user, includeBadData=True):
    allowed_spec = GetAuthorizedHostSpectrum_ByUser(user, includeBadData)
    spec_ids = allowed_spec.values('id')
    allowed_spec_data_query = Q(spectrum__id__in=spec_ids)
    allowed_spec_data = HostSpecData.objects.filter(allowed_spec_data_query)

    return allowed_spec_data

def GetAuthorizedTransientSpecData_BySpectrum(user, spectrum_id, includeBadData=True):
    # First check if they're allowed to access...
    allowed_spec = GetAuthorizedTransientSpectrum_ByUser(user, includeBadData)
    if allowed_spec:
        allowed_spec = allowed_spec.filter(pk=spectrum_id)

    spec_data = None
    if allowed_spec:
        #... then get the data according to the dq flag preference
        spec_data = TransientSpecData.objects.filter(spectrum__id=spectrum_id)

    return spec_data

def GetAuthorizedHostSpecData_BySpectrum(user, spectrum_id, includeBadData=True):
    # First check if they're allowed to access...
    allowed_spec = GetAuthorizedHostSpectrum_ByUser(user, includeBadData)
    if allowed_spec:
        allowed_spec = allowed_spec.filter(pk=spectrum_id)

    spec_data = None
    if allowed_spec:
        #... then get the data according to the dq flag preference
        spec_data = HostSpecData.objects.filter(spectrum__id=spectrum_id)

    return spec_data


# This are private methods. Don't invoke them outside of this module!
def _GetTransientSpectrum(includeBadData,filter):
    if includeBadData:
        return TransientSpectrum.objects.filter(filter)
    else:
        return TransientSpectrum.objects.exclude(data_quality__isnull=False).filter(filter)

def _GetHostSpectrum(includeBadData, filter):
    if includeBadData:
        return HostSpectrum.objects.filter(filter)
    else:
        return HostSpectrum.objects.exclude(data_quality__isnull=False).filter(filter)