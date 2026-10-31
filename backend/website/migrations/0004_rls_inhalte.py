"""Inhalte der Webseite: Row-Level Security (gehören der Einheit)."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["website_websitetext", "website_websiterevision", "website_websiteimage"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [("website", "0003_inhalte")]

    operations = [migrations.RunPython(forwards, backwards)]
