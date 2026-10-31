"""Row-Level Security für die Mitgliederverwaltung (Meilenstein 2).

- Vereinsdaten (Mitgliedschaft, Zeiträume, Arten …): nur die aktive Organisation.
- Personen und Verbandsnummern: im Verbandsbereich (Dachverband bzw.
  eigenständiger Verein), damit die Dublettenprüfung verbandsweit funktioniert.
  Welche Felder ein anderer Verein davon sieht, begrenzt die Anwendung.
- Kontaktdaten: im Verbandsbereich und nur gemeinsame oder eigene Datensätze.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, disable_rls_sql, enable_policy_sql, enable_rls_sql

ORG_TABLES = [
    "members_membertype",
    "members_membership",
    "members_membershipperiod",
    "members_membertypeassignment",
    "members_departmentmembership",
    "members_departmentroleholder",
]

SCOPE_TABLES = {
    "members_person": f"scope_id = {SCOPE}",
    "members_federationmember": f"scope_id = {SCOPE}",
    "members_contactdetails": (
        f"scope_id = {SCOPE} AND (organization_id IS NULL OR organization_id = {ORG})"
    ),
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in ORG_TABLES:
        schema_editor.execute(enable_rls_sql(table))
    for table, rule in SCOPE_TABLES.items():
        schema_editor.execute(enable_policy_sql(table, rule))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in [*ORG_TABLES, *SCOPE_TABLES]:
        schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_rls_m1"),
        ("members", "0001_initial"),
        ("audit", "0002_auditentry_person_id"),
        ("access", "0003_roleassignment_person"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
