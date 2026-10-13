from django.db import migrations, models


class Migration(migrations.Migration):
    """Bring migration state in line with the models. No database changes.

    - 0002 added ``TransientTag.associated_users`` but the model never defined it.
      DBs that ran 0002 via ``migrate`` (prod, older dev DBs) carry an empty
      ``YSE_App_transienttag_associated_users`` table; DBs built from the SQL
      seeds don't have it at all. A plain RemoveField would drop the table on
      the former and fail on the latter, so only the state is changed and the
      orphan table is left alone.
    - The ``data_quality`` alters only normalize the model reference
      (``YSE_App.dataquality`` -> ``YSE_App.DataQuality``); same table.
    """

    dependencies = [
        ('YSE_App', '0003_surveyobservation_priority'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='transienttag',
                    name='associated_users',
                ),
            ],
            database_operations=[],
        ),
        migrations.AlterField(
            model_name='hostphotdata',
            name='data_quality',
            field=models.ManyToManyField(blank=True, to='YSE_App.DataQuality'),
        ),
        migrations.AlterField(
            model_name='hostspectrum',
            name='data_quality',
            field=models.ManyToManyField(blank=True, to='YSE_App.DataQuality'),
        ),
        migrations.AlterField(
            model_name='transientphotdata',
            name='data_quality',
            field=models.ManyToManyField(blank=True, to='YSE_App.DataQuality'),
        ),
        migrations.AlterField(
            model_name='transientspectrum',
            name='data_quality',
            field=models.ManyToManyField(blank=True, to='YSE_App.DataQuality'),
        ),
    ]
