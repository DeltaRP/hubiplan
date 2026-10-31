"""Neues Recht „Fotos verwalten“ in die bestehenden Vorstandsrollen der Vereine aufnehmen."""

from django.db import migrations

CODE = "photos.manage"


def forwards(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(name="Vorstand", organization__type="club"):
        if CODE not in role.permissions:
            role.permissions = sorted([*role.permissions, CODE])
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(permissions__contains=[CODE]):
        role.permissions = [p for p in role.permissions if p != CODE]
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0004_alter_roleassignment_user"),
        ("organizations", "0004_organization_photo_approval_required"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
