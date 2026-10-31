"""Row-Level Security für die mandantenbezogenen Tabellen aus Meilenstein 1."""

from django.db import migrations

from core.rls import USER, disable_rls_sql, enable_rls_sql

TABLES = {
    "organizations_department": "",
    "organizations_departmentrole": "",
    # Eigene Rollenzuordnungen und deren Rollen sind immer sichtbar
    # (für „Organisation wechseln“ nach dem Login).
    "access_roleassignment": f"user_id = {USER}",
    "access_role": (
        f"id IN (SELECT role_id FROM access_roleassignment WHERE user_id = {USER})"
    ),
    "audit_auditentry": "",
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table, extra in TABLES.items():
        schema_editor.execute(enable_rls_sql(table, extra))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_role"),
        ("organizations", "0001_initial"),
        ("access", "0002_initial"),
        ("audit", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
