"""Hintergrund-Jobs der Mitgliederverwaltung."""

import logging

from celery import shared_task

from .workflows import purge_expired

logger = logging.getLogger(__name__)


@shared_task
def purge_expired_members() -> int:
    """Täglich: Daten ehemaliger Mitglieder nach Ablauf der Löschfrist löschen."""
    from . import loeschliste

    # Löschliste zuerst (falls ein älteres Backup eingespielt wurde, Fachfrage 7)
    loeschliste.apply()
    count = purge_expired()
    logger.info("Löschfrist: %s Mitgliedschaften bereinigt", count)
    return count
