"""Wettbewerbe: Row-Level Security für Reihen, Wanderpokale und Auszeichnungen."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "competitions_series",
    "competitions_trophy",
    "competitions_award",
    "competitions_awardgrant",
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
    dependencies = [("competitions", "0011_auszeichnungen_reihen")]

    operations = [migrations.RunPython(forwards, backwards)]
