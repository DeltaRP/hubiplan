"""Rundschreiben: Row-Level Security und Rechte.

- Rundschreiben, Anhänge, Vorlagen und Empfänger gehören dem Absender
  (Verein oder Dachverband).
- Empfänger sieht zusätzlich der Verein des Empfängers (Mitgliederbereich:
  „meine Rundschreiben“), und damit auch das Rundschreiben und seine Anhänge.
- Rollen, die Rollen verwalten dürfen (Vorstand), dürfen Rundschreiben
  versenden, ebenso Abteilungsrollen, die die Rollen der Abteilung verwalten.
"""

from django.db import migrations

from core.rls import ORG, disable_rls_sql, enable_policy_sql, enable_rls_sql

OWN = f"organization_id = {ORG}"
RECEIVED = (
    "EXISTS (SELECT 1 FROM circulars_circularrecipient r WHERE r.circular_id = "
    "circulars_circular.id)"
)
CIRCULAR_VISIBLE = (
    "EXISTS (SELECT 1 FROM circulars_circular c WHERE c.id = circular_id)"
)

POLICIES = {
    "circulars_circularrecipient": (f"{OWN} OR club_id = {ORG}", OWN),
    "circulars_circular": (f"{OWN} OR {RECEIVED}", OWN),
    "circulars_circularattachment": (f"{OWN} OR {CIRCULAR_VISIBLE}", OWN),
}
TABLES = [*POLICIES, "circulars_circulartemplate"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, (using, check) in POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, check))
        schema_editor.execute(enable_rls_sql("circulars_circulartemplate"))
    Role = apps.get_model("access", "Role")
    DepartmentRole = apps.get_model("organizations", "DepartmentRole")
    for role in Role.objects.exclude(organization__type="platform"):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and "circulars.send" not in perms:
            role.permissions = sorted({*perms, "circulars.send"})
            role.save(update_fields=["permissions"])
    for role in DepartmentRole.objects.all():
        perms = list(role.permissions or [])
        if "dept.roles.manage" in perms and "dept.circulars.send" not in perms:
            role.permissions = sorted({*perms, "dept.circulars.send"})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_rls_veranstaltungen"),
        ("circulars", "0001_rundschreiben"),
        ("access", "0005_vorstand_fotos"),
        ("organizations", "0012_kurzname"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
