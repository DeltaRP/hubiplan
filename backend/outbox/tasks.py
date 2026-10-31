"""Hintergrund-Jobs des Postausgangs."""

import logging

from celery import shared_task

from .purge import purge_sent

logger = logging.getLogger(__name__)


@shared_task
def purge_sent_mails() -> int:
    """Täglich: Text und Anhänge zugestellter Mails nach Ablauf der Frist leeren."""
    count = purge_sent()
    logger.info("Postausgang: %s Mails geleert", count)
    return count
