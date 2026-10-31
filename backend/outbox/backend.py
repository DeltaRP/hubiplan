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


def _store_attachments(message) -> list[dict]:
    stored = []
    for item in message.attachments:
        if isinstance(item, tuple):
            name, content, mimetype = item
        else:  # MIMEBase
            name = item.get_filename() or "anhang"
            content = item.get_payload(decode=True)
            mimetype = item.get_content_type()
        if isinstance(content, str):
            content = content.encode()
        folder = attachment_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}-{Path(name).name}"
        path.write_bytes(content or b"")
        stored.append(
            {
                "name": name,
                "path": str(path.relative_to(settings.PRIVATE_ROOT)),
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
            with rls_bypass():
                mail = OutgoingMail.objects.create(
                    organization_id=int(org_id) if org_id else None,
                    to=", ".join([*message.to, *message.cc, *message.bcc]),
                    reply_to=", ".join(message.reply_to or []),
                    subject=message.subject[:300],
                    body=redact(body),
                    attachments=getattr(message, "outbox_attachments", None)
                    or _store_attachments(message),
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
