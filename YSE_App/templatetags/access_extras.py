"""Template filters for the rule set (#86): show a control only to users who may use it. They decide
nothing themselves; TransientService does. The server checks again on every write.

    {% load access_extras %}
    {% if user|can_edit:transient %} ... status buttons, follow-up forms, removing a tag ... {% endif %}
    {% if user|can_comment:transient %} ... the comment form ... {% endif %}
    {% if user|can_delete:followup %} ... a delete button ... {% endif %}
"""
from django import template

from YSE_App.data import TransientService

register = template.Library()


@register.filter
def can_edit(user, transient):
    return TransientService.can_edit(user, transient)


@register.filter
def can_comment(user, transient):
    return TransientService.can_comment(user, transient)


@register.filter
def can_delete(user, item):
    return TransientService.can_delete(user, item)
