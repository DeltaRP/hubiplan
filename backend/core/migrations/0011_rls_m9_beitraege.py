"""Beiträge und Rechnungen (Meilenstein 9): Row-Level Security und Freischaltung.

- Beitragsregeln, Beitragsläufe, Rechnungen und Zahlungen sieht nur der eigene Verein.
- Bestehende Vereine bekommen das Modul freigeschaltet.
- Vereinsrollen, die Rollen verwalten dürfen (Vorstand), bekommen die Beitragsrechte.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "billing_billingsettings",
    "billing_feerate",
    "billing_agerate",
    "billing_feerun",
    "billing_invoice",
    "billing_invoiceline",
    "billing_payment",
]
CODES = ["billing.view", "billing.edit"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))
    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("access", "Role")
    for org in Organization.objects.filter(type="club"):
        if "billing" not in (org.enabled_modules or []):
            org.enabled_modules = sorted({*(org.enabled_modules or []), "billing"})
            org.save(update_fields=["enabled_modules"])
    for role in Role.objects.filter(organization__type="club"):
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
        ("core", "0010_rls_m8_kasse"),
        ("billing", "0001_initial"),
        ("organizations", "0008_kontaktdaten_bestaetigung"),
        ("access", "0005_vorstand_fotos"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
