"""Mailverteiler: Rundschreiben aus dem eigenen Mailprogramm.

Alle Mails an ``<adresse>@<Verteiler-Domain>`` landen in einem Sammelpostfach
(Catch-all beim eigenen Mailserver, z. B. Hestia). HUBIplan holt sie jede Minute
per IMAP ab (``fetch_inbound``) und verarbeitet sie (``process_message``):

1. Rückläufer, Abwesenheitsnotizen und eigene Mails werden still verworfen.
2. Die Empfängeradresse bestimmt den Verteiler (``MailingList``).
3. Der Absender muss ein Konto mit dem Recht „Rundschreiben versenden“ für die
   Einheit des Verteilers haben. Sonst: abgewiesen, ohne Antwort (keine Rückläufer
   an gefälschte Absender).
4. Aus Betreff, Text und PDF-Anhängen entsteht ein Rundschreiben mit den Empfängern
   des Verteilers.
5. Je nach Verteiler bekommt der Absender eine Mail mit Bestätigungslink (erst der
   Klick versendet; ein gefälschter Absender bekommt den Link nie) oder das
   Rundschreiben liegt als Entwurf in HUBIplan.

Antworten der Mitglieder gehen an den Absender (Antwort-an), nie an alle.
"""

from __future__ import annotations

import datetime
import imaplib
import logging
import re
import ssl
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid, parseaddr
from html.parser import HTMLParser

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from access.catalog import CIRCULARS_SEND, DEPT_CIRCULARS_SEND
from core.tenancy import rls_bypass
from outbox import mail
from outbox.backend import ORG_HEADER

from . import recipients as rcp
from . import services, text
from .models import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_BODY,
    Circular,
    CircularAttachment,
    InboundMail,
    MailingList,
)

logger = logging.getLogger(__name__)

CONFIRM_SALT = "circulars.inbound.confirm"
CONFIRM_DAYS = 7
MAX_RAW_BYTES = 25 * 1024 * 1024
FETCH_BATCH = 50
# Ohne eingetragene Domain (Testserver): Platzhalter für den Probe-Eingang
SIMULATION_DOMAIN = "verteiler.invalid"

LOCAL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
RESERVED = {
    "abuse",
    "admin",
    "hostmaster",
    "mailer-daemon",
    "no-reply",
    "noreply",
    "postmaster",
    "root",
    "webmaster",
}


# --- Adressen ---


def domains() -> list[str]:
    return list(settings.INBOUND_DOMAINS) or (
        [SIMULATION_DOMAIN] if settings.INBOUND_SIMULATION else []
    )


def address_of(ml: MailingList) -> str:
    found = domains()
    return f"{ml.local_part}@{found[0]}" if found else ""


def alias_addresses(ml: MailingList) -> list[str]:
    found = domains()
    return [f"{a}@{found[0]}" for a in ml.aliases or []] if found else []


MAX_ALIASES = 5
UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def plain_local(value: str) -> str:
    """Teil vor dem @, klein und ohne Umlaute („Schriftführer“ → „schriftfuehrer“)."""
    local = (value or "").strip().lower()
    if "@" in local:
        local = local.split("@", 1)[0]
    return local.translate(UMLAUTS)


def lists_with(local: str):
    """Verteiler, die diese Adresse als Haupt- oder weitere Adresse haben."""
    return MailingList.objects.filter(Q(local_part=local) | Q(aliases__contains=[local]))


def clean_local_part(
    value: str, current: MailingList | None = None, field: str = "local_part"
) -> str:
    local = plain_local(value)
    if not LOCAL_RE.match(local) or ".." in local:
        raise serializers.ValidationError(
            {
                field: f"„{value}“: nur Buchstaben, Ziffern, Punkt, Binde- und Unterstrich "
                "(nicht am Anfang oder Ende)."
            }
        )
    if local in RESERVED:
        raise serializers.ValidationError({field: f"„{local}“ ist reserviert."})
    with rls_bypass():
        taken = lists_with(local)
        if current is not None:
            taken = taken.exclude(pk=current.pk)
        if taken.exists():
            raise serializers.ValidationError({field: f"„{local}“ ist schon vergeben."})
    return local


