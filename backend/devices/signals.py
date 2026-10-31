"""Geräte abmelden, wenn sich das Passwort ändert oder der Zugang endet."""

from __future__ import annotations

from django.db.models.signals import post_delete
from django.utils import timezone


def revoke_devices(user) -> int:
    from .models import Device

    if user is None or user.pk is None:
        return 0
    return Device.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _on_password_change(sender, request=None, user=None, **kwargs):
    revoke_devices(user)


def _on_access_deleted(sender, instance, **kwargs):
    # Ohne Zugang zum Mitgliederbereich hat die App nichts mehr zu zeigen
    from core.tenancy import user_view
    from portal.models import PortalAccess

    # Zugänge in allen Vereinen zählen, nicht nur die im Verein des Löschenden: In dessen
    # Sicht fehlen die übrigen Zugänge unter RLS (Gesamtaudit 31.10.b, AT-F01)
    with user_view(instance.user_id):
        remaining = PortalAccess.objects.filter(user_id=instance.user_id).exists()
    if not remaining:
        revoke_devices(instance.user)


def connect() -> None:
    from allauth.account import signals as account_signals

    from portal.models import PortalAccess

    for signal in (account_signals.password_changed, account_signals.password_reset):
        signal.connect(_on_password_change, dispatch_uid=f"devices-{id(signal)}")
    post_delete.connect(_on_access_deleted, sender=PortalAccess, dispatch_uid="devices-access")
