"""E-Mail-Backend, das jede Nachricht im Postausgang speichert.

- Ohne ``EMAIL_HOST``: Die Mail wird nur gespeichert (Test-Postfach).
- Mit ``EMAIL_HOST``: zusätzlich per SMTP versendet; der Status wird vermerkt.

Organisation und Art einer Mail kommen über die Kopfzeilen ``X-Hubiplan-Org``
und ``X-Hubiplan-Kind`` (siehe ``outbox.mail.send``); sie werden vor dem
Versand entfernt.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend

from core.tenancy import rls_bypass

from .models import OutgoingMail

logger = logging.getLogger(__name__)

ORG_HEADER = "X-Hubiplan-Org"
KIND_HEADER = "X-Hubiplan-Kind"


def attachment_dir() -> Path:
    return Path(settings.PRIVATE_ROOT) / "outbox"


def _store_attachments(message, org_id: int | None) -> list[dict]:
    """Anhänge verschlüsselt im privaten Speicher ablegen (Schlüssel des Vereins,
    ohne Verein der Plattform)."""
    from django.core.files.base import ContentFile

    from core import crypto
    from exchange.models import private_storage
    from organizations.models import Organization

    stored = []
    if not message.attachments:
        return stored
    owner = org_id if org_id is not None else Organization.platform().pk
    for item in message.attachments:
        if isinstance(item, tuple):
            name, content, mimetype = item
        else:  # MIMEBase
            name = item.get_filename() or "anhang"
            content = item.get_payload(decode=True)
            mimetype = item.get_content_type()
        if isinstance(content, str):
            content = content.encode()
        relative = f"outbox/{uuid.uuid4().hex}-{Path(name).name}"
        with crypto.owner(owner):
            relative = private_storage().save(relative, ContentFile(content or b""))
        stored.append(
            {
                "name": name,
                "path": relative,
                "size": len(content or b""),
                "content_type": mimetype or "application/octet-stream",
            }
        )
    return stored


class NotAccepted(Exception):
    """Der Mailserver hat eine Nachricht nicht angenommen."""


# Links, mit denen man sich anmelden oder ein Konto übernehmen kann. Sie stehen nur in
# der verschickten Mail, nie im Postausgang, den der Vorstand lesen kann.
SECRET_LINK = re.compile(
    r"(https?://\S*?/(?:anmelden/link|passwort-zuruecksetzen|konto/email)/)\S+"
)
REDACTED = "[Link aus Sicherheitsgründen nicht gespeichert]"


def redact(text: str) -> str:
    return SECRET_LINK.sub(lambda m: m.group(1) + REDACTED, text or "")


class OutboxBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        count = 0
        smtp = SmtpBackend(fail_silently=self.fail_silently) if settings.EMAIL_HOST else None
        for message in email_messages:
            headers = message.extra_headers or {}
            org_id = headers.pop(ORG_HEADER, None)
            kind = headers.pop(KIND_HEADER, "")
            body = message.body
            for alt in getattr(message, "alternatives", []) or []:
                if not body and alt[1] == "text/plain":
                    body = alt[0]
            org_pk = int(org_id) if org_id else None
            with rls_bypass():
                mail = OutgoingMail.objects.create(
                    organization_id=org_pk,
                    to=", ".join([*message.to, *message.cc, *message.bcc]),
                    reply_to=", ".join(message.reply_to or []),
                    subject=message.subject[:300],
                    body=redact(body),
                    attachments=getattr(message, "outbox_attachments", None)
                    or _store_attachments(message, org_pk),
                    kind=kind[:50],
                )
            if smtp is not None:
                try:
                    accepted = smtp.send_messages([message])
                    if not accepted:
                        # SMTP hat die Mail nicht angenommen (z. B. still behandelter Fehler)
                        raise NotAccepted("Der Mailserver hat die Nachricht nicht angenommen.")
                    mail.status = OutgoingMail.Status.SENT
                except Exception as exc:  # noqa: BLE001 – Fehler vermerken, nicht abbrechen
                    logger.exception("Versand an %s fehlgeschlagen", mail.to)
                    mail.status = OutgoingMail.Status.FAILED
                    mail.error = str(exc)[:300]
                    with rls_bypass():
                        mail.save(update_fields=["status", "error"])
                    if not self.fail_silently:
                        raise
                    continue  # nicht als versandt zählen
                with rls_bypass():
                    mail.save(update_fields=["status", "error"])
            count += 1
        return count
