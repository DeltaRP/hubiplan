"""Row-Level Security für Import- und Exportaufträge und Vorlagen."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "exchange_exportjob",
    "exchange_exporttemplate",
    "exchange_importjob",
    "exchange_importtemplate",
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
    dependencies = [
        ("core", "0005_rls_m4"),
        ("exchange", "0001_initial"),
        ("access", "0004_alter_roleassignment_user"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
