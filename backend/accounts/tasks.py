"""Regelmäßige Aufgaben rund um Konten."""

from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from core.tenancy import rls_bypass


@shared_task
def expire_initial_passwords() -> int:
    """Nicht ersetzte Startpasswörter nach Ablauf unbrauchbar machen (AT-S04).

    Das Konto bleibt; die Person setzt ihr Passwort über den Einladungslink oder
    „Passwort vergessen“.
    """
    from .models import User

    count = 0
    with rls_bypass():
        for user in User.objects.filter(initial_password_expires__lt=timezone.now()):
            retire_initial_password(user)
            count += 1
    return count


def retire_initial_password(user) -> None:
    """Startpasswort unbrauchbar machen; App-Geräte und offene Links hingen daran."""
    from devices.signals import revoke_devices

    from .security import revoke_links

    user.set_unusable_password()
    user.initial_password_expires = None
    user.save(update_fields=["password", "initial_password_expires"])
    revoke_devices(user)
    revoke_links(user)


def convert_initial_passwords() -> tuple[int, int]:
    """Alle noch ausgegebenen Startpasswörter durch einen Einladungslink ersetzen (FQ-16).

    Rückgabe: (umgestellte Konten, davon Mail verschickt)."""
    from .invitations import send_password_link
    from .models import User

    converted = sent = 0
    with rls_bypass():
        for user in User.objects.filter(initial_password_expires__isnull=False):
            retire_initial_password(user)
            converted += 1
            sent += send_password_link(user)
    return converted, sent
