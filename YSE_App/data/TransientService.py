"""Who may see which transient, host, photometry and spectrum (#86). The one home of the rule.

Groups are Django auth groups. The reserved 'Public' group means every logged-in user; no group means
superusers only. Superusers see everything; nobody else bypasses the rule.

A user has one of three levels of access to a transient:
  FULL        a superuser, or the transient is in 'Public' or in one of the user's groups;
  TNS_OBJECT  not FULL, but the transient has an IAU name: TNS shows it to anyone, so its TNS facts
              are visible (not our notes, tags, follow-ups, or data outside its own groups);
  None        no access at all: it must not show up anywhere for this user.
Writes follow the rule set in the plan (agentic_planning/086-group-visibility/plan.md):
  can_comment  anyone who can see the transient (either level);
  can_edit     curating (status, tags, fields, follow-up, uploads): the curate_transients permission
               ("Transient Curators") and one of the transient's groups other than 'Public', which
               grants reading only; or a superuser;
  can_change   an item someone added (a comment, ...): its author, or a superuser.

Photometry, spectra, comments (Log) and follow-ups follow their own groups, and also need what
they're attached to (a transient, host, ...) to be visible, or a 'Public' point would give a hidden
transient away. A host is visible if a transient linked to it is visible, or if no transient is
linked to it (a catalog galaxy). Static facts about a visible transient (its row, host, tags,
aliases, links) are not restricted further.

Only data groups go on data: a group that grants permissions is a role (e.g. "TNS Reporters").

Group checks are subqueries on the M2M table rather than joins, so no row is duplicated and no
distinct() is needed: the querysets stay safe to count, annotate and order.
"""
from django.contrib.auth.models import Group
from django.db.models import Q

from YSE_App.models import (AlternateTransientNames, GWCandidate, Host, HostFollowup, HostImage, HostObservationTask,
                            HostPhotData, HostPhotometry, HostSpecData, HostSpectrum, HostWebResource, Log, Transient,
                            TransientDiffImage, TransientFollowup, TransientImage, TransientObservationTask,
                            TransientPhotData, TransientPhotometry, TransientSpecData, TransientSpectrum,
                            TransientWebResource)
from YSE_App.transient_names import find_transient

PUBLIC = 'Public'
FULL = 'full'
TNS_OBJECT = 'tns_object'


def in_groups_q(model, user):
    """Rows of `model` (anything with a `groups` M2M to auth Group) tagged 'Public' or with one of
    `user`'s groups. The group rule itself; it ignores superusers, so callers check that first."""
    field = model._meta.get_field('groups')
    tagged = field.remote_field.through.objects.filter(
        Q(**{field.m2m_reverse_field_name() + '__name': PUBLIC}) |
        Q(**{field.m2m_reverse_field_name() + '__in': user.groups.all()}))
    return Q(pk__in=tagged.values(field.m2m_field_name()))


def data_groups():
    """The groups that may be put on data: those granting no permissions. A group that grants
    permissions is a role, and stays one: give a team extra rights through a separate group."""
    return Group.objects.filter(permissions__isnull=True)


def tns_object_q(prefix=''):
    """Transients that are on TNS (an IAU name is set). `prefix` reaches them through a relation."""
    return ~Q(**{prefix + 'iau_name': None}) & ~Q(**{prefix + 'iau_name': ''})


def full_access_transients(user, queryset=None):
    """The transients `user` has FULL access to, out of `queryset` (default: all of them)."""
    transients = Transient.objects.all() if queryset is None else queryset
    if user.is_superuser:
        return transients
    return transients.filter(in_groups_q(Transient, user))


def visible_transients(user, queryset=None):
    """The transients `user` may see at all (FULL or TNS_OBJECT), out of `queryset` (default: all)."""
    transients = Transient.objects.all() if queryset is None else queryset
    if user.is_superuser:
        return transients
    return transients.filter(in_groups_q(Transient, user) | tns_object_q())


def access_level(user, transient):
    """FULL, TNS_OBJECT or None: what `user` may see of one transient."""
    if user.is_superuser or full_access_transients(user, Transient.objects.filter(pk=transient.pk)).exists():
        return FULL
    if transient.iau_name:
        return TNS_OBJECT
    return None


CURATE = 'YSE_App.curate_transients'


def can_edit(user, transient):
    """Whether `user` may curate `transient`: a superuser, or the curator role (role) and one of its
    groups other than 'Public' (scope). The one rule for curating; the template filter, view decorator
    and API permission only call this."""
    if user.is_superuser:
        return True
    if not user.has_perm(CURATE):
        return False
    return transient.groups.exclude(name=PUBLIC).filter(pk__in=user.groups.values('pk')).exists()


