from django.conf import settings
from django.db import migrations


# Lookup rows the candidate flow (#16, #23) relies on: (app model, name).
CANDIDATE_LOOKUP_ROWS = [
    ('TransientStatus', 'Candidate'),
    ('TransientTag', 'Candidate'),
    ('DataQuality', 'Superseded'),
    ('InformationSource', 'diffpype'),
]


def _has_row(Model, name):
    """True if a row exists whose name matches ignoring case and surrounding
    whitespace. Compared in Python, not SQL, so the result doesn't depend on the
    column's collation (the SQL seeds are latin1, migration-built tables are
    utf8mb4, and trailing-space handling differs between them). These lookup
    tables are tiny."""
    wanted = name.strip().lower()
    return any((existing or '').strip().lower() == wanted
               for existing in Model.objects.values_list('name', flat=True))


def add_candidate_lookup_rows(apps, schema_editor):
    """Create each row unless one with the same name already exists, ignoring
    case and surrounding whitespace.

    Rows are attributed to the first superuser, like the SQL seeds in
    docker/db_init/YSE_rest_of_tables_insert.sql. Existing rows are never
    modified, so a hand-made row (e.g. Dave's "Candidate" tag on prod) is reused
    as is. A new row is created with the exact name from CANDIDATE_LOOKUP_ROWS.
    """
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    User = apps.get_model(app_label, model_name)
    admin = User.objects.filter(is_superuser=True).order_by('id').first()
    if admin is None:
        print('\n  0005: no superuser exists, so the candidate lookup rows were not created. '
              'See docker/README.md, "Migrations".')
        return

    for model_name, name in CANDIDATE_LOOKUP_ROWS:
        Model = apps.get_model('YSE_App', model_name)
        if not _has_row(Model, name):
            Model.objects.create(name=name, created_by=admin, modified_by=admin)


class Migration(migrations.Migration):
    """Data only: no schema change. Reversing leaves the rows in place, since
    candidates, photometry flags and web resources may already point at them."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('YSE_App', '0004_align_state_with_models'),
    ]

    operations = [
        migrations.RunPython(add_candidate_lookup_rows, migrations.RunPython.noop),
    ]
