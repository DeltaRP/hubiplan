"""Würden an Untereinheiten weitergeben: Vereine lesen die weitergegebenen Würden ihres
Dachverbands (Verbandsbereich) und die Regentschaften ihrer eigenen Träger (Herkunft =
der Verein) samt Begleitpersonen und Fotos; ändern können sie sie nie."""

from django.db import migrations

from core.rls import ORG, SCOPE, enable_policy_sql, enable_rls_sql

OWN = f"organization_id = {ORG}"
SHARED_DIGNITY = f"(organization_id = {SCOPE} AND share_down)"
# Von weitergegebenen Würden nur die Regentschaften, deren Träger aus der Einheit kam
SHARED_REIGN = (
    f"(organization_id = {SCOPE} AND EXISTS "
    "(SELECT 1 FROM honors_dignity d WHERE d.id = dignity_id AND d.share_down)"
    f" AND origin_id = {ORG})"
)
# Die Regentschaft selbst unterliegt RLS: sichtbar nur, wenn ihre Würde weitergegeben ist
SHARED_CHILD = (
    f"(organization_id = {SCOPE} AND EXISTS (SELECT 1 FROM honors_reign r WHERE r.id = reign_id))"
)

POLICIES = {
    "honors_dignity": (f"{OWN} OR {SHARED_DIGNITY}", OWN),
    "honors_reign": (f"{OWN} OR {SHARED_REIGN}", OWN),
    "honors_companion": (f"{OWN} OR {SHARED_CHILD}", OWN),
    "honors_reignphoto": (f"{OWN} OR {SHARED_CHILD}", OWN),
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, (using, check) in POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, check))


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in POLICIES:
            schema_editor.execute(enable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_rls_mailverteiler"),
        ("honors", "0006_share_down"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
