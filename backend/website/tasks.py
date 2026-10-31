"""Hintergrund-Jobs der Webseite."""

from celery import shared_task

from .contact import purge_held


@shared_task
def purge_held_messages() -> int:
    """Täglich: zurückgehaltene Formularnachrichten nach 7 Tagen löschen."""
    return purge_held()


@shared_task
def sync_social_feeds() -> int:
    """Alle 30 Minuten: neue Beiträge der verbundenen Instagram- und Facebook-Kanäle."""
    from core.tenancy import rls_bypass

    from .social import sync_all

    with rls_bypass():
        return sync_all()


@shared_task
def maintain_social_feeds() -> None:
    """Täglich: Instagram-Zugänge verlängern, Facebook-Zugänge prüfen."""
    from core.tenancy import rls_bypass

    from .social import maintain_all

    with rls_bypass():
        maintain_all()
