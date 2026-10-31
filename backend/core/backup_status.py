"""Stand des täglichen Backups prüfen und bei Problemen Alarm schlagen (INF-F03/F04).

Der Backup-Dienst schreibt nach jedem Lauf eine kleine Statusdatei in ein eigenes
Volume (``BACKUP_STATUS_DIR``, im Worker nur lesbar). Diese Aufgabe meldet per
Alarm-Mail, wenn der letzte Lauf fehlgeschlagen oder unvollständig war oder wenn
seit mehr als ``BACKUP_MAX_AGE_HOURS`` Stunden kein vollständiges Backup entstand.
Ohne Statusordner (Entwicklung, Tests) gibt es nichts zu prüfen.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from . import alarm

STATUS_FILE = "status"


def read_status(directory: str) -> dict[str, str] | None:
    path = Path(directory) / STATUS_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    result = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key.strip()] = value.strip()
    return result


def problem(status: dict[str, str] | None, now: float, max_age_hours: int) -> str | None:
    """Text des Problems oder None, wenn alles in Ordnung ist."""
    if status is None:
        return "Der Backup-Dienst hat noch keinen Stand gemeldet."
    try:
        last_ok = int(status.get("last_ok") or 0)
    except ValueError:
        last_ok = 0
    state = status.get("state", "")
    if state == "fehler":
        return f"Das letzte Backup ist fehlgeschlagen: {status.get('text') or 'ohne Angabe'}"
    if state == "unvollstaendig":
        return (
            "Das letzte Backup ist unvollständig: "
            f"{status.get('text') or 'Dateien fehlen'}. Alte Backups werden solange nicht "
            "gelöscht."
        )
    if now - last_ok > max_age_hours * 3600:
        hours = int((now - last_ok) // 3600) if last_ok else None
        since = f"seit {hours} Stunden" if hours is not None else "noch nie"
        return f"Kein vollständiges Backup {since}."
    return None


@shared_task
def check_backup() -> str | None:
    directory = settings.BACKUP_STATUS_DIR
    if not directory or not Path(directory).is_dir():
        return None
    text = problem(read_status(directory), time.time(), settings.BACKUP_MAX_AGE_HOURS)
    # Höchstens eine Mail je Problem und Tag
    # Schlüssel ohne Leerzeichen (memcached-tauglich): Prüfsumme des Textes
    key = hashlib.sha256(text.encode()).hexdigest()[:32] if text else ""
    if text and cache.add(f"backup-alarm:{key}", 1, 24 * 60 * 60):
        alarm.send_alert(
            "Backup prüfen",
            [text, "Details: backup.log und restore-test.log im Backup-Ordner."],
        )
    return text
