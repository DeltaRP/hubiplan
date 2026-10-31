"""Gespeicherte Dateien erst nach erfolgreichem Commit löschen.

Rollt die Transaktion zurück, bleibt die Datei erhalten, auf die die
Datenbank dann weiter zeigt (Audit 29.10. B-V03)."""

from __future__ import annotations

from django.db import transaction


def delete_on_commit(*files) -> None:
    """Dateien (FieldFile) zum Löschen nach dem Commit vormerken."""
    targets = [(f.storage, f.name) for f in files if f and f.name]

    def _remove():
        for storage, name in targets:
            storage.delete(name)

    if targets:
        transaction.on_commit(_remove)
