"""Meldungen: Row-Level Security und Recht „Meldungen abgeben“ für bestehende Rollen.

Rollen, die Rollen verwalten dürfen (Vorstand), bekommen „Meldungen abgeben“. Das Modul
selbst bleibt aus, bis die Plattform es für die Einheit freischaltet.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "entries_call",
    "entries_callblock",
    "entries_entry",
    "entries_entryteam",
    "entries_entryperson",
    "entries_entryanswer",
    "entries_entryversion",
]
NEW = {"entries.submit"}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(
        organization__type__in=["federation", "club"], department__isnull=True
    ):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and not NEW <= set(perms):
            role.permissions = sorted({*perms, *NEW})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(organization__type__in=["federation", "club"]):
        perms = [p for p in (role.permissions or []) if p not in NEW]
        if perms != list(role.permissions or []):
            role.permissions = perms
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("entries", "0001_meldungen"),
        ("access", "0015_name_oeffentlich"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
