"""Who may see which transient, host, photometry and spectrum (#86). The one home of the rule.

Groups are Django auth groups. The reserved 'Public' group means every logged-in user; no group means
superusers only. Superusers see everything; nobody else bypasses the rule.

A user has one of three levels of access to a transient:
  FULL        a superuser, or the transient is in 'Public' or in one of the user's groups;
  TNS_OBJECT  not FULL, but the transient has an IAU name: TNS shows it to anyone, so its TNS facts
              are visible (not our notes, tags, follow-ups, or data outside its own groups);
  None        no access at all: it must not show up anywhere for this user.

Photometry and spectra follow their own groups, and also need their transient (or host) to be
visible, or a 'Public' point would give a hidden transient away. A host is visible if a transient
linked to it is visible, or if no transient is linked to it (a catalog galaxy).

Group checks are subqueries on the M2M table rather than joins, so no row is duplicated and no
distinct() is needed: the querysets stay safe to count, annotate and order.
"""
from django.db.models import Q

from YSE_App.models import Host, Transient
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


def find_visible_transient(user, slug, queryset=None):
    """The transient a URL points to (by slug, alias or name, as find_transient), if `user` may see
    it; otherwise None, the same as for a transient that doesn't exist, so a 404 can't tell them apart."""
    return find_transient(slug, visible_transients(user, queryset))


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
