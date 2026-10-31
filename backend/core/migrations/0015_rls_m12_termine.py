"""Terminkalender (Meilenstein 12): Row-Level Security und Freischaltung.

- Termine sieht die eigene Organisation. Vereine lesen zusätzlich die nicht
  internen Termine ihres Dachverbands (Verbandsbereich), ändern können sie sie nie.
- Abweichungen von Serien und Anhänge folgen dem Termin, Kategorien dem Kalender.
- Öffentliche Links sieht nur die eigene Organisation (der öffentliche Abruf läuft
  als Systemaufgabe).
- Bestehende Vereine und Dachverbände bekommen das Modul freigeschaltet; Rollen,
  die Rollen verwalten dürfen (Vorstand), dürfen Termine verwalten, ebenso
  Abteilungsrollen, die die Rollen der Abteilung verwalten.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, disable_rls_sql, enable_policy_sql, enable_rls_sql

OWN = f"organization_id = {ORG}"
FEDERATION_SHARED = f"(organization_id = {SCOPE} AND visibility <> 'board')"
EVENT_VISIBLE = (
    f"{OWN} OR (organization_id = {SCOPE} AND EXISTS "
    "(SELECT 1 FROM events_event e WHERE e.id = event_id))"
)

POLICIES = {
    "events_event": (f"{OWN} OR {FEDERATION_SHARED}", OWN),
    "events_eventexception": (EVENT_VISIBLE, OWN),
    "events_eventattachment": (EVENT_VISIBLE, OWN),
    "events_eventcategory": (f"{OWN} OR organization_id = {SCOPE}", OWN),
}
TABLES = [*POLICIES, "events_calendarpublication"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, (using, check) in POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, check))
        schema_editor.execute(enable_rls_sql("events_calendarpublication"))
    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("access", "Role")
    DepartmentRole = apps.get_model("organizations", "DepartmentRole")
    for org in Organization.objects.exclude(type="platform"):
        if "events" not in (org.enabled_modules or []):
            org.enabled_modules = sorted({*(org.enabled_modules or []), "events"})
            org.save(update_fields=["enabled_modules"])
    for role in Role.objects.exclude(organization__type="platform"):
        perms = list(role.permissions or [])
        if "roles.manage" in perms and "events.manage" not in perms:
            role.permissions = sorted({*perms, "events.manage"})
            role.save(update_fields=["permissions"])
    for role in DepartmentRole.objects.all():
        perms = list(role.permissions or [])
        if "dept.roles.manage" in perms and "dept.events.manage" not in perms:
            role.permissions = sorted({*perms, "dept.events.manage"})
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_rls_m11_sepa_abschluss"),
        ("events", "0001_termine"),
        ("access", "0005_vorstand_fotos"),
        ("organizations", "0009_abteilungsrolle_reihenfolge"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
