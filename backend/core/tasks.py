"""Hintergrund-Jobs. Bisher nur ein Test-Job, um die Celery-Anbindung zu prüfen."""

from celery import shared_task


@shared_task
def ping() -> str:
    return "pong"


def enqueue(task, job, *, failed_status: str, message: str = "") -> bool:
    """Hintergrund-Job an Celery übergeben. Ist der Dienst nicht erreichbar, bleibt der
    Auftrag nicht unbemerkt „läuft“ stehen: Status zurück und Hinweis zum Neustart."""
    import logging

    try:
        task.delay(job.pk)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Job %s konnte nicht gestartet werden", job.pk)
        job.status = failed_status
        job.error = message or (
            "Der Hintergrunddienst war nicht erreichbar, es wurde nichts verändert. "
            "Bitte noch einmal starten."
        )
        job.save(update_fields=["status", "error"])
        return False
    return True
