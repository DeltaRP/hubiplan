"""Hintergrund-Jobs der Beiträge."""

from celery import shared_task


@shared_task
def archive_invoices() -> int:
    """Festgeschriebene Rechnungen als PDF ablegen (alle 15 Minuten, je 200)."""
    from .archive import archive_missing

    return archive_missing()
