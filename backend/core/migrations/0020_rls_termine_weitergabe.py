"""Termine: Weitergabe nach oben.

Bisher las eine Einheit nur eigene Termine und die nicht internen Termine der
Einheit darüber (Verbandsbereich). Neu liest eine Einheit zusätzlich die nicht
internen Termine der Einheiten direkt darunter, die ihre Termine nach oben
freigeben (Schalter der Einheit oder Angabe am Termin). Ändern kann sie diese
Termine nie.
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
# Abweichungen und Anhänge folgen dem Termin (die Termin-Regel gilt auch hier)
EVENT_VISIBLE = f"{OWN} OR EXISTS (SELECT 1 FROM events_event e WHERE e.id = event_id)"
CHILDREN = f"(SELECT id FROM organizations_organization WHERE parent_id = {ORG})"

POLICIES = {
    "events_event": (f"{OWN} OR {FEDERATION_SHARED} OR {CHILD_SHARED_UP}", OWN),
    "events_eventexception": (EVENT_VISIBLE, OWN),
    "events_eventattachment": (EVENT_VISIBLE, OWN),
    "events_eventcategory": (
        f"{OWN} OR organization_id = {SCOPE} OR organization_id IN {CHILDREN}",
        OWN,
    ),
}

OLD_EVENT_VISIBLE = (
    f"{OWN} OR (organization_id = {SCOPE} AND EXISTS "
    "(SELECT 1 FROM events_event e WHERE e.id = event_id))"
)
OLD = {
    "events_event": (f"{OWN} OR {FEDERATION_SHARED}", OWN),
    "events_eventexception": (OLD_EVENT_VISIBLE, OWN),
    "events_eventattachment": (OLD_EVENT_VISIBLE, OWN),
    "events_eventcategory": (f"{OWN} OR organization_id = {SCOPE}", OWN),
}


def apply(policies):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            for table, (using, check) in policies.items():
                schema_editor.execute(enable_policy_sql(table, using, check))

    return run


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_rls_ehrentitel"),
        ("events", "0004_weitergabe"),
        ("organizations", "0026_termine_weitergabe"),
    ]

    operations = [migrations.RunPython(apply(POLICIES), apply(OLD))]
