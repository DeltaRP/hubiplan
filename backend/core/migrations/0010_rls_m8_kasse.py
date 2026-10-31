"""Kasse (Meilenstein 8): Row-Level Security und Freischaltung.

- Konten, Kategorien, Buchungen und Belege sehen nur die eigene Organisation.
- Bestehende Vereine und Dachverbände bekommen das Modul Kasse freigeschaltet.
- Rollen, die Rollen verwalten dürfen (Vorstand), bekommen die Kassenrechte.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["finance_account", "finance_category", "finance_booking", "finance_receipt"]
CODES = ["finance.view", "finance.edit"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))
    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("access", "Role")
    for org in Organization.objects.exclude(type="platform"):
        if "finance" not in (org.enabled_modules or []):
            org.enabled_modules = sorted({*(org.enabled_modules or []), "finance"})
            org.save(update_fields=["enabled_modules"])
    for role in Role.objects.exclude(organization__type="platform"):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and not set(CODES) <= set(perms):
            role.permissions = sorted({*perms, *CODES})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_rls_m7_zugaenge"),
        ("finance", "0001_initial"),
        ("organizations", "0006_kasse_geschaeftsjahr"),
        ("access", "0005_vorstand_fotos"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
