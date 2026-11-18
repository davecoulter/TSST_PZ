"""View adapters for the visibility rule (#86). They decide nothing themselves; TransientService does."""
import functools

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse

from YSE_App.data import TransientService
from YSE_App.models import Transient
from YSE_App.transient_names import transient_not_found


def transient_access(level=TransientService.TNS_OBJECT, by='slug', pass_transient=True):
    """Look the view's transient up through the rule, by the URL's `slug` or `transient_id` (a keyword,
    or the first positional argument when a view calls another directly).

    - Not visible to the user (or not there): the not-found page for a slug, a plain 404 for an id;
      the same response either way, so it can't tell the two apart.
    - Visible, but `level` is FULL and the user may not change it (TransientService.can_edit): 403.
    - By slug, an old slug or a name typed in redirects to the current slug (#29), query string kept.
    - pass_transient=True: the view gets the transient as `transient`, in place of `slug`/`transient_id`.
      False: a guard only; the view is called with its own arguments, unchanged.
    Put it under @login_required (on a method, wrap both in django's method_decorator)."""
    def decorate(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            if by in kwargs:
                key, rest, others = kwargs[by], args, {k: v for k, v in kwargs.items() if k != by}
            else:
                key, rest, others = args[0], args[1:], kwargs
            if by == 'slug':
                transient = TransientService.find_visible_transient(request.user, key)
                if transient is None:
                    return transient_not_found(request, key)
                if transient.slug and transient.slug != key:
                    url = reverse(request.resolver_match.view_name, kwargs=dict(others, slug=transient.slug))
                    query = request.META.get('QUERY_STRING')
                    return HttpResponseRedirect(url + ('?' + query if query else ''))
            else:
                transient = TransientService.visible_transients(
                    request.user, Transient.objects.filter(pk=key)).first()
                if transient is None:
                    raise Http404('Transient not found')
            if level == TransientService.FULL and not TransientService.can_edit(request.user, transient):
                raise PermissionDenied
            if pass_transient:
                return view(request, *rest, transient=transient, **others)
            return view(request, *args, **kwargs)
        return wrapper
    return decorate


# --- the API (#86 part 3a): DRF adapters. They decide nothing themselves; TransientService does. -------

from django.contrib.auth.models import Group  # noqa: E402  (kept with the API adapters)
from django.db.models import Q  # noqa: E402
from rest_framework import permissions, serializers  # noqa: E402


class IsSuperuser(permissions.BasePermission):
    """Superusers only. DRF's IsAdminUser checks is_staff, which most users have (#92)."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_superuser)


class RulePermission(permissions.BasePermission):
    """The API's default permission (#86; the plan's rule set and two-axis principle). Reading needs a
    login; the rows were already narrowed by the viewset's queryset (ReadableQuerysetMixin). Deleting
    is for superusers. Writing, by the view's `write_rule`, or by its model when it has none:
      'curate'      rows that belong to a transient or host (the default for those): the curator role,
                    and on an object, can_edit on its transient (or a curator who can see its host).
                    A PATCH that only adds tags to a transient needs only can_add_tags.
      'comment'     anyone may add; an item is changed by its author (can_change).
      'vocabulary'  shared labels (tags, PIs): anyone may add; an item is changed by its creator.
      'own'         the user's own rows only (`owner_field` on the view).
      'site'        every other table (the default for those): superusers only.
    The obsolete YSE tables use IsSuperuser instead, for reads too."""

    @staticmethod
    def rule(view):
        explicit = getattr(view, 'write_rule', None)
        if explicit:
            return explicit
        model = view.get_serializer_class().Meta.model
        return 'curate' if TransientService.is_transient_linked(model) else 'site'

    @staticmethod
    def only_adds_tags(request):
        return request.method == 'PATCH' and set(request.data) <= {'tags'}

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS or user.is_superuser:
            return True
        if request.method == 'DELETE':
            return False
        rule = self.rule(view)
        if rule in ('comment', 'vocabulary', 'own'):
            return True
        if rule == 'curate':
            return user.has_perm(TransientService.CURATE) or self.only_adds_tags(request)
        return False

    def has_object_permission(self, request, view, obj):
        user = request.user
        if request.method in permissions.SAFE_METHODS or user.is_superuser:
            return True
        rule = self.rule(view)
        if rule in ('comment', 'vocabulary'):
            return TransientService.can_change(user, obj)
        if rule == 'own':
            return TransientService.follow(obj, view.owner_field) == user
        if rule != 'curate':
            return False
        transient = TransientService.transient_of(obj)
        if transient is not None:
            if TransientService.can_edit(user, transient):
                return True
            # adding tags is for anyone who can see it; removing them is checked in the serializer
            return isinstance(obj, Transient) and self.only_adds_tags(request) and \
                TransientService.can_add_tags(user, transient)
        host = TransientService.host_of(obj)
        return host is not None and TransientService.editable_hosts(user).filter(pk=host.pk).exists()


class ReadableQuerysetMixin:
    """A viewset whose rows are what the user may read (TransientService.readable), or, for per-user
    tables (`owner_field`), the user's own rows."""
    owner_field = None

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if self.owner_field:
            return queryset if user.is_superuser else queryset.filter(**{self.owner_field: user})
        return TransientService.readable(queryset, user)


class RuleRelatedField(serializers.HyperlinkedRelatedField):
    """A link in a write that must follow the rule set: only objects the user may attach to are found
    (TransientService.writable), so anything else gets the same 'does not exist' error as a missing
    object. rule='comment' on comments, 'curate' (default) elsewhere."""

    def __init__(self, *args, rule='curate', **kwargs):
        self.rule = rule
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get('request')
        if request is None:
            return queryset.none()
        return TransientService.writable(queryset, request.user, self.rule)


def settable_groups(user, allow_public=False):
    """The groups `user` may put on an item: only data groups (never a role group); their own, plus
    'Public' where `allow_public` (comments). Superusers: any data group, 'Public' included (releasing)."""
    groups = TransientService.data_groups()
    if user.is_superuser:
        return groups
    allowed = Q(pk__in=user.groups.values('pk'))
    if allow_public:
        allowed |= Q(name=TransientService.PUBLIC)
    else:
        allowed &= ~Q(name=TransientService.PUBLIC)
    return groups.filter(allowed)


def set_groups(item, groups, user, allow_public=False):
    """Set an item's groups from a write: the user changes only the groups they may set; the item's
    other groups (another team's, or 'Public' set by a release) are kept."""
    kept = item.groups.exclude(pk__in=settable_groups(user, allow_public).values('pk'))
    item.groups.set(list(kept) + list(groups))


class GroupsField(serializers.SlugRelatedField):
    """`groups`, by name (#86): only the groups the user may set (settable_groups), so anything else
    is refused as 'does not exist'."""

    def __init__(self, allow_public=False, **kwargs):
        self.allow_public = allow_public
        super().__init__(slug_field='name', queryset=Group.objects.all(), **kwargs)

    def get_queryset(self):
        request = self.context.get('request')
        if request is None:
            return Group.objects.none()
        return settable_groups(request.user, self.allow_public)
