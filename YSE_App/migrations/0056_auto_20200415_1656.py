# Generated by Django 2.0.4 on 2020-04-15 16:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('YSE_App', '0055_auto_20200414_2029'),
    ]

    operations = [
        migrations.AddField(
            model_name='transient',
            name='dec_err',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='transient',
            name='ra_err',
            field=models.FloatField(blank=True, null=True),
        ),
    ]