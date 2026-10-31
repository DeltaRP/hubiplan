"""Row-Level Security für den Dachverbandszugriff (Meilenstein 6).

Die Plattform schaltet je Dachverband frei, ob er Mitgliedsdaten seiner Vereine
sehen (read) oder auch ändern (write) darf. Die Anwendung setzt dann
``app.fed_access``; die Regeln lassen Lesen bzw. Schreiben in den Vereinen zu,
deren Verbandsbereich der aktive Dachverband ist.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, enable_policy_sql

FED_READ = "current_setting('app.fed_access', true) IN ('read', 'write')"
FED_WRITE = "current_setting('app.fed_access', true) = 'write'"
CLUBS_OF_ORG = f"(SELECT id FROM organizations_organization WHERE parent_id = {ORG})"
MEMBERSHIPS_OF_ORG = f"(SELECT id FROM members_membership WHERE scope_id = {ORG})"


def rule(own: str, fed: str, flag: str) -> str:
    return f"({own}) OR ({flag} AND {fed})"


POLICIES = {
    "members_membership": (
        f"organization_id = {ORG}",
        f"scope_id = {ORG}",
    ),
    "members_membershipperiod": (
        f"organization_id = {ORG}",
        f"membership_id IN {MEMBERSHIPS_OF_ORG}",
    ),
    "members_membertypeassignment": (
        f"organization_id = {ORG}",
        f"membership_id IN {MEMBERSHIPS_OF_ORG}",
    ),
    "members_departmentmembership": (
        f"organization_id = {ORG}",
        f"membership_id IN {MEMBERSHIPS_OF_ORG}",
    ),
    "members_departmentroleholder": (
        f"organization_id = {ORG}",
        f"membership_id IN {MEMBERSHIPS_OF_ORG}",
    ),
    "members_membertype": (
        f"organization_id = {ORG}",
        f"organization_id IN {CLUBS_OF_ORG}",
    ),
    "organizations_department": (
        f"organization_id = {ORG}",
        f"organization_id IN {CLUBS_OF_ORG}",
    ),
    "members_contactdetails": (
        f"scope_id = {SCOPE} AND (organization_id IS NULL OR organization_id = {ORG})",
        f"scope_id = {ORG}",
    ),
}

# Bisherige Regeln (für das Zurückrollen)
PREVIOUS = {
    "members_contactdetails": (
        f"scope_id = {SCOPE} AND (organization_id IS NULL OR organization_id = {ORG})"
    ),
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table, (own, fed) in POLICIES.items():
        schema_editor.execute(
            enable_policy_sql(table, rule(own, fed, FED_READ), rule(own, fed, FED_WRITE))
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table, (own, _fed) in POLICIES.items():
        schema_editor.execute(enable_policy_sql(table, PREVIOUS.get(table, own)))


class Migration(migrations.Migration):
    dependencies = [("core", "0006_rls_m5")]

    operations = [migrations.RunPython(forwards, backwards)]

