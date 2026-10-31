"""Einladungs-E-Mails für neu angelegte Konten."""

from __future__ import annotations

import logging

from allauth.account import app_settings as account_settings
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def password_link(user) -> str:
    """Link zum Setzen des Passworts (gleiches Verfahren wie „Passwort vergessen“)."""
    token = account_settings.PASSWORD_RESET_TOKEN_GENERATOR().make_token(user)
    key = f"{user_pk_to_url_str(user)}-{token}"
    return settings.HEADLESS_FRONTEND_URLS["account_reset_password_from_key"].format(key=key)


def send_invitation(user, organization, role_name: str) -> bool:
    from .tokens import INVITATION_DAYS as days

    body = (
        f"Guten Tag,\n\n"
        f"für Sie wurde bei HUBIplan ein Konto angelegt: Rolle „{role_name}“ in "
        f"„{organization.name}“.\n\n"
        f"Bitte legen Sie über diesen Link Ihr Passwort fest (gültig {days} Tage):\n"
        f"{password_link(user)}\n\n"
        f"Ihre Anmeldung: {user.email}\n\n"
        f"Wir empfehlen, danach unter „Einstellungen → Mein Konto“ die "
        f"Zwei-Faktor-Anmeldung einzurichten.\n"
    )
    try:
        send_mail(
            f"Einladung zu HUBIplan – {organization.name}",
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
    except Exception:  # noqa: BLE001 – Versandfehler dürfen die Zuordnung nicht verhindern
        logger.exception("Einladung an %s konnte nicht gesendet werden", user.email)
        return False
    return True
