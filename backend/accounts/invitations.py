"""Einladungs-E-Mails für neu angelegte Konten."""

from __future__ import annotations

import logging

from allauth.account import app_settings as account_settings
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.core.mail import send_mail
from django.utils.translation import gettext as _

from core.i18n import language_of

logger = logging.getLogger(__name__)


def password_link(user) -> str:
    """Link zum Setzen des Passworts (gleiches Verfahren wie „Passwort vergessen“)."""
    token = account_settings.PASSWORD_RESET_TOKEN_GENERATOR().make_token(user)
    key = f"{user_pk_to_url_str(user)}-{token}"
    return settings.HEADLESS_FRONTEND_URLS["account_reset_password_from_key"].format(key=key)


def send_invitation(user, organization, role_name: str) -> bool:
    from .tokens import INVITATION_DAYS as days

    with language_of(user):
        body = _(
            "Guten Tag,\n\n"
            "für Sie wurde bei HUBIplan ein Konto angelegt: Rolle „{role}“ in „{org}“.\n\n"
            "Bitte legen Sie über diesen Link Ihr Passwort fest (gültig {days} Tage):\n"
            "{link}\n\n"
            "Ihre Anmeldung: {email}\n\n"
            "Wir empfehlen, danach unter „Einstellungen → Mein Konto“ die "
            "Zwei-Faktor-Anmeldung einzurichten.\n"
        ).format(
            role=role_name,
            org=organization.name,
            days=days,
            link=password_link(user),
            email=user.email,
        )
        subject = _("Einladung zu HUBIplan – {org}").format(org=organization.name)
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
    except Exception:  # noqa: BLE001 – Versandfehler dürfen die Zuordnung nicht verhindern
        logger.exception("Einladung an %s konnte nicht gesendet werden", user.email)
        return False
    return True


def send_password_link(user) -> bool:
    """Link zum Festlegen des Passworts für ein Konto, dessen Startpasswort entfällt (FQ-16)."""
    from .tokens import INVITATION_DAYS as days

    with language_of(user):
        body = _(
            "Guten Tag,\n\n"
            "HUBIplan verschickt keine Startpasswörter mehr. Ihr bisheriges Startpasswort "
            "gilt nicht mehr.\n\n"
            "Bitte legen Sie über diesen Link Ihr eigenes Passwort fest (gültig {days} Tage):\n"
            "{link}\n\n"
            "Ihre Anmeldung: {email}\n\n"
            "Ist der Link abgelaufen, hilft „Passwort vergessen“ auf der Anmeldeseite.\n"
        ).format(days=days, link=password_link(user), email=user.email)
        subject = _("HUBIplan: Passwort festlegen")
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
    except Exception:  # noqa: BLE001 – ein Versandfehler soll die übrigen nicht aufhalten
        logger.exception("Passwort-Link an %s konnte nicht gesendet werden", user.email)
        return False
    return True
