"""Hintergrund-Jobs der Rundschreiben."""

from celery import shared_task

from . import services


@shared_task
def send_circular(circular_id: int) -> int:
    """Offene Mails eines Rundschreibens verschicken."""
    return services.send_pending(circular_id)


@shared_task
def fetch_inbound() -> int:
    """Mailverteiler: Sammelpostfach abholen."""
    from . import inbound

    return inbound.fetch_inbound()


@shared_task
def resume_stalled() -> int:
    """Hängengebliebene Rundschreiben weiterversenden (alle 15 Minuten)."""
    return services.resume_stalled()
