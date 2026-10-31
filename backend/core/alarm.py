"""Alarm-Mails an den Betreiber bei sicherheitsrelevanten Ereignissen.

Ein Angreifer mit gestohlenem Zugang fällt meist durch große Exporte oder neue
Plattformzugänge auf. Diese Ereignisse melden wir sofort per Mail, damit der
Betreiber reagieren kann (Zugang sperren, Passwörter zurücksetzen).

Empfänger: ``SECURITY_ALERT_EMAIL`` (Komma-Liste), sonst alle aktiven Superuser.
Eine Alarm-Mail darf die eigentliche Aktion nie verhindern.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.utils import timezone

logger = logging.getLogger(__name__)

KIND = "sicherheit"


def recipients() -> list[str]:
    configured = [a.strip() for a in settings.SECURITY_ALERT_EMAIL.split(",") if a.strip()]
    if configured:
        return configured
    from django.contrib.auth import get_user_model

    from .tenancy import rls_bypass

    with rls_bypass():
        return [
            e
            for e in get_user_model()
            .objects.filter(is_superuser=True, is_active=True)
            .values_list("email", flat=True)
            if e
        ]


def send_alert(subject: str, lines: list[str]) -> None:
    if not settings.SECURITY_ALERTS:
        return
    try:
        to = recipients()
        if not to:
            logger.warning("Sicherheitsalarm ohne Empfänger: %s", subject)
            return
        from outbox.mail import send

        body = "\n".join(
            [
                f"{subject}",
                "",
                *lines,
                f"Zeit: {timezone.localtime():%d.%m.%Y %H:%M}",
                "",
                "Wenn das nicht erwartet war: Zugang sperren, Passwort zurücksetzen und das",
                "Protokoll prüfen (Notfallplan in docs/betrieb.md).",
            ]
        )
        send(to, f"[HUBIplan-Sicherheit] {subject}", body, kind=KIND, fail_silently=True)
    except Exception:  # noqa: BLE001
        logger.exception("Sicherheitsalarm konnte nicht gesendet werden: %s", subject)


def _who(user) -> str:
    return getattr(user, "email", "") or "unbekannt"


def export_finished(organization, user, what: str, count: int | None) -> None:
    """Große Exporte (ab ``ALERT_EXPORT_ROWS`` Zeilen) und vollständige Exporte melden."""
    if count is not None and count < settings.ALERT_EXPORT_ROWS:
        return
    size = f"{count} Datensätze" if count is not None else "alle Daten"
    send_alert(
        f"Export: {size} aus {organization.name}",
        [f"Art: {what}", f"Organisation: {organization.name}", f"Benutzer: {_who(user)}"],
    )


def _role_assigned(sender, instance, created, **kwargs) -> None:
    from organizations.models import Organization

    if not created or instance.user_id is None:
        return
    role = instance.role
    if role.organization.type != Organization.Type.PLATFORM:
        return
    send_alert(
        "Neuer Plattformzugang",
        [f"Benutzer: {_who(instance.user)}", f"Rolle: {role.name}"],
    )


def _user_saved(sender, instance, created, **kwargs) -> None:
    if created and instance.is_superuser:
        send_alert("Neuer Superuser angelegt", [f"Benutzer: {_who(instance)}"])


def connect() -> None:
    from django.contrib.auth import get_user_model

    from access.models import RoleAssignment

    post_save.connect(_role_assigned, sender=RoleAssignment, dispatch_uid="alarm-rolle")
    post_save.connect(_user_saved, sender=get_user_model(), dispatch_uid="alarm-superuser")
