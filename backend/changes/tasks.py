from celery import shared_task

from .purge import purge_old


@shared_task
def purge_old_changes() -> int:
    return purge_old()
