"""Row-Level Security für Wechselanfragen: sichtbar für alten und neuen Verein."""

from django.db import migrations

from core.rls import ORG, disable_rls_sql, enable_policy_sql

TABLE = "members_transferrequest"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            enable_policy_sql(TABLE, f"from_org_id = {ORG} OR to_org_id = {ORG}")
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(disable_rls_sql(TABLE))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_rls_m2"),
        ("members", "0002_membership_purged_at_transferrequest"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
