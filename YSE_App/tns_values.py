"""TNS enumerations (#52, plan 052 amendments 20-21): groups, AT types, filters, instruments, units,
archives, ... as TNS lists them at /api/get/values.

They live in the TNSValue table, seeded from the 2025-06-18 snapshot (migration 0015) and refreshed
from TNS by `refresh` ("Refresh from TNS" on the select page, `manage.py sync_tns_values`), so a page
load never calls TNS. Nothing hardcodes an id: code names a label ('PSN', 'JWST - NIRCam') and this
gives the id.

- Lookups (`label`, `listed`, `find_id`, `choices`) read a per-process copy of the table, at most
  CACHE_SECONDS old: a refresh reaches every web worker within that time (at once in its own).
- `refresh(bot, user)` asks TNS as one bot, at most once per REFRESH_GAP site-wide, and `apply`s the
  answer: new values are added, renamed ones relabelled, dropped ones kept but unlisted (never
  deleted), and every TNS group gets an observation group (`link_obs_groups`).
"""
import datetime
import json
import time
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from . import tns_client
from .candidate_ingest import name_key

CACHE_SECONDS = 60
REFRESH_GAP = datetime.timedelta(minutes=10)

_cache = {'tables': None, 'loaded': 0.0}


def clear():
    """Forget this process's copy, so the next lookup reads the table."""
    _cache['tables'] = None


def _tables():
    """{kind: {tns_id: (label, listed)}}, from this process's copy when fresh enough."""
    if _cache['tables'] is None or time.monotonic() - _cache['loaded'] > CACHE_SECONDS:
        from .models import TNSValue
        tables = defaultdict(dict)
        for kind, tns_id, text, is_listed in TNSValue.objects.values_list('kind', 'tns_id', 'label', 'listed'):
            tables[kind][tns_id] = (text, is_listed)
        _cache.update(tables=dict(tables), loaded=time.monotonic())
    return _cache['tables']


def table(kind):
    """{id: label} of the values TNS lists, for one kind, e.g. table('groups'); ids are strings."""
    return {i: text for i, (text, is_listed) in _tables().get(kind, {}).items() if is_listed}


def label(kind, value_id):
    """The label of an id, listed or not; None when TNS never had such an id."""
    if value_id is None:
        return None
    found = _tables().get(kind, {}).get(str(value_id))
    return found[0] if found else None


def listed(kind, value_id):
    """Whether TNS still lists this id (at the last refresh)."""
    found = _tables().get(kind, {}).get(str(value_id))
    return bool(found and found[1])


def find_id(kind, name):
    """The listed id whose label is `name` (ignoring case and surrounding spaces), else the one whose
    label starts with `name` followed by ' - ' ('PSN' finds 'PSN - Possible SN'), else None. More than
    one prefix match is ambiguous and also gives None."""
    if not name:
        return None
    wanted = name.strip().lower()
    labels = table(kind)
    exact = [i for i, text in labels.items() if text.strip().lower() == wanted]
    if exact:
        return exact[0]
    prefixed = [i for i, text in labels.items() if text.strip().lower().startswith(wanted + ' - ')]
    return prefixed[0] if len(prefixed) == 1 else None


def choices(kind):
    """[(id, label)] of the listed values, sorted by label, for a form's dropdown."""
    return sorted(table(kind).items(), key=lambda item: item[1].lower())


def as_of():
    """When the values were last brought from TNS: the latest successful refresh, else the snapshot."""
    from .models import TNSValue, TNSValueSync
    last = TNSValueSync.objects.filter(ok=True).order_by('-created_date').values_list('created_date', flat=True).first()
    if last:
        return last
    return TNSValue.objects.order_by('-last_seen').values_list('last_seen', flat=True).first()


# --- refreshing from TNS ----------------------------------------------------

class TooSoon(Exception):
    """The last refresh was within REFRESH_GAP; `wait` is how many seconds until the next is allowed."""

    def __init__(self, wait):
        super().__init__('TNS values were refreshed moments ago; try again in %d s' % wait)
        self.wait = wait


def refresh(bot, user, gap=REFRESH_GAP):
    """Ask TNS for its values as `bot` and apply them; returns `apply`'s summary. TooSoon (and no call
    to TNS) within `gap` of the last refresh, failed or not; a TNS failure is recorded, then raised."""
    from .models import TNSValueSync
    last = TNSValueSync.objects.order_by('-created_date').first()
    if gap and last is not None and timezone.now() - last.created_date < gap:
        raise TooSoon((gap - (timezone.now() - last.created_date)).total_seconds())
    try:
        data = tns_client.values(bot)
    except tns_client.TNSError as e:
        TNSValueSync.objects.create(bot=bot, ok=False, summary=str(e), created_by=user, modified_by=user)
        raise
    summary = apply(data, user)
    TNSValueSync.objects.create(bot=bot, ok=True, summary=json.dumps(summary), created_by=user, modified_by=user)
    return summary


