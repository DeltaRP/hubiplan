"""Recht „Verbund verwalten“ für Rollen, die die Organisation bearbeiten dürfen."""

from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(
        organization__type__in=["platform", "federation", "club"], department__isnull=True
    ):
        perms = list(role.permissions or [])
        if "org.edit" in perms and "peering.manage" not in perms:
            role.permissions = sorted({*perms, "peering.manage"})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(permissions__contains=["peering.manage"]):
        role.permissions = [p for p in role.permissions if p != "peering.manage"]
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("peering", "0001_initial"),
        ("access", "0011_eine_rollenart_rueckverweise"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
