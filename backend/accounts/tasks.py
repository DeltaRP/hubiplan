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
    from .security import revoke_links

    count = 0
    with rls_bypass():
        for user in User.objects.filter(initial_password_expires__lt=timezone.now()):
            user.set_unusable_password()
            user.initial_password_expires = None
            user.save(update_fields=["password", "initial_password_expires"])
            # Verbundene App-Geräte hingen am Startpasswort
            from devices.signals import revoke_devices

            revoke_devices(user)
            revoke_links(user)
            count += 1
    return count
