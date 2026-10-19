"""Transient names (#29): the internal name, the IAU name, and finding a transient by either.

`Transient.name` is the internal name, which ingest and the API match on. `Transient.iau_name`
is the TNS designation once the transient is reported, stored bare (2026abc). Wherever both
exist the IAU name leads, and the slug follows it (see Transient.save()).
"""
import re
from urllib.parse import urlencode

from django.db.models import Q
from django.db.models.functions import Coalesce
from django.shortcuts import render

from YSE_App.models import AlternateTransientNames, Transient

TNS_SEARCH_URL = 'https://www.wis-tns.org/search'

# "AT 2026abc", "SN2026abc", "at_2026abc": the prefix TNS shows but doesn't store
_IAU_PREFIX = re.compile(r'^(?:AT|SN)[\s_-]*(?=\d{4})', re.IGNORECASE)
_IAU_DESIGNATION = re.compile(r'^\d{4}[a-z]{1,4}$', re.IGNORECASE)


def display_name_expression(prefix=''):
    """Transient.display_name in the DB, for annotating and ordering. `prefix` reaches the
    transient through a relation, e.g. 'transient__'. Don't annotate it as `display_name`:
    that's a read-only property on the model."""
    return Coalesce(prefix + 'iau_name', prefix + 'name')


def name_q(text, prefix=''):
    """Either name contains `text`, ignoring case."""
    return Q(**{prefix + 'name__icontains': text}) | Q(**{prefix + 'iau_name__icontains': text})


def find_transient(slug, queryset=None):
    """The transient a URL points to, or None. Tried in order: its current slug; an alias's slug
    (the old URL of a renamed transient, or a candidate run ID); its internal or IAU name typed
    in directly, with or without the AT/SN prefix."""
    transients = Transient.objects.all() if queryset is None else queryset
    transient = transients.filter(slug=slug).first()
    if transient is not None:
        return transient
    alias_of = (AlternateTransientNames.objects.filter(slug=slug)
                .values_list('transient_id', flat=True).first())
    if alias_of is not None:
        transient = transients.filter(pk=alias_of).first()
        if transient is not None:
            return transient
    name = slug.strip()
    return (transients.filter(Q(name__iexact=name) | Q(iau_name__iexact=_IAU_PREFIX.sub('', name)))
            .order_by('id').first())


def transient_not_found(request, name):
    """The 404 page for a name that isn't in STZ-PZ, with a link to look it up on TNS."""
    bare = _IAU_PREFIX.sub('', name.strip())
    # TNS searches IAU designations and reporters' internal names as separate fields
    field = 'name' if _IAU_DESIGNATION.match(bare) else 'internal_name'
    return render(request, 'YSE_App/transient_not_found.html', {
        'name': name,
        'tns_search_url': TNS_SEARCH_URL + '?' + urlencode({field: bare}),
    }, status=404)
