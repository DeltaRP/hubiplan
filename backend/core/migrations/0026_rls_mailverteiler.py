"""Mailverteiler: Row-Level Security wie die Rundschreiben selbst.

Eingänge ohne zugeordneten Verteiler (Organisation leer) sieht nur die
Systemverarbeitung (Umgehung), nie ein Vorstand.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["circulars_mailinglist", "circulars_inboundmail"]


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
        ("core", "0025_rls_kontoauszuege"),
        ("circulars", "0005_mailverteiler"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
