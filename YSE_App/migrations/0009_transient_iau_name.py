from django.db import migrations, models


class Migration(migrations.Migration):
    """Transient.iau_name (#29): the TNS designation, null until reported, so existing rows
    need no backfill. MySQL allows any number of NULLs under the unique index."""

    dependencies = [
        ('YSE_App', '0008_new_tag_backfill'),
    ]

    operations = [
        migrations.AddField(
            model_name='transient',
            name='iau_name',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
