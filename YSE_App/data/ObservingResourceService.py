"""The observing resources (telescope time) a user may see and use (#86, #91): those in their groups.
The rule itself is TransientService.readable_resources; a resource with no group is superusers' only
(it used to be everyone's)."""
from YSE_App.models import ClassicalObservingDate, ClassicalResource, QueuedResource, ToOResource
from YSE_App.data import TransientService


def GetAuthorizedToOResource_ByUser(user):
    return TransientService.readable_resources(user, ToOResource.objects.all())


def GetAuthorizedQueuedResource_ByUser(user):
    return TransientService.readable_resources(user, QueuedResource.objects.all())


def GetAuthorizedClassicalResource_ByUser(user):
    return TransientService.readable_resources(user, ClassicalResource.objects.all())


def GetAuthorizedClassicalObservingDate_ByUser(user):
    return ClassicalObservingDate.objects.filter(resource__in=GetAuthorizedClassicalResource_ByUser(user).values('pk'))
