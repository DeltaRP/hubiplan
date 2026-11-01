"""Wettbewerbe: Row-Level Security für Pfänder, Schüsse, Mannschaften, Platzierungen und
Standzugänge."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "competitions_shot",
    "competitions_prize",
    "competitions_team",
    "competitions_teammember",
    "competitions_placing",
    "competitions_standaccess",
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [("competitions", "0003_vogel_fremd_standzugang")]

    operations = [migrations.RunPython(forwards, backwards)]
