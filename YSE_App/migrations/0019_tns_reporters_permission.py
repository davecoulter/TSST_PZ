from django.db import migrations

# #86: "TNS Reporters" becomes a role in the Django sense: a group that grants a permission. Its
# members get the TNS permission declared on TNSReportAttempt.Meta; superusers have every permission
# anyway. Django only creates permission rows after all migrations have run, so this one creates the
# row itself (the same row Django would make), then gives it to the group.
GROUP = 'TNS Reporters'
CODENAME, NAME = 'mutate_tns_metadata', 'Can mutate TNS metadata'


def grant(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    content_type, _ = ContentType.objects.get_or_create(app_label='YSE_App', model='tnsreportattempt')
    permission, _ = Permission.objects.get_or_create(content_type=content_type, codename=CODENAME,
                                                     defaults={'name': NAME})
    Group.objects.get_or_create(name=GROUP)[0].permissions.add(permission)


def revoke(apps, schema_editor):
    # deleting the row also takes it off every group and user that had it
    apps.get_model('auth', 'Permission').objects.filter(
        content_type__app_label='YSE_App', codename=CODENAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('YSE_App', '0018_log_followup_groups_tns_permission'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(grant, revoke),
    ]
