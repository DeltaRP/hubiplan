"""Dokumentenablage: Row-Level Security und Rechte für bestehende Rollen.

- Ordner, Dokumente und Fassungen sieht die eigene Organisation. Vereine lesen
  zusätzlich die für Vereine (oder öffentlich) freigegebenen Ordner ihres
  Dachverbands (Verbandsbereich), ändern können sie sie nie.
- Rollen, die Rollen verwalten dürfen (Vorstand), bekommen „Dokumente lesen“ und
  „Dokumente verwalten“, ebenso Abteilungsrollen, die die Rollen der Abteilung
  verwalten.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, disable_rls_sql, enable_policy_sql

OWN = f"organization_id = {ORG}"
FOLDER_SHARED = (
    f"(organization_id = {SCOPE} AND department_id IS NULL "
    "AND visibility IN ('clubs', 'public'))"
)
DOC_SHARED = (
    f"(organization_id = {SCOPE} AND EXISTS "
    "(SELECT 1 FROM documents_folder f WHERE f.id = folder_id))"
)
VERSION_SHARED = (
    f"(organization_id = {SCOPE} AND EXISTS "
    "(SELECT 1 FROM documents_document d WHERE d.id = document_id))"
)

POLICIES = {
    "documents_folder": (f"{OWN} OR {FOLDER_SHARED}", OWN),
    "documents_document": (f"{OWN} OR {DOC_SHARED}", OWN),
    "documents_documentversion": (f"{OWN} OR {VERSION_SHARED}", OWN),
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, (using, check) in POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, check))
    Role = apps.get_model("access", "Role")
    DepartmentRole = apps.get_model("organizations", "DepartmentRole")
    for role in Role.objects.exclude(organization__type="platform"):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and "docs.manage" not in perms:
            role.permissions = sorted({*perms, "docs.view", "docs.manage"})
            role.save(update_fields=["permissions"])
    for role in DepartmentRole.objects.all():
        perms = list(role.permissions or [])
        if "dept.roles.manage" in perms and "dept.docs.manage" not in perms:
            role.permissions = sorted({*perms, "dept.docs.manage"})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in POLICIES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_ablage"),
        ("core", "0017_rls_veranstaltungen"),
        ("access", "0005_vorstand_fotos"),
        ("organizations", "0012_kurzname"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
