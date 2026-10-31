"""Neue Pflichtspalten brauchen eine Vorgabe in der Datenbank.

Beim Ausrollen laufen die Migrationen, während der alte Code noch Einträge schreibt. Der
kennt die neuen Spalten nicht; ohne Vorgabe in der Datenbank schlüge jedes Speichern fehl.
"""

import pytest
from django.db import connection

SPALTEN = [
    ("audit_auditentry", "prev_hash"),
    ("audit_auditentry", "hash"),
    ("audit_auditentry", "changes_hash"),
    ("audit_auditentry", "cleared"),
    ("finance_yearclosing", "purged_by_name"),
    ("organizations_organization", "reserves_enabled"),
    ("members_honorarytitle", "year_only"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("tabelle", "spalte"), SPALTEN)
def test_neue_pflichtspalten_haben_vorgabe(tabelle, spalte):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            [tabelle, spalte],
        )
        nullable, vorgabe = cur.fetchone()
    assert nullable == "NO"
    assert vorgabe is not None
