from celery import shared_task

from core.tenancy import rls_bypass


@shared_task
def shorten_old_entries() -> int:
    """Täglich: Fassungen ein Jahr nach dem Anlass auf Name und Mannschaft kürzen."""
    from .services import shorten_old

    with rls_bypass():
        return shorten_old()
