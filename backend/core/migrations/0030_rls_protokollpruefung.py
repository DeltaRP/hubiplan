"""Prüfergebnis des Änderungsprotokolls: Row-Level Security wie das Protokoll selbst."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["audit_auditcheck"]


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
        ("core", "0029_rls_kassenzaehlung"),
        ("audit", "0006_protokollkette"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
