"""Verbund: Termine der fernen Einheit darüber lesen.

Eine Einheit, die mit einer Einheit auf einer anderen Instanz darüber gekoppelt
ist, liest deren übermittelte, nicht internen Termine (Platzhalter der fernen
Einheit, Kopplung aktiv). Ändern kann sie sie nie (CHECK bleibt OWN).
"""

from django.db import migrations

from core.rls import ORG, SCOPE, enable_policy_sql

OWN = f"organization_id = {ORG}"
FEDERATION_SHARED = f"(organization_id = {SCOPE} AND visibility <> 'board')"
CHILD_SHARED_UP = (
    "(visibility <> 'board' AND department_id IS NULL AND EXISTS ("
    "SELECT 1 FROM organizations_organization o WHERE o.id = organization_id "
    f"AND o.parent_id = {ORG} AND COALESCE(share_up, o.events_share_up)))"
)
REMOTE = (
    "EXISTS (SELECT 1 FROM peering_coupling c WHERE c.remote_unit_id = organization_id "
    f"AND c.local_unit_id = {ORG} AND c.direction = 'parent' AND c.state = 'active')"
)
REMOTE_SHARED = f"(visibility <> 'board' AND {REMOTE})"
CHILDREN = f"(SELECT id FROM organizations_organization WHERE parent_id = {ORG})"

POLICIES = {
    "events_event": (f"{OWN} OR {FEDERATION_SHARED} OR {CHILD_SHARED_UP} OR {REMOTE_SHARED}", OWN),
    "events_eventcategory": (
        f"{OWN} OR organization_id = {SCOPE} OR organization_id IN {CHILDREN} OR {REMOTE}",
        OWN,
    ),
}
OLD = {
    "events_event": (f"{OWN} OR {FEDERATION_SHARED} OR {CHILD_SHARED_UP}", OWN),
    "events_eventcategory": (
        f"{OWN} OR organization_id = {SCOPE} OR organization_id IN {CHILDREN}",
        OWN,
    ),
}


def apply(policies):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            for table, (using, check) in policies.items():
                schema_editor.execute(enable_policy_sql(table, using, check))

    return run


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_rls_eine_rollenart"),
        ("events", "0005_verbund"),
        ("peering", "0001_initial"),
    ]

    operations = [migrations.RunPython(apply(POLICIES), apply(OLD))]