def can_comment(user, transient):
    """Whether `user` may comment on `transient`: anyone who can see it. The comment's own groups
    decide who reads it."""
    return access_level(user, transient) is not None


def can_add_tags(user, transient):
    """Whether `user` may add tags to `transient`: anyone who can see it (adding is additive, and tags
    are leaving the main dashboard, #75). Removing a tag is curating (can_edit)."""
    return access_level(user, transient) is not None


def is_transient_linked(model):
    """Whether rows of `model` belong to a transient or host, so the rule set applies to them;
    anything else is a shared table, written only by superusers unless its viewset says otherwise."""
    return model in _TRANSIENT_PATH or model in _HOST_PATH or model is Log


def can_change(user, item):
    """Whether `user` may change or delete an item someone added (a comment, ...): its author, or a
    superuser."""
    return user.is_superuser or (user.is_authenticated and item.created_by_id == user.pk)


def find_visible_transient(user, slug, queryset=None):
    """The transient a URL points to (by slug, alias or name, as find_transient), if `user` may see
    it; otherwise None, the same as for a transient that doesn't exist, so a 404 can't tell them apart."""
    return find_transient(slug, visible_transients(user, queryset))


def filter_query_results(user, rows):
    """The transients a saved query returned (rows whose first column is the transient's name) that
    `user` may see. Only the names are read back from the query's SQL, never its other columns, and the
    result is narrowed by the rule like any other list."""
    names = {row[0] for row in rows}
    return visible_transients(user, Transient.objects.filter(name__in=names))


def filter_by_transient(queryset, user, field='transient', level=FULL):
    """Rows of anything hanging off a transient (comments, follow-ups, images, tags, ...) whose
    transient, reached through `field`, `user` may see at `level` (FULL, or TNS_OBJECT for either)."""
    if user.is_superuser:
        return queryset
    allowed = full_access_transients(user) if level == FULL else visible_transients(user)
    return queryset.filter(**{field + '__in': allowed.values('pk')})


def visible_hosts(user, queryset=None):
    """The hosts `user` may see: linked to a transient they may see, or linked to no transient."""
    hosts = Host.objects.all() if queryset is None else queryset
    if user.is_superuser:
        return hosts
    linked = Transient.objects.filter(host__isnull=False).values('host_id')
    seen = visible_transients(user).filter(host__isnull=False).values('host_id')
    return hosts.filter(Q(pk__in=seen) | ~Q(pk__in=linked))


def authorized_data(queryset, user):
    """The photometry or spectra in `queryset` (Transient/Host Photometry or Spectrum) that `user`
    may see: tagged 'Public' or one of their groups, on a transient or host they may see."""
    if user.is_superuser:
        return queryset
    model = queryset.model
    if hasattr(model, 'transient'):
        owner = Q(transient__in=visible_transients(user).values('pk'))
    else:
        owner = Q(host__in=visible_hosts(user).values('pk'))
    return queryset.filter(in_groups_q(model, user), owner)


# A comment can be attached to any of these; each one that is set must be visible too.
_LOG_TARGETS = {
    'transient': lambda user: visible_transients(user),
    'host': lambda user: visible_hosts(user),
    'transient_photometry': lambda user: authorized_data(TransientPhotometry.objects.all(), user),
    'transient_spectrum': lambda user: authorized_data(TransientSpectrum.objects.all(), user),
    'transient_followup': lambda user: authorized_data(TransientFollowup.objects.all(), user),
    'host_photometry': lambda user: authorized_data(HostPhotometry.objects.all(), user),
    'host_spectrum': lambda user: authorized_data(HostSpectrum.objects.all(), user),
}


def authorized_logs(queryset, user):
    """The comments (Log) in `queryset` that `user` may read: tagged 'Public' or one of their groups,
    and everything they're attached to (of _LOG_TARGETS) visible to them."""
    if user.is_superuser:
        return queryset
    q = in_groups_q(queryset.model, user)
    for field, allowed in _LOG_TARGETS.items():
        q &= Q(**{field: None}) | Q(**{field + '__in': allowed(user).values('pk')})
    return queryset.filter(q)


# --- the API (#86 part 3a): one place that knows how each model reaches its transient or host ---------

# Items with their own groups: readable by the group rule (authorized_data / authorized_logs).
_GROUPED = (TransientPhotometry, TransientSpectrum, TransientFollowup, HostPhotometry, HostSpectrum)

