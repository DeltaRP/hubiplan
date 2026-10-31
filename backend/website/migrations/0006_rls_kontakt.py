"""Zurückgehaltene Nachrichten: Row-Level Security (gehören der Einheit)."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(enable_rls_sql("website_heldmessage"))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(disable_rls_sql("website_heldmessage"))


class Migration(migrations.Migration):
    dependencies = [("website", "0005_kontakt")]

    operations = [migrations.RunPython(forwards, backwards)]
