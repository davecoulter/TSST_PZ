# Seeds TNSValue from the TNS values snapshot Dave's bot downloaded on 2025-06-18 (#52, plan 052
# amendment 20), so a fresh install and the tests have TNS's groups, filters, instruments, ... without
# calling TNS. "Refresh from TNS" (tns_values.sync) brings them up to date afterwards.
# The snapshot is read here directly; this migration does not depend on app code that may change.

import datetime
import json
import os

from django.db import migrations

SNAPSHOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'tns_values.json')


def seed(apps, schema_editor):
    TNSValue = apps.get_model('YSE_App', 'TNSValue')
    with open(SNAPSHOT) as f:
        snapshot = json.load(f)
    seen = datetime.datetime.strptime(snapshot['retrieved'], '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)
    TNSValue.objects.bulk_create([
        TNSValue(kind=kind, tns_id=str(tns_id), label=label, listed=True, last_seen=seen)
        for kind, values in snapshot['data'].items() for tns_id, label in values.items()])


def unseed(apps, schema_editor):
    apps.get_model('YSE_App', 'TNSValue').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('YSE_App', '0014_tnsvalue'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
