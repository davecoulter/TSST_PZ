from django.conf import settings
from django.db import migrations

# Pivot wavelengths (microns) for JWST NIRCam filters. Source: JWST User Documentation,
# "NIRCam Filters", Tables 2 and 3, "Pivot lambda (um)" (values based on commissioning
# flight data), https://jwst-docs.stsci.edu/jwst-near-infrared-camera/nircam-instrumentation/nircam-filters
# (read 2026-10-15). A frozen copy: later edits to YSE_App/common/jwst_bands.py don't change it.
NIRCAM_PIVOT_UM = {
    'F070W': 0.705, 'F090W': 0.902, 'F115W': 1.154, 'F140M': 1.405, 'F150W': 1.501,
    'F162M': 1.627, 'F164N': 1.645, 'F150W2': 1.672, 'F182M': 1.845, 'F187N': 1.874,
    'F200W': 1.988, 'F210M': 2.096, 'F212N': 2.121, 'F250M': 2.503, 'F277W': 2.776,
    'F300M': 2.996, 'F322W2': 3.247, 'F323N': 3.237, 'F335M': 3.362, 'F356W': 3.565,
    'F360M': 3.623, 'F405N': 4.053, 'F410M': 4.083, 'F430M': 4.281, 'F444W': 4.402,
    'F460M': 4.630, 'F466N': 4.654, 'F470N': 4.708, 'F480M': 4.817,
}


def _norm(name):
    return (name or '').strip().lower()


def _find(Model, name):
    """The row whose name matches ignoring case and surrounding whitespace (like 0005)."""
    wanted = _norm(name)
    for obj in Model.objects.order_by('id'):
        if _norm(obj.name) == wanted:
            return obj
    return None


def apply_data(apps, schema_editor):
    """Tag kinds (Transient, Candidate) and the backfill of existing tags, the Archived
    status (#40), and NIRCam band wavelengths (#41). Idempotent; existing rows are
    never modified, except tags with no kind (set to Transient) and bands with no
    wavelength."""
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    User = apps.get_model(app_label, model_name)
    admin = User.objects.filter(is_superuser=True).order_by('id').first()

    if admin is None:
        print('\n  0007: no superuser exists, so the tag kinds and the Archived status were not '
              'created. See docker/README.md, "Migrations".')
    else:
        TagKind = apps.get_model('YSE_App', 'TagKind')
        kinds = {}
        for name in ('Transient', 'Candidate'):
            kinds[name] = _find(TagKind, name) or TagKind.objects.create(
                name=name, created_by=admin, modified_by=admin)
        # tags that predate kinds are transient tags
        apps.get_model('YSE_App', 'TransientTag').objects.filter(
            kind__isnull=True).update(kind=kinds['Transient'])

        TransientStatus = apps.get_model('YSE_App', 'TransientStatus')
        if _find(TransientStatus, 'Archived') is None:
            TransientStatus.objects.create(name='Archived', created_by=admin, modified_by=admin)

    PhotometricBand = apps.get_model('YSE_App', 'PhotometricBand')
    for band in PhotometricBand.objects.filter(
            instrument__name__iexact='NIRCam', instrument__telescope__name__iexact='JWST'):
        microns = NIRCAM_PIVOT_UM.get((band.name or '').strip().upper())
        if microns is not None and not (band.lambda_eff or '').strip():
            band.lambda_eff = '%.1f' % (microns * 10000)
            band.save(update_fields=['lambda_eff'])


class Migration(migrations.Migration):
    """Data only. Reversing leaves the rows: tags, statuses and wavelengths may already be
    in use."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('YSE_App', '0006_host_catalog_and_tag_kind'),
    ]

    operations = [
        migrations.RunPython(apply_data, migrations.RunPython.noop),
    ]
