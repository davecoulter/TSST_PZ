from YSE_App.models import *
from django.db.models import Q
from YSE_App.data import TransientService

# Who may see which photometry is decided in TransientService (#86); these keep their old names.

def GetAuthorizedTransientPhotometry_ByUser(user):
    return TransientService.authorized_data(TransientPhotometry.objects.all(), user)

def GetAuthorizedTransientPhotometry_ByUser_ByTransient(user, transient_id):

    allowed_phot_by_group = GetAuthorizedTransientPhotometry_ByUser(user)
    transient_query = Q(transient=transient_id)
    allowed_phot_by_group_by_transient = allowed_phot_by_group.filter(transient_query).distinct()

    return allowed_phot_by_group_by_transient

def GetAuthorizedTransientDiffImages_ByUser(user):
    # difference images and stamps (#23) belong to a photometry point, and follow its photometry
    return TransientDiffImage.objects.filter(
        phot_data__photometry__in=GetAuthorizedTransientPhotometry_ByUser(user).values('pk'))

def GetAuthorizedHostPhotometry_ByUser(user):
    return TransientService.authorized_data(HostPhotometry.objects.all(), user)

def GetAuthorizedHostPhotometry_ByUser_ByHost(user, host_id):
    allowed_phot_by_group = GetAuthorizedHostPhotometry_ByUser(user)
    host_query = Q(host=host_id)
    allowed_phot_by_group_by_host = allowed_phot_by_group.filter(host_query).distinct()

    return allowed_phot_by_group_by_host

def GetAuthorizedTransientPhotData_ByUser(user, includeBadData=True):
    allowed_phot = GetAuthorizedTransientPhotometry_ByUser(user)
    phot_ids = allowed_phot.values('id')
    allowed_phot_data_query = Q(photometry__id__in=phot_ids)
    allowed_phot_data = _GetTransientPhotData(includeBadData, allowed_phot_data_query)

    return allowed_phot_data

def GetAuthorizedTransientPhotData_ByUser_ByTransient(user, transient_id, includeBadData=True):
    allowed_phot = GetAuthorizedTransientPhotometry_ByUser_ByTransient(user, transient_id)
    phot_ids = allowed_phot.values('id')
    allowed_phot_data_query = Q(photometry__id__in=phot_ids)
    allowed_phot_data = _GetTransientPhotData(includeBadData, allowed_phot_data_query)

    return allowed_phot_data

def GetAuthorizedHostPhotData_ByUser(user, includeBadData=True):
    allowed_phot = GetAuthorizedHostPhotometry_ByUser(user)
    phot_ids = allowed_phot.values('id')
    allowed_phot_data_query = Q(photometry__id__in=phot_ids)
    allowed_phot_data = _GetHostPhotData(includeBadData, allowed_phot_data_query)

    return allowed_phot_data

def GetAuthorizedHostPhotData_ByUser_ByHost(user, host_id, includeBadData=True):
    allowed_phot = GetAuthorizedHostPhotometry_ByUser_ByHost(user, host_id)
    phot_ids = allowed_phot.values('id')
    allowed_phot_data_query = Q(photometry__id__in=phot_ids)
    allowed_phot_data = _GetHostPhotData(includeBadData, allowed_phot_data_query)

    return allowed_phot_data

def GetAuthorizedTransientPhotData_ByPhotometry(user, photometry_id, includeBadData=True):
    # First check if they're allowed to access...
    allowed_phot = GetAuthorizedTransientPhotometry_ByUser(user).filter(pk=photometry_id)

    phot_data = None
    if allowed_phot:
        #... then get the data according to the dq flag preference
        query = Q(photometry__id=photometry_id)
        phot_data = _GetTransientPhotData(includeBadData, query)

    return phot_data


# This are private methods. Don't invoke them outside of this module!
def _GetTransientPhotData(includeBadData,filter):
    if includeBadData:
        return TransientPhotData.objects.filter(filter)
    else:
        return TransientPhotData.objects.exclude(data_quality__isnull=False).filter(filter)

def _GetHostPhotData(includeBadData, filter):
    if includeBadData:
        return HostPhotData.objects.filter(filter)
    else:
        return HostPhotData.objects.exclude(data_quality__isnull=False).filter(filter)
