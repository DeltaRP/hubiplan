"""Row-Level Security für Zusatzfelder.

Sichtbar sind Felder und Werte der aktiven Organisation und – für Vereine im
Dachverband – die des Dachverbands (verbandsweite Felder). Welche
Dachverbandsfelder ein Verein tatsächlich sieht, begrenzt die Anwendung.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, disable_rls_sql, enable_policy_sql

TABLES = ["customfields_fielddefinition", "customfields_fieldvalue"]
RULE = f"organization_id = {ORG} OR organization_id = {SCOPE}"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_policy_sql(table, RULE))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_rls_m3"),
        ("customfields", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
