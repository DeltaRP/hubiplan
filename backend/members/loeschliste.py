"""Löschliste (Gesamtaudit 31.10.b, Frage 7): erledigte Löschungen überleben ein Backup.

Wird ein älteres Backup eingespielt, sind gelöschte Daten wieder da. Deshalb steht jede
Löschung zusätzlich in einer Datei außerhalb der Datenbank (eigenes Volume, nur Kennungen
und Zeitpunkte, keine Namen). Beim Start des Backends und täglich wird die Liste erneut
angewendet: Was dort steht und in der Datenbank wieder ungelöscht ist, wird nochmals
gelöscht. Die Kennung allein reicht nicht (nach dem Einspielen vergibt die Datenbank
Nummern neu), deshalb muss auch der Anlagezeitpunkt der Mitgliedschaft passen.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)


def path() -> Path | None:
    value = getattr(settings, "LOESCHLISTE_PATH", "")
    return Path(value) if value else None


def note(membership, *, after_deadline: bool) -> None:
    """Löschung nach dem Speichern in die Liste schreiben (eine Zeile je Löschung)."""
    _append(membership, {"d": after_deadline})


def note_readmitted(membership) -> None:
    """Wiederaufnahme: eine frühere Löschung dieser Mitgliedschaft gilt nicht mehr."""
    _append(membership, {"r": True})


def _append(membership, extra: dict) -> None:
    target = path()
    if target is None:
        return
    entry = {
        "m": membership.pk,
        "o": membership.organization_id,
        "p": membership.person_id,
        "c": membership.created_at.isoformat(),
        **extra,
        "at": timezone.now().isoformat(),
    }

    def write():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            # Die Löschung selbst ist geschehen; fehlt nur der Eintrag, meldet das der Alarm
            logger.exception("Löschliste nicht beschreibbar: %s", target)
            from core.alarm import send_alert

            send_alert(
                "Löschliste nicht beschreibbar",
                [f"Der Eintrag zur Mitgliedschaft {membership.pk} fehlt in {target}."],
            )

    transaction.on_commit(write)


def entries() -> list[dict]:
    target = path()
    if target is None or not target.exists():
        return []
    result = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("m"), int):
            result.append(item)
    return result


def apply() -> int:
    """Liste erneut anwenden; Rückgabe: Anzahl erneut gelöschter Mitgliedschaften."""
    from core.tenancy import rls_bypass

    from .models import Membership
    from .workflows import purge_membership

    # Je Mitgliedschaft zählt der letzte Eintrag (Löschung oder Wiederaufnahme)
    last: dict[tuple, dict] = {}
    for item in entries():
        last[(item["m"], item.get("c"))] = item
    count = 0
    with rls_bypass():
        for item in last.values():
            if item.get("r"):
                continue
            membership = (
                Membership.objects.select_related("person", "organization")
                .filter(pk=item["m"], organization_id=item.get("o"), purged_at__isnull=True)
                .first()
            )
            created = parse_datetime(item.get("c") or "")
            if membership is None or created is None or membership.created_at != created:
                continue
            with transaction.atomic():
                purge_membership(membership, after_deadline=bool(item.get("d")), listed=True)
            count += 1
    if count:
        logger.warning("Löschliste: %s Mitgliedschaften erneut gelöscht", count)
        from core.alarm import send_alert

        send_alert(
            "Löschliste nach dem Einspielen angewendet",
            [
                f"{count} Mitgliedschaften waren in der Datenbank wieder ungelöscht und wurden "
                "erneut gelöscht (vermutlich wurde ein älteres Backup eingespielt)."
            ],
        )
    return count