def clean_aliases(values, current: MailingList | None, main: str) -> list[str]:
    if not isinstance(values, list):
        raise serializers.ValidationError({"aliases": "Ungültige Angabe."})
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        local = clean_local_part(value, current, field="aliases")
        if local != main and local not in out:
            out.append(local)
    if len(out) > MAX_ALIASES:
        raise serializers.ValidationError({"aliases": f"Höchstens {MAX_ALIASES} weitere Adressen."})
    return out


def find_list(addresses: list[str]) -> tuple[MailingList | None, str]:
    """Verteiler zur ersten passenden Empfängeradresse (``name+zusatz@`` zählt als ``name@``)."""
    accepted = set(domains())
    first = ""
    for address in addresses:
        local, _, domain = address.lower().rpartition("@")
        if not local or domain not in accepted:
            continue
        first = first or address.lower()
        # „schriftführer@“ (falls es ein Server zustellt) zählt wie „schriftfuehrer@“
        local = local.split("+", 1)[0].translate(UMLAUTS)
        ml = (
            lists_with(local)
            .select_related("organization", "department", "pattern")
            .filter(is_active=True)
            .first()
        )
        if ml is not None:
            return ml, address.lower()
    return None, first


# --- Wer darf an einen Verteiler schicken ---


def has_right(user, ml: MailingList) -> bool:
    """Hat das Konto das Recht „Rundschreiben versenden“ für die Einheit des Verteilers?"""
    from access.permissions import permissions_in
    from portal.services import department_contexts

    if user is None or not user.is_active:
        return False
    with rls_bypass():
        if CIRCULARS_SEND in permissions_in(user, ml.organization):
            return True
        if ml.department_id:
            ctx = department_contexts(user).get(ml.department_id)
            return ctx is not None and DEPT_CIRCULARS_SEND in ctx.permissions
    return False


def may_send(user, ml: MailingList) -> bool:
    """Darf das Konto an den Verteiler schreiben? Recht nötig; ist eine Auswahl von
    Absendern eingestellt, muss das Konto außerdem dazugehören."""
    if not has_right(user, ml):
        return False
    with rls_bypass():
        chosen = list(ml.senders.values_list("pk", flat=True))
    return not chosen or user.pk in chosen


def eligible_senders(ml: MailingList) -> list:
    """Konten, die das Recht für die Einheit des Verteilers haben (zur Auswahl)."""
    from access.models import RoleAssignment
    from portal.models import PortalAccess

    User = get_user_model()
    with rls_bypass():
        ids = set(
            RoleAssignment.objects.active()
            .filter(organization=ml.organization, user__isnull=False)
            .values_list("user_id", flat=True)
        )
        if ml.department_id:
            memberships = (
                RoleAssignment.all_objects.active()
                .filter(role__department_id=ml.department_id, membership__isnull=False)
                .values_list("membership_id", flat=True)
            )
            ids |= set(
                PortalAccess.objects.filter(membership_id__in=memberships).values_list(
                    "user_id", flat=True
                )
            )
        users = User.objects.filter(pk__in=ids, is_active=True).order_by(
            "last_name", "first_name", "email"
        )
        return [u for u in users if has_right(u, ml)]


def user_for(address: str):
    if not address:
        return None
    return get_user_model().objects.filter(email__iexact=address, is_active=True).first()


# --- Inhalt der Mail ---


