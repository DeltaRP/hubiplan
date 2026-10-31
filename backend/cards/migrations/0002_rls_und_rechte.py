"""Mitgliedsausweise: Row-Level Security und Recht für bestehende Vorstandsrollen.

- Ausweise sieht nur der eigene Verein (die öffentliche Seite sucht ohne RLS).
- Rollen, die Rollen verwalten dürfen (Vorstand), bekommen „Mitgliedsausweise“.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLE = "cards_membercard"
CODE = "cards.manage"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(enable_rls_sql(TABLE))
    Role = apps.get_model("access", "Role")
    for role in Role.objects.exclude(organization__type="platform"):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and CODE not in perms:
            role.permissions = sorted({*perms, CODE})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(disable_rls_sql(TABLE))
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(permissions__contains=[CODE]):
        role.permissions = [p for p in role.permissions if p != CODE]
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("cards", "0001_initial"),
        ("core", "0011_rls_m9_beitraege"),
        ("access", "0005_vorstand_fotos"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
