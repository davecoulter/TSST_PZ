"""Template helpers for the TNS report pages (#52)."""
from django import template

register = template.Library()


@register.filter(name='is_tns_reporter')
def is_tns_reporter(user):
    """{% if user|is_tns_reporter %}: the same check the TNS pages make (membership of the "TNS
    Reporters" group), so the nav entry shows exactly for those who can open them."""
    from ..tns_views import is_tns_reporter as check  # at render time, not when the tag library loads
    return check(user)
