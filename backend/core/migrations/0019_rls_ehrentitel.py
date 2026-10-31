"""Ehrentitel: Row-Level Security.

- Titel und Verleihungen gehören der verleihenden Organisation (Verein oder
  Dachverband); nur sie ändert sie.
- Ein Verein liest zusätzlich die Titel seines Dachverbands und deren
  Verleihungen an seine eigenen Mitglieder.
- Ein Dachverband mit Mitgliederzugriff liest Titel und Verleihungen seiner Vereine.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, disable_rls_sql, enable_policy_sql

FED_READ = "current_setting('app.fed_access', true) IN ('read', 'write')"
CLUBS_OF_ORG = f"(SELECT id FROM organizations_organization WHERE parent_id = {ORG})"
OWN = f"organization_id = {ORG}"
OWN_PERSONS = f"(SELECT person_id FROM members_membership WHERE organization_id = {ORG})"
FROM_CLUBS = f"({FED_READ} AND organization_id IN {CLUBS_OF_ORG})"

POLICIES = {
    "members_honorarytitle": f"{OWN} OR organization_id = {SCOPE} OR {FROM_CLUBS}",
    "members_honorarytitleaward": (
        f"{OWN} OR (organization_id = {SCOPE} AND person_id IN {OWN_PERSONS}) OR {FROM_CLUBS}"
    ),
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, using in POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, OWN))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in POLICIES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_rls_rundschreiben"),
        ("members", "0008_ehrentitel"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
