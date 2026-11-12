"""Template helpers for the TNS report pages (#52)."""
from django import template

register = template.Library()


@register.filter(name='is_tns_reporter')
def is_tns_reporter(user):
    """{% if user|is_tns_reporter %}: the same check the TNS pages make (membership of the "TNS
    Reporters" group), so the nav entry shows exactly for those who can open them."""
    from ..tns_views import is_tns_reporter as check  # at render time, not when the tag library loads
    return check(user)


@register.inclusion_tag('YSE_App/tns_attempt_badge.html', takes_context=True)
def tns_badge(context, transient):
    """{% tns_badge transient %}: the transient's latest TNS report as a badge (#52 stage 4), for TNS
    reporters (its link goes to their pages); nothing for anyone else or with no report."""
    from ..tns_attempts import latest
    user = context.get('user')
    attempt = latest([transient.pk]).get(transient.pk) if transient and is_tns_reporter(user) else None
    return {'attempt': attempt}


@register.inclusion_tag('YSE_App/tns_reports_box.html', takes_context=True)
def tns_reports(context, transient):
    """{% tns_reports transient %}: every TNS report of the transient, newest first (#52 stage 4: time,
    who, bot, service, status, report id, TNS's message, its submission, the payload), for TNS reporters."""
    import json
    from ..models import TNSReportAttempt
    from ..tns_views import attempt_state
    user = context.get('user')
    if not transient or not is_tns_reporter(user):
        return {'rows': None}
    attempts = TNSReportAttempt.objects.filter(transient=transient).select_related('bot', 'created_by').order_by('-created_date', '-id')
    return {'rows': [dict(attempt=a, state=attempt_state(a), payload=json.dumps(json.loads(a.payload), indent=1)) for a in attempts]}
