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


@register.filter(name='basename')
def basename(value):
    """The file name of a path or URL: the full path is not shown on the page."""
    return (value or '').rstrip('/').rsplit('/', 1)[-1]


@register.simple_tag(takes_context=True)
def archived_count(context):
    """Number of archived transients the viewer may see (#86), for the sidebar."""
    from ..dashboard_sets import archived_count as _count
    return _count(context['request'].user)


@register.simple_tag(takes_context=True)
def candidate_count(context):
    """Number of NEW candidates (still tagged New), for the sidebar badge; classifying them clears it."""
    from ..dashboard_sets import new_candidates
    from ..data import TransientService
    return TransientService.visible_transients(context['request'].user, new_candidates()).count()
