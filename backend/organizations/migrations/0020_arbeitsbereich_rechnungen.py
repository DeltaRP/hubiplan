"""Arbeitsbereiche von Untereinheiten bekommen Beiträge und Rechnungen.

Bestehende Arbeitsbereiche: Modul einschalten und der Vorstandsrolle die Rechte
für Rechnungen geben, wenn sie schon die Kasse führt.
"""

from django.db import migrations

BILLING = ["billing.view", "billing.edit"]


def forwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("access", "Role")
    db = schema_editor.connection.alias
    for unit in Organization.objects.using(db).filter(type="unit", own_workspace=True):
        modules = set(unit.enabled_modules or [])
        if "billing" not in modules:
            unit.enabled_modules = sorted(modules | {"billing"})
            unit.save(update_fields=["enabled_modules"])
        for role in Role.objects.using(db).filter(organization=unit, name="Vorstand"):
            perms = set(role.permissions or [])
            if "finance.edit" in perms and not set(BILLING) <= perms:
                role.permissions = sorted(perms | set(BILLING))
                role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0019_jubilaeen_einheiten"),
        ("access", "0005_vorstand_fotos"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
