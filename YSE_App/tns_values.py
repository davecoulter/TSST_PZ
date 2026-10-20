"""TNS enumerations (#52): reporting groups, AT types, instruments, filters, units and archives.

TNS publishes them as `{id: label}` tables at /api/get/values. A snapshot is committed at
YSE_App/data/tns_values.json and refreshed by `manage.py sync_tns_values`, so forms and the
payload builder read the file and a page load never calls TNS. Nothing here hardcodes an id:
code names a label ('TSST_COSMOS_3D', 'PSN', 'JWST - NIRCam') and the snapshot gives the id.
Plan: agentic_planning/052-tns-reporting/plan.md.
"""
import functools
import json
import os

SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'tns_values.json')


@functools.lru_cache(maxsize=None)
def load(path=SNAPSHOT):
    """The snapshot file: {'retrieved': 'YYYY-MM-DD', 'source': str, 'data': {table: {id: label}}}.
    Cached for the life of the process; `load.cache_clear()` after writing a new one."""
    with open(path) as f:
        return json.load(f)


def table(kind):
    """{id: label} for one table, e.g. table('groups'); ids are strings, as TNS sends them."""
    return load()['data'].get(kind, {})


def label(kind, value_id):
    """The label of an id, or None when the snapshot has no such id."""
    if value_id is None:
        return None
    return table(kind).get(str(value_id))


def find_id(kind, name):
    """The id whose label is `name` (ignoring case and surrounding spaces), else the id whose label
    starts with `name` followed by ' - ' ('PSN' finds 'PSN - Possible SN'), else None. More than
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
    """[(id, label)] sorted by label, for a form's dropdown."""
    return sorted(table(kind).items(), key=lambda item: item[1].lower())


def dump(data, retrieved, source):
    """The snapshot file's text: every table sorted by numeric id, so a refresh diffs cleanly."""
    tables = {kind: dict(sorted(values.items(), key=lambda item: int(item[0])))
              for kind, values in sorted(data.items())}
    return json.dumps({'retrieved': retrieved, 'source': source, 'data': tables},
                      indent=1, ensure_ascii=False) + '\n'
