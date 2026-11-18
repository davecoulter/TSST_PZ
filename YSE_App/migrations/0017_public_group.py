from django.db import migrations

# #86: the reserved group that means "every logged-in user". Data with no group is visible to
# superusers only, so this is the one way to share widely. Production already has a group of this
# name (from YSE-PZ), which is reused as is. No existing data is assigned to it here: groups for
# existing data are set by a separate, manual step (plan 086, deliverable 10).
GROUP = 'Public'


def create_group(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name=GROUP)


class Migration(migrations.Migration):

    dependencies = [
        ('YSE_App', '0016_transient_groups'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # Reversing leaves the group: data may be tagged with it by then.
        migrations.RunPython(create_group, migrations.RunPython.noop),
    ]
