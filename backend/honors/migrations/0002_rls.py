"""Würden und Chronik: Row-Level Security wie bei allen Vereinsdaten."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["honors_dignity", "honors_reign", "honors_companion", "honors_reignphoto"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [("honors", "0001_wuerden")]

    operations = [migrations.RunPython(forwards, backwards)]