class _HtmlText(HTMLParser):
    """HTML-Mail als einfacher Text (Absätze, Zeilenumbrüche, Listen, Links)."""

    BREAK = {"br"}
    BLOCK = {"p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
    SKIP = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.href: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BREAK:
            self.out.append("\n")
        elif tag in self.BLOCK:
            self.out.append("\n\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith(("http://", "https://", "mailto:")):
                self.href = href
                self.link_text = []
        elif tag in ("b", "strong"):
            self.out.append("**")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n\n")
        elif tag == "a" and self.href is not None:
            label = "".join(self.link_text).strip()
            href, self.href = self.href, None
            if label and label != href and not href.startswith("mailto:"):
                self.out.append(f"[{label}]({href})")
            else:
                self.out.append(label or href)
        elif tag in ("b", "strong"):
            self.out.append("**")

    def handle_data(self, data):
        if self.skip:
            return
        data = re.sub(r"\s+", " ", data)
        if self.href is not None:
            self.link_text.append(data)
        else:
            self.out.append(data)

    def text(self) -> str:
        return "".join(self.out)


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    result = parser.text().replace("****", "")
    # Leere Fettschrift (z. B. aus Signaturen) und Leerraum am Zeilenanfang entfernen
    result = re.sub(r"\*\*\s*\*\*", "", result)
    return "\n".join(line.strip() for line in result.splitlines())


def clean_body(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [line.rstrip() for line in value.split("\n")]
    value = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    # Geschweifte Klammern, die kein Platzhalter sind, bleiben als runde Klammern stehen
    def keep(m: re.Match) -> str:
        return m.group(0) if m.group(1) in text.PLACEHOLDERS else f"({m.group(1)})"

    return text.PLACEHOLDER_RE.sub(keep, value)


def body_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return clean_body(content)


@dataclass
class Extracted:
    subject: str
    body: str
    pdfs: list[tuple[str, bytes]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error: str = ""


def extract(msg: EmailMessage) -> Extracted:
    subject = re.sub(r"\s+", " ", str(msg.get("Subject", "") or "")).strip()[:200]
    body = body_of(msg)
    result = Extracted(subject, body)
    total = 0
    for part in msg.iter_attachments():
        name = (part.get_filename() or "").strip()
        if not name:
            continue  # eingebettete Bilder (Signatur, Logo)
        name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
        data = part.get_payload(decode=True) or b""
        if not data.startswith(b"%PDF-"):
            result.skipped.append(f"{name} (nur PDF möglich)")
            continue
        if len(data) > MAX_ATTACHMENT_BYTES or total + len(data) > 2 * MAX_ATTACHMENT_BYTES:
            result.skipped.append(f"{name} (zu groß)")
            continue
        if len(result.pdfs) >= MAX_ATTACHMENTS:
            result.skipped.append(f"{name} (höchstens {MAX_ATTACHMENTS} Anhänge)")
            continue
        total += len(data)
        result.pdfs.append((name, data))
    if not subject:
        result.error = "Die Mail hat keinen Betreff."
    elif not body:
        result.error = "Die Mail hat keinen Text."
    elif len(body) > MAX_BODY:
        result.error = f"Der Text ist länger als {MAX_BODY} Zeichen."
    return result


# --- Verarbeitung ---


def is_automatic(msg: EmailMessage) -> str:
    """Grund, warum die Mail automatisch entstand (Rückläufer, Abwesenheit, eigene Mail)."""
    auto = str(msg.get("Auto-Submitted", "") or "").strip().lower()
    if auto and auto != "no":
        return "automatische Mail"
    if str(msg.get("Precedence", "") or "").strip().lower() in ("bulk", "junk", "list"):
        return "Massen- oder Listenmail"
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"):
        return "automatische Antwort"
    if msg.get(ORG_HEADER):
        return "Mail von HUBIplan selbst"
    if str(msg.get("Return-Path", "") or "").strip() == "<>":
        return "Rückläufer"
    if msg.get_content_type() == "multipart/report":
        return "Rückläufer"
    sender = parseaddr(str(msg.get("From", "") or ""))[1].lower()
    local = sender.split("@", 1)[0]
    if local in ("mailer-daemon", "postmaster") or local.startswith(("noreply", "no-reply")):
        return "Absender ohne Postfach"
    own = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].lower()
    if own and sender == own:
        return "Mail von HUBIplan selbst"
    return ""


def spam_flagged(msg: EmailMessage) -> bool:
    """Hat der Spamfilter des Mailservers (SpamAssassin) die Mail markiert?"""
    flag = str(msg.get("X-Spam-Flag", "") or "").strip().lower()
    status = str(msg.get("X-Spam-Status", "") or "").strip().lower()
    return flag == "yes" or status.startswith("yes")


# Fremde Absender an offene Verteiler: höchstens so viele Mails je Tag und Verteiler
OPEN_PER_DAY = 3


def dmarc_failed(msg: EmailMessage) -> bool:
    """Hat der eigene Mailserver die Herkunft geprüft und abgelehnt (DMARC)?"""
    results = " ".join(str(v) for v in msg.get_all("Authentication-Results") or [])
    return bool(re.search(r"\bdmarc=fail\b", results, re.IGNORECASE))


def recipient_addresses(msg: EmailMessage) -> list[str]:
    headers = []
    for name in ("Delivered-To", "X-Original-To", "Envelope-To", "To", "Cc"):
        headers.extend(str(v) for v in msg.get_all(name) or [])
    return [a for _, a in getaddresses(headers) if a]


def _log(**kwargs) -> InboundMail:
    ml = kwargs.get("mailing_list")
    if ml is not None:
        kwargs.setdefault("organization", ml.organization)
    for key, limit in (("sender", 300), ("recipient", 300), ("subject", 300), ("reason", 300)):
        if key in kwargs:
            kwargs[key] = (kwargs[key] or "")[:limit]
    return InboundMail.objects.create(**kwargs)


def process_message(raw: bytes) -> InboundMail | None:
    """Eine eingegangene Mail verarbeiten. ``None``: schon verarbeitet (doppelt)."""
    with rls_bypass():
        return _process(raw)


def _process(raw: bytes) -> InboundMail | None:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = str(msg.get("Message-ID", "") or "").strip()[:300]
    if message_id and InboundMail.objects.filter(message_id=message_id).exists():
        return None
    sender = parseaddr(str(msg.get("From", "") or ""))[1].lower()
    subject = re.sub(r"\s+", " ", str(msg.get("Subject", "") or "")).strip()
    ml, recipient = find_list(recipient_addresses(msg))
    base = {
        "message_id": message_id,
        "sender": sender,
        "recipient": recipient,
        "subject": subject,
        "mailing_list": ml,
    }
    rejected = InboundMail.Status.REJECTED
    if len(raw) > MAX_RAW_BYTES:
        return _log(**base, status=rejected, reason="Mail zu groß.")
    automatic = is_automatic(msg)
    if automatic:
        return _log(**base, status=rejected, reason=f"Verworfen: {automatic}.")
    if ml is None:
        return _log(**base, status=rejected, reason="Kein Verteiler unter dieser Adresse.")
    if dmarc_failed(msg):
        return _log(**base, status=rejected, reason="Absender nicht echt (DMARC-Prüfung).")
    user = user_for(sender)
    # Offener Verteiler: wer sonst nicht darf, schreibt als fremder Absender (ohne Konto)
    stranger = not may_send(user, ml)
    if stranger and not ml.open_senders:
        reason = "Absender darf an diesen Verteiler nicht schreiben."
        return _log(**base, user=user, status=rejected, reason=reason)
    if stranger:
        user = None
        if spam_flagged(msg):
            return _log(**base, status=rejected, reason="Vom Spamfilter markiert.")
        since = timezone.now() - datetime.timedelta(days=1)
        recent = InboundMail.objects.filter(
            mailing_list=ml, sender=sender, received_at__gte=since
        ).exclude(status=rejected)
        if recent.count() >= OPEN_PER_DAY:
            reason = f"Mehr als {OPEN_PER_DAY} Mails an einem Tag von diesem Absender."
            return _log(**base, status=rejected, reason=reason)
    content = extract(msg)
    if content.error:
        entry = _log(**base, user=user, status=rejected, reason=content.error)
        if user is not None:
            notify_rejected(entry, content.error)
        return entry
    if stranger:
        # Ohne Bestätigung direkt an den Verteiler (Antworten gehen an den Absender)
        with transaction.atomic():
            circular = create_circular(ml, None, content, reply_to=sender)
            errors = services.problems(circular)
            count = len(rcp.select(circular).chosen) if not errors else 0
            if errors or not count:
                reason = (
                    " ".join(errors.values()) if errors else "Der Verteiler hat keine Empfänger."
                )
                delete_circular(circular)
                return _log(**base, status=rejected, reason=reason)
            if ml.mode == MailingList.Mode.DRAFT:
                return _log(**base, circular=circular, status=InboundMail.Status.DRAFT)
            services.start_sending(circular, None)
            return _log(**base, circular=circular, status=InboundMail.Status.SENT)
    with transaction.atomic():
        circular = create_circular(ml, user, content)
        errors = services.problems(circular)
        count = len(rcp.select(circular).chosen) if not errors else 0
        if errors or not count:
            reason = " ".join(errors.values()) if errors else "Der Verteiler hat keine Empfänger."
            delete_circular(circular)
            entry = _log(**base, user=user, status=rejected, reason=reason)
            transaction.on_commit(lambda: notify_rejected(entry, reason))
            return entry
        status = {
            MailingList.Mode.CONFIRM: InboundMail.Status.WAITING,
            MailingList.Mode.DIRECT: InboundMail.Status.SENT,
        }.get(ml.mode, InboundMail.Status.DRAFT)
        if status == InboundMail.Status.SENT:
            # Direkt: ohne Bestätigungslink; vor Fälschung schützt nur noch DMARC
            services.start_sending(circular, user)
        entry = _log(**base, user=user, circular=circular, status=status)
    if status == InboundMail.Status.WAITING:
        notify_confirm(entry, content.skipped)
    elif status == InboundMail.Status.SENT:
        notify_sent(entry, content.skipped)
    else:
        notify_draft(entry, content.skipped)
    return entry


def create_circular(ml: MailingList, user, content: Extracted, reply_to: str = "") -> Circular:
    pattern = ml.pattern
    circular = Circular.objects.create(
        organization=ml.organization,
        department=ml.department,
        kind=pattern.kind if pattern.kind != Circular.Kind.SHORT else Circular.Kind.INFO,
        audience=pattern.audience,
        filters=dict(pattern.filters or {}),
        via_app=pattern.via_app,
        also_mail=pattern.also_mail,
        subject=content.subject,
        body=content.body,
        reply_to=reply_to or user.email,
        created_by=user,
    )
    for name, data in content.pdfs:
        att = CircularAttachment(circular=circular, name=name, size=len(data))
        att.file.save(_safe_name(name), ContentFile(data), save=False)
        att.save()
    return circular


def _safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)
    return keep[-80:] or "anhang.pdf"


def delete_circular(circular: Circular) -> None:
    from core.files import delete_on_commit

    for att in circular.attachments.all():
        delete_on_commit(att.file)
    circular.delete()


# --- Bestätigung ---


def confirm_token(entry: InboundMail) -> str:
    return signing.dumps({"i": entry.pk}, salt=CONFIRM_SALT, compress=True)


def confirm_url(entry: InboundMail) -> str:
    return f"{settings.FRONTEND_URL}/rundschreiben/bestaetigen/{confirm_token(entry)}"


def entry_from_token(token: str) -> InboundMail | None:
    try:
        data = signing.loads(token, salt=CONFIRM_SALT, max_age=CONFIRM_DAYS * 24 * 60 * 60)
    except signing.BadSignature:
        return None
    pk = data.get("i") if isinstance(data, dict) else None
    if not isinstance(pk, int):
        return None
    with rls_bypass():
        return (
            InboundMail.objects.select_related(
                "mailing_list", "organization", "user", "circular", "circular__department"
            )
            .filter(pk=pk)
            .first()
        )


def confirm(entry: InboundMail) -> dict[str, int]:
    """Absender hat bestätigt: versenden (einmal; der Link gilt danach nicht mehr)."""
    with rls_bypass(), transaction.atomic():
        entry = InboundMail.objects.select_for_update().get(pk=entry.pk)
        if entry.status != InboundMail.Status.WAITING or entry.circular_id is None:
            raise serializers.ValidationError("Dieses Rundschreiben wurde schon bearbeitet.")
        if entry.mailing_list is None or not may_send(entry.user, entry.mailing_list):
            raise serializers.ValidationError("Du darfst an diesen Verteiler nicht mehr schreiben.")
        counts = services.start_sending(entry.circular, entry.user)
        entry.status = InboundMail.Status.SENT
        entry.save(update_fields=["status"])
    return counts


def discard(entry: InboundMail) -> None:
    with rls_bypass(), transaction.atomic():
        entry = InboundMail.objects.select_for_update().get(pk=entry.pk)
        if entry.status != InboundMail.Status.WAITING:
            raise serializers.ValidationError("Dieses Rundschreiben wurde schon bearbeitet.")
        if entry.circular is not None and entry.circular.is_draft:
            delete_circular(entry.circular)
        entry.circular = None
        entry.status = InboundMail.Status.REJECTED
        entry.reason = "Vom Absender verworfen."
        entry.save(update_fields=["circular", "status", "reason"])


# --- Antworten an den Absender ---


def _counts_text(circular: Circular) -> str:
    counts = rcp.select(circular).counts()
    parts = []
    if counts["app"]:
        parts.append(f"{counts['app']} per App")
    parts.append(f"{counts['mail']} per E-Mail")
    if counts["letter"]:
        parts.append(f"{counts['letter']} per Brief (zum Drucken in HUBIplan)")
    if counts["portal"]:
        parts.append(f"{counts['portal']} nur im Mitgliederbereich")
    return ", ".join(parts)


def _skipped_text(skipped: list[str]) -> str:
    if not skipped:
        return ""
    return "\n\nNicht übernommene Anhänge: " + "; ".join(skipped)


def _send(entry: InboundMail, subject: str, body: str) -> None:
    address = getattr(entry.user, "email", "")
    if not address:
        return
    mail.send(
        address,
        subject,
        body,
        organization=entry.organization,
        kind="verteiler",
        fail_silently=True,
        headers={"Auto-Submitted": "auto-replied"},
    )


def notify_confirm(entry: InboundMail, skipped: list[str]) -> None:
    ml = entry.mailing_list
    body = (
        f"Hallo,\n\ndeine Mail „{entry.subject}“ an den Verteiler {ml.name} "
        f"({address_of(ml)}) ist als Rundschreiben vorbereitet.\n\n"
        f"Empfänger: {_counts_text(entry.circular)}.\n\n"
        f"Erst wenn du bestätigst, geht es hinaus:\n{confirm_url(entry)}\n\n"
        f"Der Link gilt {CONFIRM_DAYS} Tage. Hast du die Mail nicht geschickt, "
        "ignoriere diese Nachricht einfach; dann wird nichts versendet."
        f"{_skipped_text(skipped)}\n"
    )
    _send(entry, f"Bitte bestätigen: {entry.subject}"[:300], body)


def notify_draft(entry: InboundMail, skipped: list[str]) -> None:
    ml = entry.mailing_list
    body = (
        f"Hallo,\n\ndeine Mail „{entry.subject}“ an den Verteiler {ml.name} "
        f"({address_of(ml)}) liegt als Entwurf in HUBIplan unter Rundschreiben.\n\n"
        f"Empfänger: {_counts_text(entry.circular)}.\n\n"
        f"Versendet wird erst dort: {settings.FRONTEND_URL}/rundschreiben/{entry.circular_id}"
        f"{_skipped_text(skipped)}\n"
    )
    _send(entry, f"Als Entwurf abgelegt: {entry.subject}"[:300], body)


def notify_sent(entry: InboundMail, skipped: list[str]) -> None:
    ml = entry.mailing_list
    body = (
        f"Hallo,\n\ndeine Mail „{entry.subject}“ an den Verteiler {ml.name} "
        f"({address_of(ml)}) wird jetzt versendet.\n\n"
        f"Empfänger: {_counts_text(entry.circular)}.\n\n"
        f"Stand und Briefe in HUBIplan: "
        f"{settings.FRONTEND_URL}/rundschreiben/{entry.circular_id}\n\n"
        "Hast du die Mail nicht geschickt, melde dich bitte sofort beim Vorstand."
        f"{_skipped_text(skipped)}\n"
    )
    _send(entry, f"Versendet: {entry.subject}"[:300], body)


def notify_rejected(entry: InboundMail, reason: str) -> None:
    ml = entry.mailing_list
    body = (
        f"Hallo,\n\ndeine Mail „{entry.subject or '(ohne Betreff)'}“ an den Verteiler "
        f"{ml.name if ml else ''} wurde nicht versendet:\n\n{reason}\n\n"
        "Bitte korrigieren und erneut schicken.\n"
    )
    _send(entry, f"Nicht versendet: {entry.subject or 'Rundschreiben'}"[:300], body)


# --- Probe ohne Sammelpostfach (Testserver) ---


def simulate(ml: MailingList, user, subject: str, body: str) -> InboundMail | None:
    msg = EmailMessage()
    msg["From"] = user.email
    msg["To"] = address_of(ml) or f"{ml.local_part}@{SIMULATION_DOMAIN}"
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="hubiplan.probe")
    msg.set_content(body)
    return process_message(msg.as_bytes())


# --- Abholen per IMAP ---

LOCK = "circulars:inbound:fetch"


def fetch_inbound() -> int:
    """Neue Mails aus dem Sammelpostfach abholen und verarbeiten. Gibt die Anzahl zurück."""
    if not settings.INBOUND_IMAP_HOST:
        return 0
    if not cache.add(LOCK, 1, timeout=10 * 60):
        return 0  # läuft schon
    done = 0
    try:
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL(
            settings.INBOUND_IMAP_HOST,
            settings.INBOUND_IMAP_PORT,
            ssl_context=context,
            timeout=60,
        ) as imap:
            imap.login(settings.INBOUND_IMAP_USER, settings.INBOUND_IMAP_PASSWORD)
            imap.select(settings.INBOUND_IMAP_FOLDER)
            _, found = imap.uid("search", None, "UNSEEN")
            uids = (found[0] or b"").split()[:FETCH_BATCH]
            for uid in uids:
                _, parts = imap.uid("fetch", uid, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw is None:
                    continue
                try:
                    process_message(raw)
                    flag = "(\\Deleted)"
                    done += 1
                except Exception:  # noqa: BLE001
                    # Bleibt (gelesen) im Postfach, damit man sie sich ansehen kann
                    logger.exception("Verteiler: Mail %s nicht verarbeitet", uid)
                    flag = "(\\Seen)"
                imap.uid("store", uid, "+FLAGS", flag)
            imap.expunge()
    except (OSError, imaplib.IMAP4.error):
        logger.exception("Verteiler: Sammelpostfach nicht erreichbar")
    finally:
        cache.delete(LOCK)
    return done
