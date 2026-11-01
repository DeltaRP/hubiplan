"""Hinweis-Mails an das eigene Konto bei sicherheitsrelevanten Ereignissen der App.

Wer einen QR-Code abfotografiert oder einen Anmeldelink abfängt, bekommt ein Gerät mit
langem Zugang. Damit das auffällt, bekommt das Konto bei jedem neuen Gerät und bei jeder
Freischaltung der Verwaltung eine Mail. Eine Mail darf die Aktion nie verhindern.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from core.i18n import datetime_text, language_of, user_language

logger = logging.getLogger(__name__)

KIND = "sicherheit"


def _send(user, subject: str, text: str, **params) -> None:
    """Hinweis-Mail in der Sprache des Kontos; ``subject`` und ``text`` sind die deutschen
    Schlüssel (mit ``gettext_noop`` markiert), ``params`` die Werte für die Platzhalter."""
    if not user.email:
        return
    from outbox.mail import send

    when = timezone.localtime()
    with language_of(user):
        subject = _(subject)
        body = _(
            "Hallo {name},\n\n{text}\n\n"
            "Zeit: {when} Uhr\n\n"
            "Warst du das, ist nichts zu tun. Sonst bitte sofort im Browser unter Mein Konto › "
            "App & andere Instanzen das Gerät abmelden und dein Passwort ändern: {link}\n"
        ).format(
            name=user.get_full_name() or user.email,
            text=_(text).format(**params),
            when=datetime_text(when),
            link=f"{settings.FRONTEND_URL}/mein-konto/app",
        )
    try:
        send(
            [user.email],
            subject,
            body,
            kind=KIND,
            fail_silently=True,
            language=user_language(user),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Hinweis-Mail konnte nicht gesendet werden: %s", subject)


def device_added(user, device) -> None:
    name = device.name
    transaction.on_commit(
        lambda: _send(
            user,
            gettext_noop("Neues Gerät mit deinem Zugang verbunden"),
            gettext_noop(
                "Das Gerät „{name}“ wurde mit deinem HUBIplan-Zugang verbunden (HUBIplan-App)."
            ),
            name=name,
        )
    )


def admin_unlocked(user, device) -> None:
    name = device.name
    transaction.on_commit(
        lambda: _send(
            user,
            gettext_noop("Verwaltung in der App freigeschaltet"),
            gettext_noop(
                "Auf dem Gerät „{name}“ wurde die Verwaltung in der HUBIplan-App freigeschaltet "
                "(Passwort und Zwei-Faktor-Code)."
            ),
            name=name,
        )
    )


def admin_unlock_failed(user, device) -> None:
    """Mehrere falsche Versuche: Mail an das Konto und Alarm an den Betreiber (einmal je Stunde)."""
    from django.core.cache import cache

    from core.alarm import send_alert

    if not cache.add(f"app-admin-unlock-alarm:{device.pk}", 1, 60 * 60):
        return
    _send(
        user,
        gettext_noop("Fehlgeschlagene Freischaltung der Verwaltung"),
        gettext_noop(
            "Auf dem Gerät „{name}“ wurde mehrmals erfolglos versucht, die Verwaltung in "
            "der HUBIplan-App freizuschalten."
        ),
        name=device.name,
    )
    send_alert(
        "App: mehrere fehlgeschlagene Freischaltungen der Verwaltung",
        [f"Konto: {user.email}", f"Gerät: {device.name} (Nr. {device.pk})"],
    )


def copy_detected(user, device) -> None:
    """Ausgemusterter Geräteschlüssel benutzt (H7): Gerät ist gesperrt, Mail und Alarm."""
    from core.alarm import send_alert

    name, pk = device.name, device.pk

    def run():
        _send(
            user,
            gettext_noop("Gerät wegen kopiertem Schlüssel abgemeldet"),
            gettext_noop(
                "Der Schlüssel des Geräts „{name}“ wurde an zwei Stellen benutzt. Das deutet auf "
                "eine Kopie hin. HUBIplan hat das Gerät deshalb abgemeldet; bitte die App neu "
                "verbinden."
            ),
            name=name,
        )
        send_alert(
            "App: Kopie eines Geräteschlüssels erkannt",
            [f"Konto: {user.email}", f"Gerät: {name} (Nr. {pk})", "Gerät wurde abgemeldet."],
        )

    transaction.on_commit(run)
