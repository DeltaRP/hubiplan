"""Row-Level Security für Mitgliederfotos und Foto-Upload-Links (nur eigener Verein)."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["members_memberphoto", "members_photouploadlink"]


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
        ("core", "0007_rls_m6_federation"),
        ("members", "0004_membership_photo_consent_at_and_more"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
