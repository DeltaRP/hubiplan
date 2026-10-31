"""Freigabe nach oben: der Dachverband liest die freigegebenen Ordner seiner Vereine.

Dokumente und Fassungen folgen ihrem Ordner bzw. Dokument: sichtbar ist, was zu
einem sichtbaren Ordner gehört (die Unterabfrage unterliegt selbst RLS).
Schreiben bleibt auf die eigene Organisation beschränkt.
"""

from django.db import migrations

from core.rls import ORG, SCOPE, enable_policy_sql

OWN = f"organization_id = {ORG}"
FROM_FEDERATION = (
    f"(organization_id = {SCOPE} AND department_id IS NULL "
    "AND visibility IN ('clubs', 'public'))"
)
FROM_CLUBS = (
    "(shared_up AND department_id IS NULL AND organization_id IN "
    f"(SELECT o.id FROM organizations_organization o WHERE o.parent_id = {ORG}))"
)
DOC_VISIBLE = "EXISTS (SELECT 1 FROM documents_folder f WHERE f.id = folder_id)"
VERSION_VISIBLE = "EXISTS (SELECT 1 FROM documents_document d WHERE d.id = document_id)"

POLICIES = {
    "documents_folder": (f"{OWN} OR {FROM_FEDERATION} OR {FROM_CLUBS}", OWN),
    "documents_document": (f"{OWN} OR {DOC_VISIBLE}", OWN),
    "documents_documentversion": (f"{OWN} OR {VERSION_VISIBLE}", OWN),
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table, (using, check) in POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, check))


def backwards(apps, schema_editor):
    import importlib

    previous = importlib.import_module("documents.migrations.0002_rls_rechte")
    if schema_editor.connection.vendor == "postgresql":
        for table, (using, check) in previous.POLICIES.items():
            schema_editor.execute(enable_policy_sql(table, using, check))


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_nach_oben")]

    operations = [migrations.RunPython(forwards, backwards)]
