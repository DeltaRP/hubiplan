"""Veranstaltungen und Veranstaltungsreihen (Finanzen): Row-Level Security.

Sie gehören der Organisation, die sie angelegt hat; andere Vereine und der
Dachverband sehen sie nicht.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["finance_projectseries", "finance_project"]


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
        ("core", "0016_rls_m13_rueckmeldungen"),
        ("finance", "0005_veranstaltungen"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
