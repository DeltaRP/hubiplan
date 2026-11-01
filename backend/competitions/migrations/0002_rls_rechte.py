"""Wettbewerbe: Row-Level Security und Rechte für bestehende Rollen.

Rollen, die Rollen verwalten dürfen (Vorstand), bekommen „Wettbewerbe verwalten“ und
„Ergebnisse erfassen“. Das Modul selbst bleibt aus, bis die Plattform es für die
Einheit freischaltet.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "competitions_competition",
    "competitions_scoring",
    "competitions_starter",
    "competitions_score",
    "competitions_shootoff",
    "competitions_shootoffentry",
]
NEW = {"competitions.manage", "competitions.results"}


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
        ("competitions", "0001_wettbewerbe"),
        ("access", "0015_name_oeffentlich"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
