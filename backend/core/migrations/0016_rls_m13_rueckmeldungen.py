"""Rückmeldungen und Kalender-Abo (Meilenstein 13): Row-Level Security.

Rückmeldungen und persönliche Kalender-Abos gehören dem Verein des Termins bzw.
des Zugangs; andere Vereine und der Dachverband sehen sie nicht. Das Abo wird
ohne Anmeldung als Systemaufgabe gelesen.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["events_eventresponse", "events_personalcalendar"]


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
        ("core", "0015_rls_m12_termine"),
        ("events", "0002_rueckmeldungen"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
