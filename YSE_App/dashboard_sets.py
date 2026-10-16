"""What the dashboard grids contain (#40), in one place so the dashboard, the summary view and the
Archived page agree.

Status is the lifecycle: Candidate (triage, shown on /candidates/), then New and the working statuses,
then Archived (kept, out of the way, on /archived/). A transient is always somewhere: a tag box, the
Needs review grid (no transient-kind tag yet), the candidate list, or the Archived page.
"""
import django_tables2 as tables
from django.db.models import Exists, OuterRef, Q

from .candidate_ingest import CANDIDATE, DEFAULT_SOURCE, find_by_name
from .models import Transient, TransientStatus, TransientTag, TransientWebResource
from .table_utils import TransientTable

ARCHIVED = 'Archived'


def _status(name):
    return find_by_name(TransientStatus, name)


def hidden_statuses():
    """Statuses left out of the main dashboard's boxes: Candidate and Archived."""
    return [s for s in (_status(CANDIDATE), _status(ARCHIVED)) if s is not None]


def transient_tags():
    """Tags that get a main-dashboard box: transient-kind tags (a tag with no kind predates kinds
    and is a transient tag). Candidate-kind tags are annotations for the candidate pages."""
    return TransientTag.objects.exclude(kind__name__iexact='Candidate')


def needs_review():
    """Transients sitting in no tag box: not a candidate, not archived, no transient-kind tag."""
    return (Transient.objects.exclude(status__in=hidden_statuses())
            .exclude(tags__in=transient_tags())
            .order_by('-disc_date'))


def new_candidates():
    """Candidates (status Candidate) still carrying the candidate-kind `New` tag: the backlog to triage."""
    status = _status(CANDIDATE)
    if status is None:
        return Transient.objects.none()
    return Transient.objects.filter(status=status, tags__kind__name__iexact='Candidate',
                                    tags__name__iexact='New').distinct()


def archived():
    """Archived transients, each marked when it came from the candidate pipeline."""
    status = _status(ARCHIVED)
    if status is None:
        return Transient.objects.none()
    from_pipeline = TransientWebResource.objects.filter(
        transient=OuterRef('pk'), information_source__name__iexact=DEFAULT_SOURCE)
    return (Transient.objects.filter(status=status)
            .annotate(has_candidate_data=Exists(from_pipeline)).order_by('-disc_date'))


def archive_tags():
    """Tags that make an archive grid: every tag except the New call to action, which belongs to the
    candidate backlog."""
    return TransientTag.objects.exclude(Q(kind__name__iexact='Candidate') & Q(name__iexact='New'))


class ArchivedTable(TransientTable):
    """The dashboard table with a badge, on rows from the candidate pipeline, linking to the candidate page."""
    name_string = tables.TemplateColumn(
        "<a href=\"{% url 'transient_detail' record.slug %}\">{{ record.name }}</a>"
        "{% if record.has_candidate_data %} <a class=\"label label-warning\" title=\"candidate page\" "
        "href=\"{% url 'candidate_detail' record.slug %}\">candidate</a>{% endif %}",
        verbose_name='Name', orderable=True, order_by='name')


def archived_count():
    return archived().count()
