"""Satzungen: Row-Level Security wie bei anderen Organisationsdaten."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["statutes_statuteversion", "statutes_statutepublication"]


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
        ("statutes", "0001_initial"),
        ("core", "0001_app_role"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
