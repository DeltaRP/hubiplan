"""E-Mails im Namen einer Organisation versenden."""

from __future__ import annotations

import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .backend import KIND_HEADER, ORG_HEADER

logger = logging.getLogger(__name__)


def imprint_footer(organization) -> tuple[str, str] | None:
    """Absenderzeile mit Links zu Impressum und Datenschutz (Text und HTML)."""
    from django.utils.html import escape

    from organizations import imprint
    from organizations.models import Organization

    try:
        org = organization or Organization.platform()
        urls = imprint.page_urls(org)
    except Exception:  # noqa: BLE001
        logger.exception("Impressum-Links für die Mail fehlen")
        return None
    if org.type == Organization.Type.PLATFORM:
        sender = "Diese Nachricht wurde über HUBIplan versandt."
    else:
        sender = f"Diese Nachricht wurde im Auftrag von {org.name} über HUBIplan versandt."
    text = f"--\n{sender}\nImpressum: {urls['imprint']}\nDatenschutz: {urls['privacy']}"
    markup = (
        '<p style="margin-top:2em;font-size:12px;color:#666">'
        f"{escape(sender)}<br>"
        f'<a href="{escape(urls["imprint"])}">Impressum</a> · '
        f'<a href="{escape(urls["privacy"])}">Datenschutz</a></p>'
    )
    return text, markup


def html_document(html: str, subject: str = "") -> str:
    """HTML-Teil als vollständiges Dokument mit Sprache Deutsch (WCAG 3.1.1).

    Mailprogramme und Screenreader lesen den Text dann mit deutscher Aussprache.
    Ein schon vollständiges Dokument bleibt unverändert.
    """
    from django.utils.html import escape

    head = html.lstrip()[:200].lower()
    if head.startswith(("<!doctype", "<html")):
        return html
    title = f"<title>{escape(subject)}</title>" if subject else ""
    return (
        '<!doctype html>\n<html lang="de">\n<head><meta charset="utf-8">'
        f"{title}</head>\n<body>\n{html}\n</body>\n</html>\n"
    )


def from_address(name: str = "") -> str:
    """Absender: eigener Anzeigename vor der festen Absenderadresse."""
    name = " ".join((name or "").replace('"', "").replace("\\", "").split())[:120]
    if not name:
        return settings.DEFAULT_FROM_EMAIL
    # In Anführungszeichen, sonst gälten die Klammern als Kommentar; Django kodiert Umlaute
    return f'"{name}" <{parseaddr(settings.DEFAULT_FROM_EMAIL)[1]}>'


def send(
    to: list[str] | str,
    subject: str,
    body: str,
    *,
    organization=None,
    kind: str = "",
    attachments: list[tuple[str, bytes, str]] | None = None,
    reply_to: list[str] | None = None,
    fail_silently: bool = False,
    html: str = "",
    headers: dict[str, str] | None = None,
    stored_attachments: list[dict] | None = None,
    from_name: str = "",
) -> bool:
    """Sendet eine Mail. Gibt False zurück, wenn der Versand scheiterte (fail_silently).

    ``html``: zusätzlich als HTML. ``stored_attachments``: Anhänge, die schon im
    privaten Speicher liegen (``{"name", "path", "size", "content_type"}``, Pfad
    relativ zu PRIVATE_ROOT). Der Postausgang verweist dann auf diese Dateien,
    statt sie für jede Mail zu kopieren (Rundschreiben an viele Mitglieder).
    ``from_name``: angezeigter Absendername; die Adresse bleibt DEFAULT_FROM_EMAIL
    (nur für sie darf der Server unterschreiben, sonst scheitert DMARC).
    """
    recipients = [to] if isinstance(to, str) else list(to)
    headers = dict(headers or {})
    if organization is not None:
        headers[ORG_HEADER] = str(organization.pk)
    if kind:
        headers[KIND_HEADER] = kind
    footer = imprint_footer(organization)
    if footer:
        text, markup = footer
        body = f"{body.rstrip()}\n\n{text}\n"
        if html:
            html = (
                html.replace("</body>", f"{markup}</body>", 1)
                if "</body>" in html
                else html + markup
            )
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_address(from_name),
        to=recipients,
        reply_to=reply_to,
        headers=headers,
    )
    if html:
        message.attach_alternative(html_document(html, subject), "text/html")
    for name, content, mimetype in attachments or []:
        message.attach(name, content, mimetype)
    if stored_attachments:
        from core.privatefiles import read_private

        for item in stored_attachments:
            # Über den privaten Speicher lesen: entschlüsselt, falls die Datei verschlüsselt ist
            message.attach(item["name"], read_private(item["path"]), item["content_type"])
        message.outbox_attachments = [
            {k: v for k, v in item.items() if k != "abs"} for item in stored_attachments
        ]
    try:
        accepted = message.send()
    except Exception:  # noqa: BLE001
        if not fail_silently:
            raise
        logger.exception("Mail an %s konnte nicht gesendet werden", recipients)
        return False
    return bool(accepted)
