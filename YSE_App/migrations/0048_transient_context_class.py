# Generated by Django 2.0.4 on 2019-12-08 04:55

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('YSE_App', '0047_auto_20191201_0420'),
    ]

    operations = [
        migrations.AddField(
            model_name='transient',
            name='context_class',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='YSE_App.TransientClass'),
        ),
    ]