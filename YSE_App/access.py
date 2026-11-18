"""View adapters for the visibility rule (#86). They decide nothing themselves; TransientService does."""
import functools

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse

from YSE_App.data import TransientService
from YSE_App.models import Transient
from YSE_App.transient_names import transient_not_found


def transient_access(level=TransientService.TNS_OBJECT, by='slug'):
    """Look the view's transient up through the rule, and call the view with it as `transient` in
    place of the URL's `slug` or `transient_id`.

    - Not visible to the user (or not there): the not-found page for a slug, a plain 404 for an id;
      the same response either way, so it can't tell the two apart.
    - Visible, but `level` is FULL and the user sees it only as a TNS object: 403 (they know it exists).
    - By slug, an old slug or a name typed in redirects to the current slug (#29), query string kept.
    Put it under @login_required."""
    def decorate(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            key = kwargs.pop(by)
            if by == 'slug':
                transient = TransientService.find_visible_transient(request.user, key)
                if transient is None:
                    return transient_not_found(request, key)
                if transient.slug and transient.slug != key:
                    url = reverse(request.resolver_match.view_name, kwargs=dict(kwargs, slug=transient.slug))
                    query = request.META.get('QUERY_STRING')
                    return HttpResponseRedirect(url + ('?' + query if query else ''))
            else:
                transient = TransientService.visible_transients(
                    request.user, Transient.objects.filter(pk=key)).first()
                if transient is None:
                    raise Http404('Transient not found')
            if level == TransientService.FULL and not TransientService.can_edit(request.user, transient):
                raise PermissionDenied
            return view(request, *args, transient=transient, **kwargs)
        return wrapper
    return decorate
