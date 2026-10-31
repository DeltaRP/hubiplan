"""Dachverband und Mahnungen (Meilenstein 10): Row-Level Security und Freischaltung.

- Mahnstufen und Mahnungen sieht nur die eigene Organisation.
- Dachverbände bekommen das Modul Beiträge freigeschaltet.
- Dachverbandsrollen, die Rollen verwalten dürfen, bekommen die Beitragsrechte.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ["billing_dunninglevel", "billing_dunning"]
CODES = ["billing.view", "billing.edit"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))
    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("access", "Role")
    for org in Organization.objects.filter(type="federation"):
        if "billing" not in (org.enabled_modules or []):
            org.enabled_modules = sorted({*(org.enabled_modules or []), "billing"})
            org.save(update_fields=["enabled_modules"])
    for role in Role.objects.filter(organization__type="federation"):
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
        ("core", "0012_rls_datenuebernahme"),
        ("billing", "0002_dachverband_mahnungen_ust"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
