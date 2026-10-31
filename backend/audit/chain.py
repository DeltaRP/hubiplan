"""Verkettetes Änderungsprotokoll (Finanzamt-Prüfung C3).

Jeder Eintrag bekommt je Organisation eine laufende Nummer und eine SHA-256-Prüfsumme über
seine Angaben und die Prüfsumme des Vorgängers. Wer einen Eintrag direkt in der Datenbank
ändert, löscht oder einschiebt, bricht die Kette; die tägliche Prüfung meldet das.

Versiegelt wird nach dem Speichern in einer eigenen kurzen Transaktion (``seal``), damit
Anfragen nicht aufeinander warten. Was dabei liegen bleibt, versiegelt die tägliche Prüfung.

Datenschutz: Nach Ablauf der Löschfrist werden personenbezogene Inhalte (Bezeichnung und
Änderungen) geleert (``cleared``). Die Prüfsumme des Inhalts bleibt gespeichert, so bleibt
die Kette prüfbar; geleerte Einträge werden gezählt, nicht als Fehler gemeldet.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.db import connection, transaction
from django.utils import timezone

from core.tenancy import tenant_context

from .models import AuditCheck, AuditEntry

logger = logging.getLogger(__name__)

GENESIS = "0" * 64
LOCK_KEY = 7342  # erster Schlüssel der Advisory-Sperre (zweiter: Organisation)
MAX_PROBLEMS = 20


def _canon(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def changes_digest(entry) -> str:
    """Prüfsumme des Inhalts (Bezeichnung und Änderungen); beides darf aus
    Datenschutzgründen geleert werden, ohne dass die Kette bricht."""
    content = {"repr": entry.object_repr, "changes": entry.changes or {}}
    return hashlib.sha256(_canon(content).encode()).hexdigest()


# Nicht in der Prüfsumme: user_id (wird beim Löschen eines Kontos geleert; die
# E-Mail-Adresse bleibt) und cleared (Datenschutz, siehe oben).
def entry_digest(entry: AuditEntry, seq: int, prev_hash: str, changes_hash: str) -> str:
    data = [
        seq,
        prev_hash,
        entry.pk,
        entry.organization_id,
        entry.user_email,
        entry.timestamp.isoformat() if entry.timestamp else "",
        entry.action,
        entry.object_type,
        entry.object_id,
        changes_hash,
        entry.person_id,
        str(entry.change_set) if entry.change_set else None,
        entry.via,
    ]
    return hashlib.sha256(_canon(data).encode()).hexdigest()


def _lock(org_id: int) -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", [LOCK_KEY, org_id])


def seal(org_id: int) -> int:
    """Versiegelt alle noch offenen Einträge einer Organisation; Anzahl zurück."""
    with tenant_context(org_id), transaction.atomic():
        _lock(org_id)
        entries = AuditEntry.objects.filter(organization_id=org_id)
        last = entries.filter(seq__isnull=False).order_by("-seq").first()
        seq = last.seq if last else 0
        prev = last.hash if last else GENESIS
        open_entries = list(entries.filter(seq__isnull=True).order_by("id"))
        for entry in open_entries:
            seq += 1
            entry.seq = seq
            entry.prev_hash = prev
            entry.changes_hash = changes_digest(entry)
            entry.hash = entry_digest(entry, seq, prev, entry.changes_hash)
            prev = entry.hash
        if open_entries:
            AuditEntry.objects.bulk_update(
                open_entries, ["seq", "prev_hash", "hash", "changes_hash"], batch_size=500
            )
        return len(open_entries)


def seal_later(org_id: int) -> None:
    """Nach dem Abschluss der laufenden Transaktion versiegeln."""

    def run() -> None:
        try:
            seal(org_id)
        except Exception:  # noqa: BLE001 - die tägliche Prüfung holt es nach
            logger.exception("Protokoll von Organisation %s nicht versiegelt", org_id)

    transaction.on_commit(run)


def verify(org_id: int) -> dict:
    """Prüft die Kette einer Organisation und speichert das Ergebnis."""
    problems: list[str] = []
    count = cleared = 0
    expected_seq = 1
    prev = GENESIS
    head_seq = None
    with tenant_context(org_id):
        entries = AuditEntry.objects.filter(organization_id=org_id, seq__isnull=False)
        for entry in entries.order_by("seq").iterator(chunk_size=2000):
            count += 1
            if entry.seq != expected_seq:
                problems.append(
                    f"Nr. {expected_seq} bis {entry.seq - 1} fehlen (gelöscht)."
                    if entry.seq > expected_seq
                    else f"Nr. {entry.seq} ist doppelt."
                )
                expected_seq = entry.seq
            if entry.prev_hash != prev:
                problems.append(f"Nr. {entry.seq}: Verweis auf den Vorgänger passt nicht.")
            if changes_digest(entry) != entry.changes_hash:
                if entry.cleared:
                    cleared += 1
                else:
                    problems.append(f"Nr. {entry.seq}: Inhalt wurde nachträglich geändert.")
            if entry_digest(entry, entry.seq, entry.prev_hash, entry.changes_hash) != entry.hash:
                problems.append(f"Nr. {entry.seq}: Angaben wurden nachträglich geändert.")
            prev = entry.hash
            head_seq = entry.seq
            expected_seq += 1
        if len(problems) > MAX_PROBLEMS:
            problems = [*problems[:MAX_PROBLEMS], f"… und {len(problems) - MAX_PROBLEMS} weitere."]
        result = {
            "ok": not problems,
            "entries": count,
            "cleared": cleared,
            "head_seq": head_seq,
            "head_hash": prev if head_seq else "",
            "problems": problems,
            "checked_at": timezone.now(),
        }
        AuditCheck.objects.update_or_create(organization_id=org_id, defaults=result)
    return result
