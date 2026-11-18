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
  can_change   an item someone added (a comment, ...): its author, or a superuser;
  can_delete   by reach (review 13): a curator deletes what reaches only things they curate; anything
               site-wide (used outside their reach) is for superusers.
Observing resources (telescope time) follow the group rule too, with no transient: a user sees the
resources in their groups, and a curator in one of a resource's groups curates it.

Photometry, spectra, comments (Log) and follow-ups follow their own groups, and also need what
they're attached to (a transient, host, ...) to be visible, or a 'Public' point would give a hidden
transient away. A host is visible if a transient linked to it is visible, or if no transient is
linked to it (a catalog galaxy). Static facts about a visible transient (its row, host, tags,
aliases, links) are not restricted further.

Only data groups go on data: a group that grants permissions is a role (e.g. "TNS Reporters").

Group checks are subqueries on the M2M table rather than joins, so no row is duplicated and no
distinct() is needed: the querysets stay safe to count, annotate and order.
"""
from django.contrib.auth.models import Group, User
from django.db.models import BooleanField, Exists, OuterRef, Q, Value

from YSE_App.models import (AlternateTransientNames, ClassicalObservingDate, ClassicalResource, GWCandidate, Host,
                            HostFollowup, HostImage, HostObservationTask, HostPhotData, HostPhotometry, HostSpecData,
                            HostSpectrum, HostWebResource, Log, PrincipalInvestigator, QueuedResource, ToOResource,
                            Transient, TransientDiffImage, TransientFollowup, TransientImage, TransientObservationTask,
                            TransientPhotData, TransientPhotometry, TransientSpecData, TransientSpectrum, TransientTag,
                            TransientWebResource, UserQuery, UserTelescopeToFollow)
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


def team_groups_q(model, user):
    """Rows of `model` with one of `user`'s groups other than 'Public': the scope of curating."""
    field = model._meta.get_field('groups')
    tagged = field.remote_field.through.objects.filter(
        **{field.m2m_reverse_field_name() + '__in': user.groups.exclude(name=PUBLIC)})
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


def is_curated(model):
    """Whether rows of `model` belong to a transient, host or observing resource, so curating applies
    to them; anything else is a shared table, written only by superusers unless its viewset says otherwise."""
    return model in _TRANSIENT_PATH or model in _HOST_PATH or model in _RESOURCE_PATH or model is Log


def can_change(user, item):
    """Whether `user` may change an item someone added (a comment, a tag's definition, ...): its author,
    or a superuser. Deleting is can_delete."""
    return user.is_superuser or (user.is_authenticated and item.created_by_id == user.pk)


def settable_groups(user, allow_public=False):
    """The groups `user` may put on an item: only data groups (never a role group); their own, plus
    'Public' where `allow_public` (comments). Superusers: any data group, 'Public' included (releasing)."""
    groups = data_groups()
    if user.is_superuser:
        return groups
    if not user.is_authenticated:
        return groups.none()
    allowed = Q(pk__in=user.groups.values('pk'))
    if allow_public:
        allowed |= Q(name=PUBLIC)
    else:
        allowed &= ~Q(name=PUBLIC)
    return groups.filter(allowed)


def own_data_groups(user):
    """`user`'s own data groups, 'Public' left out: what a form ticks for them to start with."""
    return data_groups().filter(pk__in=user.groups.values('pk')).exclude(name=PUBLIC)


def team_groups(user, transient):
    """The groups something `user` adds to `transient` on their behalf gets (a follow-up requested by
    code, ...): the transient's groups other than 'Public' that are theirs (all of them for a
    superuser). Possibly none, which leaves the item to superusers: never 'Public' by default."""
    groups = transient.groups.exclude(name=PUBLIC).filter(pk__in=data_groups().values('pk'))
    return groups if user.is_superuser else groups.filter(pk__in=user.groups.values('pk'))


def users_who_can_see(log, users=None):
    """The users, out of `users` (default: every active one), who may read comment `log`: the one
    audience for anything that tells people about a comment (email or Slack notifications, #93)."""
    users = User.objects.filter(is_active=True) if users is None else users
    return [u for u in users if authorized_logs(Log.objects.filter(pk=log.pk), u).exists()]


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
# Observing resources (telescope time): grouped, with no transient. How a model reaches its resource.
_RESOURCES = (ToOResource, ClassicalResource, QueuedResource)
_RESOURCE_PATH = {ToOResource: '', ClassicalResource: '', QueuedResource: '', ClassicalObservingDate: 'resource'}
# The follow-up field that uses each kind of resource.
_FOLLOWUP_FIELD = {ToOResource: 'too_resource', ClassicalResource: 'classical_resource',
                   QueuedResource: 'queued_resource'}
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
    return transients.filter(team_groups_q(Transient, user))