def apply(data, user):
    """Bring TNSValue in line with TNS's answer ({kind: {id: label}}) and link every TNS group to an
    observation group. Kinds TNS left out are left alone. Returns what changed:
    {'added': {kind: n}, 'relabelled': {kind: ['id: old -> new']}, 'unlisted': {kind: [id]},
     'relisted': {kind: [id]}, 'obs_groups': link_obs_groups' summary}."""
    from .models import TNSValue
    now = timezone.now()
    summary = {'added': {}, 'relabelled': {}, 'unlisted': {}, 'relisted': {}, 'obs_groups': {}}
    with transaction.atomic():
        existing = {(v.kind, v.tns_id): v for v in TNSValue.objects.select_for_update()}
        for kind, values in sorted(data.items()):
            if not isinstance(values, dict):
                continue
            values = {str(i): str(text) for i, text in values.items()}
            new = [TNSValue(kind=kind, tns_id=i, label=text, listed=True, last_seen=now)
                   for i, text in values.items() if (kind, i) not in existing]
            TNSValue.objects.bulk_create(new)
            for i, text in values.items():
                row = existing.get((kind, i))
                if row is not None and row.label != text:
                    summary['relabelled'].setdefault(kind, []).append('%s: %s -> %s' % (i, row.label, text))
                    TNSValue.objects.filter(pk=row.pk).update(label=text)
                if row is not None and not row.listed:
                    summary['relisted'].setdefault(kind, []).append(i)
            TNSValue.objects.filter(kind=kind, tns_id__in=list(values)).update(listed=True, last_seen=now)
            gone = [i for (k, i), row in existing.items() if k == kind and i not in values and row.listed]
            TNSValue.objects.filter(kind=kind, tns_id__in=gone).update(listed=False)
            if new:
                summary['added'][kind] = len(new)
            if gone:
                summary['unlisted'][kind] = sorted(gone, key=lambda i: (len(i), i))
        if isinstance(data.get('groups'), dict):
            summary['obs_groups'] = link_obs_groups({str(i): str(t) for i, t in data['groups'].items()}, user)
    clear()
    return summary


def summary_text(summary):
    """`apply`'s summary in one line, e.g. '47 values added (44 groups, 3 filters); 2 relabelled; 0 unlisted;
    observation groups: 130 created, 0 linked, 0 skipped'. Each skip is named, with why, so a duplicate
    TNS group name (e.g. two groups called Icarus) is visible, not just counted."""
    added = sum(summary['added'].values())
    kinds = ', '.join('%d %s' % (n, kind) for kind, n in sorted(summary['added'].items()))
    groups = summary.get('obs_groups') or {}
    return '%d values added%s; %d relabelled; %d unlisted; observation groups: %d created, %d linked, %d skipped' % (
        added, ' (%s)' % kinds if kinds else '', sum(map(len, summary['relabelled'].values())),
        sum(map(len, summary['unlisted'].values())), len(groups.get('created', ())), len(groups.get('linked', ())),
        len(groups.get('skipped', ()))) + ''.join('; skipped: %s' % line for line in groups.get('skipped', ()))


def link_obs_groups(groups, user):
    """Give every TNS group ({id: label}) an observation group (amendment 21). For each:
    1. an obs group already linked to its id is left alone;
    2. else the one obs group with its name (name_key) and no TNS group is linked to it;
    3. else a new obs group with its name is created, linked.
    Never deletes or renames. Two obs groups with the name, or one linked to another TNS group, are
    skipped and reported. Returns {'created': [...], 'linked': [...], 'skipped': [...]}."""
    from .models import ObservationGroup
    by_id = {g.tns_reporting_group_id: g for g in ObservationGroup.objects.exclude(tns_reporting_group_id=None)}
    by_name = defaultdict(list)
    for g in ObservationGroup.objects.order_by('id'):
        by_name[name_key(g.name)].append(g)
    created, linked, skipped = [], [], []
    for tns_id, text in sorted(groups.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 0):
        if tns_id in by_id:
            continue
        matches = by_name.get(name_key(text), [])
        if len(matches) > 1:
            skipped.append('%s (%s): %d observation groups have that name' % (text, tns_id, len(matches)))
        elif matches and matches[0].tns_reporting_group_id:
            skipped.append('%s (%s): observation group %s is linked to TNS group %s'
                           % (text, tns_id, matches[0].name, matches[0].tns_reporting_group_id))
        elif matches:
            group = matches[0]
            group.tns_reporting_group_id = tns_id
            group.tns_data_source_group_id = group.tns_data_source_group_id or tns_id
            group.modified_by = user
            group.save()
            linked.append('%s (%s)' % (group.name, tns_id))
        else:
            group = ObservationGroup.objects.create(
                name=text.strip()[:64], tns_reporting_group_id=tns_id, tns_data_source_group_id=tns_id,
                created_by=user, modified_by=user)
            by_name[name_key(group.name)].append(group)
            created.append('%s (%s)' % (group.name, tns_id))
    return {'created': created, 'linked': linked, 'skipped': skipped}
