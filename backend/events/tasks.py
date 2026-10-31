"""Hintergrund-Jobs des Terminkalenders."""

from celery import shared_task

from . import notify


@shared_task
def send_event_mails(event_id: int, kind: str) -> int:
    """Einladung, Änderung oder Absage an die Eingeladenen."""
    return notify.send(event_id, kind)


@shared_task
def send_event_reminders() -> int:
    """Stündlich: fällige Erinnerungen verschicken."""
    return notify.send_reminders()
