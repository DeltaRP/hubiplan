"""Änderungspakete sieht nur die eigene Organisation."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["changes_changeset", "changes_changerecord"]


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
        ("changes", "0001_initial"),
        ("core", "0016_rls_m13_rueckmeldungen"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
