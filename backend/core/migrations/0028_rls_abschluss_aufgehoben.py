"""Aufgehobene Jahresabschlüsse: Row-Level Security wie alle Kassendaten."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["finance_reopenedclosing"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_rls_wuerden_weitergabe"),
        ("finance", "0014_abschluss_aufgehoben"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
