"""Offene Anmelde- und Bestätigungslinks bei Sicherheitsänderungen am Konto widerrufen.

Ändert jemand Passwort, Anmelde-E-Mail oder richtet 2FA ein, gelten vorher
verschickte Links (Anmeldelink, E-Mail-Bestätigung) und offene QR-Codes zum
Verbinden der App nicht mehr. Neue Links und Codes lassen sich danach normal
anfordern. Ein Passwortwechsel oder -reset meldet zusätzlich alle App-Geräte ab
(``devices.signals``; der eigene Endpunkt in ``self_service.PasswordView`` ruft
``secure_account`` direkt auf, weil er keine allauth-Signale sendet).
"""

from __future__ import annotations

from django.utils import timezone

from core.tenancy import rls_bypass


def revoke_links(user) -> None:
    from accounts.models import EmailChange
    from devices.models import PairingCode
    from portal.models import LoginLink

    if user is None or user.pk is None:
        return
    now = timezone.now()
    with rls_bypass():
        LoginLink.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
        EmailChange.objects.filter(user=user, used_at__isnull=True).delete()
        PairingCode.objects.filter(user=user, used_at__isnull=True).update(used_at=now)


def secure_account(user, *, devices: bool) -> None:
    """Zentrale Reaktion auf eine Sicherheitsänderung am Konto.

    Widerruft offene Links und QR-Codes; mit ``devices=True`` (Passwort geändert oder
    zurückgesetzt) auch alle App-Geräte samt Verwaltungsfreischaltung.
    """
    revoke_links(user)
    if devices:
        from devices.signals import revoke_devices

        revoke_devices(user)


def _on_security_change(sender, request=None, user=None, **kwargs):
    revoke_links(user)


def connect() -> None:
    from allauth.account import signals as account_signals
    from allauth.mfa import signals as mfa_signals

    for signal in (
        account_signals.password_changed,
        account_signals.password_set,
        account_signals.password_reset,
        mfa_signals.authenticator_added,
        mfa_signals.authenticator_removed,
        mfa_signals.authenticator_reset,
    ):
        signal.connect(_on_security_change, dispatch_uid=f"revoke-links-{id(signal)}")
