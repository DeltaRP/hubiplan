"""Inhalte versendeter Mails nach einer Frist aus dem Postausgang entfernen.

Der Postausgang hält Mailtexte mit Mitgliederdaten (Rechnungen, Mahnungen,
Rundschreiben). Nach der Zustellung braucht man davon nur noch den Nachweis: an wen,
wann, welcher Betreff, welche Art. Text und Anhänge werden deshalb nach
``OUTBOX_RETENTION_DAYS`` Tagen geleert. Nicht zugestellte Mails bleiben vollständig.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from core.tenancy import rls_bypass

from .backend import attachment_dir
from .models import OutgoingMail

EMPTIED = "(Inhalt nach Ablauf der Aufbewahrungsfrist entfernt)"
# Nachrichten aus dem Kontaktformular der Webseite: nur 7 Tage
SHORT_RETENTION_DAYS = 7
SHORT_RETENTION_KINDS = ("website-contact",)


def purge_sent(now: datetime.datetime | None = None) -> int:
    days = getattr(settings, "OUTBOX_RETENTION_DAYS", 30)
    cutoff = (now or timezone.now()) - datetime.timedelta(days=days)
    root = Path(settings.PRIVATE_ROOT)
    own_folder = attachment_dir().resolve()
    with rls_bypass():
        short = (now or timezone.now()) - datetime.timedelta(days=SHORT_RETENTION_DAYS)
        old = (
            OutgoingMail.objects.filter(status=OutgoingMail.Status.SENT)
            .filter(
                Q(created_at__lt=cutoff) | Q(kind__in=SHORT_RETENTION_KINDS, created_at__lt=short)
            )
            .exclude(body=EMPTIED)
        )
        paths: set[str] = set()
        count = 0
        for mail in old.iterator():
            paths.update(a.get("path", "") for a in mail.attachments or [])
            mail.body = EMPTIED
            mail.attachments = []
            mail.save(update_fields=["body", "attachments"])
            count += 1
        # Nur eigene Anhangdateien des Postausgangs löschen (nicht z. B. Dokumente,
        # die ein Rundschreiben mitgeschickt hat) und nur, wenn keine andere Mail sie
        # noch nennt
        for rel in paths:
            if not rel:
                continue
            path = (root / rel).resolve()
            if not path.is_relative_to(own_folder):
                continue
            if OutgoingMail.objects.filter(attachments__contains=[{"path": rel}]).exists():
                continue
            path.unlink(missing_ok=True)
    return count
