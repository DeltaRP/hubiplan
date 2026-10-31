from celery import shared_task

from .services import purge


@shared_task
def purge_documents() -> int:
    """Papierkorb nach 30 Tagen leeren, verwaiste Dateien entfernen."""
    return purge()
