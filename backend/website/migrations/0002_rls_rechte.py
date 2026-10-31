"""Webseite: Row-Level Security und Rechte für bestehende Rollen.

- Webseite, Domains, Vorschau-Links und Einwilligungen gehören der Einheit.
- Rollen, die Rollen verwalten dürfen (Vorstand), bekommen „Webseite verwalten“
  und „Inhalte bearbeiten“. Das Modul selbst bleibt aus, bis die Plattform es
  für die Einheit freischaltet.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = [
    "website_website",
    "website_websitedomain",
    "website_previewlink",
    "website_publicationconsent",
]
NEW = {"website.manage", "website.content"}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(organization__type__in=["federation", "club"]):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and not NEW <= set(perms):
            role.permissions = sorted({*perms, *NEW})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("website", "0001_webseite"),
        ("access", "0006_impressum"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