# How a model reaches the transient it belongs to ('' for Transient itself).
_TRANSIENT_PATH = {
    Transient: '', TransientPhotometry: 'transient', TransientSpectrum: 'transient',
    TransientFollowup: 'transient', AlternateTransientNames: 'transient', TransientWebResource: 'transient',
    GWCandidate: 'transient', TransientPhotData: 'photometry__transient', TransientSpecData: 'spectrum__transient',
    TransientImage: 'phot_data__photometry__transient', TransientDiffImage: 'phot_data__photometry__transient',
    TransientObservationTask: 'followup__transient',
}
# Models that hang off a grouped item: readable when that item is.
_PARENT = {
    TransientPhotData: ('photometry', TransientPhotometry), TransientSpecData: ('spectrum', TransientSpectrum),
    TransientImage: ('phot_data__photometry', TransientPhotometry),
    TransientDiffImage: ('phot_data__photometry', TransientPhotometry),
    TransientObservationTask: ('followup', TransientFollowup),
    HostPhotData: ('photometry', HostPhotometry), HostSpecData: ('spectrum', HostSpectrum),
}
# How a model reaches its host ('' for Host itself).
_HOST_PATH = {
    Host: '', HostPhotometry: 'host', HostSpectrum: 'host', HostFollowup: 'host', HostWebResource: 'host',
    HostImage: 'phot_data__photometry__host', HostPhotData: 'photometry__host', HostSpecData: 'spectrum__host',
    HostObservationTask: 'followup__host',
}


def editable_transients(user, queryset=None):
    """The transients `user` may curate (can_edit), out of `queryset` (default: all)."""
    transients = Transient.objects.all() if queryset is None else queryset
    if user.is_superuser:
        return transients
    if not user.has_perm(CURATE):
        return transients.none()
    ours = Transient.groups.through.objects.filter(group__in=user.groups.exclude(name=PUBLIC))
    return transients.filter(pk__in=ours.values('transient'))


def editable_hosts(user, queryset=None):
    """The hosts `user` may curate: a superuser, or a curator who can see them."""
    hosts = Host.objects.all() if queryset is None else queryset
    if user.is_superuser:
        return hosts
    return visible_hosts(user, hosts) if user.has_perm(CURATE) else hosts.none()


def _within(queryset, path, allowed):
    """`queryset` narrowed to rows whose `path` (a relation path, '' for the row itself) is in `allowed`."""
    return queryset.filter(**{(path + '__in') if path else 'pk__in': allowed.values('pk')})


def readable(queryset, user):
    """The rows of `queryset` that `user` may read, for any model the API serves: the one dispatcher the
    API's viewsets call. Grouped items by their groups and target; what hangs off them by them; static
    facts by their transient (either level) or host; anything else (reference tables) unchanged."""
    if user.is_superuser:
        return queryset
    model = queryset.model
    if model is Transient:
        return visible_transients(user, queryset)
    if model is Host:
        return visible_hosts(user, queryset)
    if model is Log:
        return authorized_logs(queryset, user)
    if model in _GROUPED:
        return authorized_data(queryset, user)
    if model in _PARENT:
        path, parent = _PARENT[model]
        return _within(queryset, path, authorized_data(parent.objects.all(), user))
    if model in _TRANSIENT_PATH:
        return _within(queryset, _TRANSIENT_PATH[model], visible_transients(user))
    if model in _HOST_PATH:
        return _within(queryset, _HOST_PATH[model], visible_hosts(user))
    return queryset


def writable(queryset, user, rule='curate'):
    """The rows of `queryset` that `user` may attach a new item to or link from a write: by the
    'comment' rule, what they can see; by the 'curate' rule, what belongs to a transient (or host) they
    may curate and, for grouped items, what they can read. Reference tables are unchanged."""
    if user.is_superuser:
        return queryset
    readable_rows = readable(queryset, user)
    if rule == 'comment':
        return readable_rows
    model = queryset.model
    if model in _TRANSIENT_PATH:
        return _within(readable_rows, _TRANSIENT_PATH[model], editable_transients(user))
    if model in _HOST_PATH:
        return _within(readable_rows, _HOST_PATH[model], editable_hosts(user))
    return readable_rows


def follow(obj, path):
    """The object at the end of a relation path ('photometry__transient'), or None along the way."""
    for attr in filter(None, path.split('__')):
        obj = getattr(obj, attr, None)
        if obj is None:
            return None
    return obj


def transient_of(obj):
    """The transient an object belongs to, or None (hosts, reference tables)."""
    path = _TRANSIENT_PATH.get(type(obj))
    return None if path is None else follow(obj, path)


def host_of(obj):
    """The host an object belongs to, or None."""
    path = _HOST_PATH.get(type(obj))
    return None if path is None else follow(obj, path)
