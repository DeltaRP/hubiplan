"""Datenübernahme (vollständiger Export und Import): Row-Level Security und Rechte.

- Export- und Importaufträge sieht nur die eigene Organisation.
- Rollen in Dachverband und Verein, die Rollen verwalten dürfen (Vorstand),
  bekommen „Vollständigen Datenexport erstellen“, im Dachverband zusätzlich
  „Vereine anlegen und importieren“.
- Abteilungsrollen, die die Rollen der Abteilung verwalten, bekommen
  „Daten der Abteilung exportieren“.
"""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql

TABLE = "datatransfer_transferjob"


def _add(obj, codes):
    perms = list(obj.permissions or [])
    if not set(codes) <= set(perms):
        obj.permissions = sorted({*perms, *codes})
        obj.save(update_fields=["permissions"])


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(enable_rls_sql(TABLE))
    Role = apps.get_model("access", "Role")
    DepartmentRole = apps.get_model("organizations", "DepartmentRole")
    for role in Role.objects.filter(organization__type__in=["federation", "club"]):
        if "roles.manage" not in (role.permissions or []):
            continue
        codes = ["data.export"]
        if role.organization.type == "federation":
            codes.append("clubs.manage")
        _add(role, codes)
    for role in DepartmentRole.objects.all():
        if "dept.roles.manage" in (role.permissions or []):
            _add(role, ["dept.export"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(disable_rls_sql(TABLE))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_rls_m9_beitraege"),
        ("datatransfer", "0001_initial"),
        ("organizations", "0009_abteilungsrolle_reihenfolge"),
        ("access", "0005_vorstand_fotos"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
