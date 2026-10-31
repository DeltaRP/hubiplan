"""Social-Media-Beiträge: Row-Level Security (gehören der Einheit)."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["website_socialfeed", "website_socialpost", "website_socialpostimage"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [("website", "0012_social_media_beitraege")]

    operations = [migrations.RunPython(forwards, backwards)]
