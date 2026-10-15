"""What the dashboard grids contain (#40), in one place so the dashboard, the summary view and the
Archived page agree.

Status is the lifecycle: Candidate (triage, shown on /candidates/), then New and the working statuses,
then Archived (kept, out of the way, on /archived/). A transient is always somewhere: a tag box, the
Needs review grid (no transient-kind tag yet), the candidate list, or the Archived page.
"""
from .candidate_ingest import CANDIDATE, find_by_name
from .models import Transient, TransientStatus, TransientTag

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


def archived():
    status = _status(ARCHIVED)
    return Transient.objects.filter(status=status).order_by('-disc_date') if status else Transient.objects.none()


def archived_count():
    return archived().count()
