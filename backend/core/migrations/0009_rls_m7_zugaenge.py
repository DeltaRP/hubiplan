"""Row-Level Security für Postausgang und Zugänge (Meilenstein 7).

- Postausgang und Änderungsmeldungen: nur die eigene Organisation.
- Zugänge: die eigene Organisation – und der Benutzer selbst, damit er nach der
  Anmeldung seine Zugänge findet, bevor eine Organisation aktiv ist.
- Anmeldelinks enthalten keine Mitgliedsdaten und haben kein RLS.
"""

from django.db import migrations

from core.rls import USER, disable_rls_sql, enable_rls_sql

TABLES = {
    "outbox_outgoingmail": "",
    "portal_changerequest": "",
    "portal_portalaccess": f"user_id = {USER}",
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, extra in TABLES.items():
            schema_editor.execute(enable_rls_sql(table, extra))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_rls_photos"),
        ("outbox", "0001_initial"),
        ("portal", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
