from django.db import models
from YSE_App.models.base import *
from YSE_App.models.transient_models import *

class Tag(BaseModel):
    class Meta:
        abstract = True

    ### Entity relationships ###
    # Optional
    color = models.ForeignKey(WebAppColor, on_delete=models.CASCADE, null=True, blank=True)

    ### Properties ###
    # Required
    name = models.CharField(max_length=256)
    
class TagKind(BaseModel):
    """What a tag is for: Transient tags group transients; Candidate tags annotate
    candidates (sorting, grouping, searching) before they are transients."""
    name = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.name

class TransientTag(Tag):
    # NULL is read as "Transient": tags created before kinds existed.
    kind = models.ForeignKey(TagKind, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return "Name: %s" % self.name
