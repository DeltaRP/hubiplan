"""SEPA und Jahresabschluss (Meilenstein 11): Row-Level Security.

Mandate, Lastschriftläufe, Lastschriften und Jahresabschlüsse sieht nur die eigene
Organisation.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["billing_mandate", "billing_debitrun", "billing_debititem", "finance_yearclosing"]


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
        ("core", "0013_rls_m10_mahnungen"),
        ("billing", "0003_sepa_lastschrift"),
        ("finance", "0003_jahresabschluss"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
