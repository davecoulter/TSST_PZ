from django.conf import settings
from django.db import migrations


def _norm(name):
    return (name or '').strip().lower()


def backfill_new_tag(apps, schema_editor):
    """Give the `New` candidate tag to the candidates that exist and have no candidate-kind tag, so the
    backlog is visible on the Candidates page (new candidates get it when they are created). Idempotent;
    nothing else is touched."""
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    User = apps.get_model(app_label, model_name)
    admin = User.objects.filter(is_superuser=True).order_by('id').first()
    TagKind = apps.get_model('YSE_App', 'TagKind')
    TransientTag = apps.get_model('YSE_App', 'TransientTag')
    Transient = apps.get_model('YSE_App', 'Transient')
    TransientStatus = apps.get_model('YSE_App', 'TransientStatus')
    WebAppColor = apps.get_model('YSE_App', 'WebAppColor')

    kind = next((k for k in TagKind.objects.order_by('id') if _norm(k.name) == 'candidate'), None)
    status = next((s for s in TransientStatus.objects.order_by('id') if _norm(s.name) == 'candidate'), None)
    if admin is None or kind is None or status is None:
        print('\n  0008: no superuser, Candidate tag kind or Candidate status yet, so nothing was backfilled. '
              'See docker/README.md, "Migrations".')
        return
    new = next((t for t in TransientTag.objects.filter(kind=kind).order_by('id') if _norm(t.name) == 'new'), None)
    candidates = [t for t in Transient.objects.filter(status=status) if not t.tags.filter(kind=kind).exists()]
    if new is None and not candidates:
        return  # nothing to tag; the tag is created when the first candidate arrives
    if new is None:
        color = WebAppColor.objects.filter(color__iexact='orange').first()
        new = TransientTag.objects.create(name='New', kind=kind, color=color, created_by=admin, modified_by=admin)
    for transient in candidates:
        transient.tags.add(new)


class Migration(migrations.Migration):
    """Data only. Reversing leaves the tags in place: people may have triaged against them."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('YSE_App', '0007_kinds_archived_wavelengths'),
    ]

    operations = [
        migrations.RunPython(backfill_new_tag, migrations.RunPython.noop),
    ]