def annotate_editable(queryset, user, transient_field='pk'):
    """`queryset` (transients, or rows with a transient at `transient_field`) with `editable`: whether
    `user` may curate that transient (can_edit). One subquery for the whole table, so a dashboard can
    show edit controls only where they work, without a query per row."""
    if user.is_superuser or not user.has_perm(CURATE):
        return queryset.annotate(editable=Value(user.is_superuser, output_field=BooleanField()))
    ours = Transient.groups.through.objects.filter(
        transient=OuterRef(transient_field), group__in=user.groups.exclude(name=PUBLIC))
    return queryset.annotate(editable=Exists(ours))


def readable_resources(user, queryset):
    """The observing resources in `queryset` (ToO, classical or queued) `user` may see and use: those in
    their groups. A resource with no group is superusers' (it used to be everyone's)."""
    if user.is_superuser:
        return queryset
    return queryset.filter(in_groups_q(queryset.model, user))


def editable_resources(user, queryset):
    """The observing resources in `queryset` `user` may curate: a curator in one of their groups."""
    if user.is_superuser:
        return queryset
    if not user.has_perm(CURATE):
        return queryset.none()
    return queryset.filter(team_groups_q(queryset.model, user))


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
    if model in _RESOURCES:
        return readable_resources(user, queryset)
    if model is ClassicalObservingDate:
        return _within(queryset, 'resource', readable_resources(user, ClassicalResource.objects.all()))
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
    if model in _RESOURCES:
        return editable_resources(user, readable_rows)
    if model is ClassicalObservingDate:
        return _within(readable_rows, 'resource', editable_resources(user, ClassicalResource.objects.all()))
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


def resource_of(obj):
    """The observing resource an object is or belongs to, or None."""
    path = _RESOURCE_PATH.get(type(obj))
    return None if path is None else follow(obj, path)


def can_curate(user, obj):
    """Whether `user` may change `obj`, a row that belongs to a transient, host or observing resource
    (is_curated): can_edit on its transient, a curator who can see its host, or a curator in one of its
    resource's groups. The API's object check for the 'curate' rule."""
    if user.is_superuser:
        return True
    transient = transient_of(obj)
    if transient is not None:
        return can_edit(user, transient)
    host = host_of(obj)
    if host is not None:
        return editable_hosts(user).filter(pk=host.pk).exists()
    resource = resource_of(obj)
    if resource is not None:
        return editable_resources(user, type(resource).objects.filter(pk=resource.pk)).exists()
    return False


def _all_groups_ours(item, user):
    """Whether every group on `item` is one of `user`'s own, other than 'Public' (and it has one)."""
    groups = item.groups.all()
    return groups.exists() and not groups.exclude(pk__in=user.groups.exclude(name=PUBLIC).values('pk')).exists()


def _outside(queryset, reach):
    """Whether any row of `queryset` is not in `reach`: something outside the user's reach uses it."""
    return queryset.exclude(pk__in=reach.values('pk')).exists()


def can_delete(user, item):
    """Whether `user` may delete `item`, by reach (plan, review 13): a curator deletes what reaches only
    things they curate; once something outside their reach uses it, it is site-wide, and superusers'.
      follow-ups, tasks, aliases, links, images   a curator of the transient
      photometry and spectra (and their points)   a curator of the transient, if every group on the
                                                  record is theirs ('Public' or another team's: site-wide)
      comments                                    the author
      tags, PIs                                   the creator, while everything using them is theirs to curate
      observing resources                         a curator of the resource, while no follow-up outside
                                                  their reach uses it
      the user's own dashboard pins and subscriptions   the user
      transients, hosts and everything site-wide  superusers only"""
    if user.is_superuser:
        return True
    if not user.is_authenticated:
        return False
    model = type(item)
    if model is Log:
        return can_change(user, item)
    if model is UserQuery:
        return item.user_id == user.pk
    if model is UserTelescopeToFollow:
        return item.profile.user_id == user.pk
    if model is TransientTag:
        return item.created_by_id == user.pk and not _outside(
            Transient.objects.filter(tags=item), editable_transients(user))
    if model is PrincipalInvestigator:
        return item.created_by_id == user.pk and not any(
            _outside(m.objects.filter(principal_investigator=item), editable_resources(user, m.objects.all()))
            for m in _RESOURCES)
    if model in _RESOURCES:
        return can_curate(user, item) and not _outside(
            TransientFollowup.objects.filter(**{_FOLLOWUP_FIELD[model]: item}),
            TransientFollowup.objects.filter(transient__in=editable_transients(user).values('pk')))
    if model is ClassicalObservingDate:
        return can_curate(user, item)
    if model in (TransientPhotometry, TransientSpectrum):
        return can_edit(user, item.transient) and _all_groups_ours(item, user)
    if model is TransientPhotData:
        return can_delete(user, item.photometry)
    if model is TransientSpecData:
        return can_delete(user, item.spectrum)
    if model is Transient or model not in _TRANSIENT_PATH:
        return False
    transient = transient_of(item)
    return transient is not None and can_edit(user, transient)
