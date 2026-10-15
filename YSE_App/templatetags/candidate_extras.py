"""Template helpers for candidate stamps and navigation (#27)."""
from django import template
from django.templatetags.static import static

from ..candidate_ingest import CANDIDATE, find_by_name
from ..models import Transient, TransientStatus

register = template.Library()

# Where the regular pages expect locally stored stamp files.
LOCAL_STAMP_DIR = 'YSE_App/images/stamps/'


def _is_url(value):
    value = (value or '').strip().lower()
    return value.startswith(('http://', 'https://', '/'))


@register.filter(name='is_url')
def is_url(value):
    """True for an absolute URL or path (e.g. a websniff stamp from #23)."""
    return _is_url(value)


@register.filter(name='stamp_src')
def stamp_src(value):
    """Image source for a stamp field: an absolute URL is used as is (the
    viewer's browser loads it from that server); anything else is a file name
    under the local stamp folder, as the pages have always built it."""
    if not value:
        return ''
    if _is_url(value):
        return value.strip()
    return static(LOCAL_STAMP_DIR + value)


@register.simple_tag
def archived_count():
    """Number of archived transients, for the sidebar."""
    from ..dashboard_sets import archived_count as _count
    return _count()


@register.simple_tag
def candidate_count():
    """Number of transients with status Candidate, for the sidebar."""
    status = find_by_name(TransientStatus, CANDIDATE)
    if status is None:
        return 0
    return Transient.objects.filter(status=status).count()
