"""Rundschreiben prüfen, versenden und als Brief drucken."""

from __future__ import annotations

import datetime
import io
import logging
from xml.sax.saxutils import escape

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from core.tenancy import rls_bypass
from outbox import mail

from . import recipients as rcp
from . import text
from .models import MAX_SHORT_BODY, MAX_SHORT_PER_DAY, Circular, CircularRecipient

logger = logging.getLogger(__name__)

OPT_OUT_SALT = "circulars.optout"


# --- Abmeldung ---


def opt_out_token(membership_id: int) -> str:
    return signing.dumps({"m": membership_id}, salt=OPT_OUT_SALT, compress=True)


def opt_out_membership(token: str) -> int | None:
    try:
        data = signing.loads(token, salt=OPT_OUT_SALT)
    except signing.BadSignature:
        return None
    return data.get("m") if isinstance(data, dict) else None


def opt_out_url(membership_id: int) -> str:
    return f"{settings.FRONTEND_URL}/rundschreiben/abmelden/{opt_out_token(membership_id)}"


# --- Absender ---


def sender_name(circular: Circular) -> str:
    if circular.department_id:
        return circular.department.name
    return circular.organization.name


def letter_org(circular: Circular):
    """Briefkopf: der Verein bzw. Dachverband (Abteilungen schreiben im Briefkopf des Vereins)."""
    return circular.organization


def reply_to(circular: Circular, user=None) -> list[str]:
    address = circular.reply_to or getattr(circular.sent_by, "email", "") or ""
    if not address and user is not None:
        address = user.email
    return [address] if address else []


# --- Prüfen ---


def problems(circular: Circular) -> dict[str, str]:
    errors = {}
    if not circular.subject.strip():
        errors["subject"] = "Bitte einen Betreff eingeben."
    if not circular.body.strip():
        errors["body"] = "Bitte einen Text eingeben."
    if circular.kind == Circular.Kind.SHORT:
        if len(circular.body) > MAX_SHORT_BODY:
            errors["body"] = f"Eine Kurzmitteilung hat höchstens {MAX_SHORT_BODY} Zeichen."
        if circular.pk and circular.attachments.exists():
            errors["attachments"] = "Kurzmitteilungen haben keine Anhänge."
    unknown = text.unknown_placeholders(circular.subject, circular.body)
    if unknown:
        names = ", ".join("{" + u + "}" for u in unknown)
        known = ", ".join("{" + p + "}" for p in text.PLACEHOLDERS)
        errors["body"] = f"Unbekannte Platzhalter: {names}. Möglich sind {known}."
    return errors


def used_placeholders(circular: Circular) -> set[str]:
    found = text.PLACEHOLDER_RE.findall(f"{circular.subject}\n{circular.body}")
    return {f for f in found if f in text.PLACEHOLDERS}


# --- Inhalt ---


def unsubscribable(circular: Circular) -> bool:
    return circular.kind == Circular.Kind.INFO and circular.audience == Circular.Audience.MEMBERS


def from_name(circular: Circular, user=None) -> str:
    """Angezeigter Absender: „Person (Verein)“; ohne Konto die Adresse des Absenders."""
    org = sender_name(circular)
    person = circular.sent_by or circular.created_by or user
    who = (person.get_full_name().strip() or person.email) if person else circular.reply_to
    return f"{who} ({org})" if who else org


def mail_footer(circular: Circular, membership_id: int | None) -> tuple[str, str]:
    """Abmeldezeile als Text und HTML (nur bei Informationen an Mitglieder).

    Wer im Auftrag von wem schreibt, steht schon in der Fußzeile des Postausgangs.
    """
    plain: list[str] = []
    html: list[str] = []
    if unsubscribable(circular) and membership_id:
        url = opt_out_url(membership_id)
        plain.append(f"Keine Informationen mehr per E-Mail? Abmelden: {url}")
        html.append(
            f'Keine Informationen mehr per E-Mail? <a href="{escape(url)}">Hier abmelden</a>.'
        )
    return "\n".join(plain), "<br>".join(html)


def render_mail(circular: Circular, values: dict, membership_id: int | None) -> dict:
    subject = text.fill(circular.subject, values).replace("\n", " ").strip()
    body = text.fill(circular.body, values)
    foot_plain, foot_html = mail_footer(circular, membership_id)
    plain = f"{text.to_plain(body)}\n"
    foot = ""
    if foot_plain:
        plain = f"{plain}\n{foot_plain}\n"
        foot = f'<p style="margin-top:24px;font-size:12px;color:#666">{foot_html}</p>'
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5">'
        f"{text.to_html(body)}{foot}</div>"
    )
    headers = {}
    if unsubscribable(circular) and membership_id:
        headers["List-Unsubscribe"] = f"<{opt_out_url(membership_id)}>"
    return {"subject": subject[:300], "body": plain, "html": html, "headers": headers}


def stored_attachments(circular: Circular) -> list[dict]:
    """Anhänge für den Postausgang (Pfad relativ zum privaten Speicher)."""
    return [
        {
            "name": att.name,
            "path": att.file.name,
            "size": att.size,
            "content_type": "application/pdf",
        }
        for att in circular.attachments.all()
    ]


def deliver(recipient: CircularRecipient, circular: Circular, attachments: list[dict]) -> bool:
    content = render_mail(circular, recipient.values, recipient.membership_id)
    return mail.send(
        recipient.email,
        content["subject"],
        content["body"],
        html=content["html"],
        headers=content["headers"],
        organization=circular.organization,
        kind="rundschreiben",
        from_name=from_name(circular),
        reply_to=reply_to(circular) or None,
        stored_attachments=attachments,
        fail_silently=True,
    )


# --- Versand ---


@transaction.atomic
def start_sending(circular: Circular, user) -> dict[str, int]:
    """Empfänger festhalten und den Versand im Hintergrund anstoßen."""
    circular = Circular.objects.select_for_update().get(pk=circular.pk)
    if not circular.is_draft:
        raise serializers.ValidationError("Dieses Rundschreiben wurde bereits versendet.")
    errors = problems(circular)
    if errors:
        raise serializers.ValidationError(errors)
    if circular.kind == Circular.Kind.SHORT:
        check_short_limit(circular)
    selection = rcp.select(circular)
    chosen = selection.chosen
    from peering import packet_circulars

    remote = packet_circulars.remote_targets(circular)
    if not chosen and not remote:
        raise serializers.ValidationError("Für diese Auswahl gibt es keine Empfänger.")
    rcp.fill_values(circular, selection, used_placeholders(circular))
    now = timezone.now()
    rows = []
    for c in chosen:
        rows.append(
            CircularRecipient(
                organization_id=circular.organization_id,
                circular=circular,
                club=c.club,
                membership_id=c.membership_id,
                user_id=c.user_id,
                first_name=c.first_name[:100],
                last_name=c.last_name[:100],
                # Bei der App bleibt die Mail als Ersatz, falls kein Push ankommt
                email=c.email if c.channel in ("mail", "app") else "",
                address=c.address,
                values=c.values,
                channel=c.channel,
                status=INITIAL_STATUS[c.channel],
            )
        )
    CircularRecipient.objects.bulk_create(rows, batch_size=500)
    counts = {
        ch: sum(1 for r in rows if r.channel == ch) for ch in ("app", "mail", "letter", "portal")
    }
    mails = counts["mail"] + counts["app"]
    circular.status = Circular.Status.SENDING if mails else Circular.Status.SENT
    circular.sent_by = user
    circular.sent_at = now
    if not circular.reply_to and user is not None:
        circular.reply_to = user.email
    circular.save(update_fields=["status", "sent_by", "sent_at", "reply_to", "updated_at"])
    if remote:
        # Vereine auf anderen Instanzen verschicken selbst (Verbund, ohne Mailadressen)
        packet_circulars.forward(circular)
    if mails:
        from .tasks import send_circular

        transaction.on_commit(lambda: send_circular.delay(circular.pk))
    else:
        _after_sending(circular)
    return counts


INITIAL_STATUS = {
    "mail": CircularRecipient.Status.PENDING,
    "app": CircularRecipient.Status.PENDING,
    "letter": CircularRecipient.Status.LETTER,
    "portal": CircularRecipient.Status.PORTAL,
}


def check_short_limit(circular: Circular) -> None:
    """Schutz vor Versehen: höchstens MAX_SHORT_PER_DAY Kurzmitteilungen je Einheit und Tag."""
    since = timezone.now() - datetime.timedelta(days=1)
    sent = Circular.objects.filter(
        organization_id=circular.organization_id,
        department_id=circular.department_id,
        kind=Circular.Kind.SHORT,
        sent_at__gte=since,
    ).count()
    if sent >= MAX_SHORT_PER_DAY:
        raise serializers.ValidationError(
            f"Heute gingen schon {sent} Kurzmitteilungen hinaus (höchstens "
            f"{MAX_SHORT_PER_DAY} je Tag). Bitte morgen erneut oder als Rundschreiben."
        )


# --- Push an die App ---

PUSH_TEXT = 300


def push_data(recipient: CircularRecipient, circular: Circular, access_id: int) -> dict:
    """Inhalt der Push-Nachricht (wird für das Gerät verschlüsselt)."""
    body = text.to_plain(text.fill(circular.body, recipient.values)).strip()
    if len(body) > PUSH_TEXT:
        body = body[: PUSH_TEXT - 1].rstrip() + "…"
    return {
        "v": 1,
        "t": "circular",
        "access": access_id,
        "id": circular.pk,
        "kind": circular.kind,
        "title": text.fill(circular.subject, recipient.values).replace("\n", " ").strip()[:200],
        "text": body,
        "from": sender_name(circular),
    }


def deliver_app(recipient: CircularRecipient, circular: Circular) -> bool:
    from devices.push import send_to_user
    from portal.models import PortalAccess

    access = (
        PortalAccess.objects.filter(membership_id=recipient.membership_id)
        .values_list("pk", "user_id")
        .first()
    )
    if access is None:
        return False
    return send_to_user(access[1], push_data(recipient, circular, access[0])) > 0


def _after_sending(circular: Circular) -> None:
    """Verbund: weitergegebene Rundschreiben melden ihre Zahlen nach oben."""
    from peering import packet_circulars

    packet_circulars.after_sending(circular)


RATE_RESERVE = 0.1
RATE_RETRY_SECONDS = 5 * 60


def mail_budget() -> int | None:
    """Wie viele Rundschreiben-Mails jetzt noch gehen (``None``: ohne Grenze).

    Grenze ist ``MAIL_RATE_PER_HOUR`` (z. B. 100/h beim Hestia-Postfach); ein Zehntel
    bleibt frei für Anmelde- und Systemmails. Gezählt werden alle Mails der letzten
    Stunde im Postausgang.
    """
    limit = settings.MAIL_RATE_PER_HOUR
    if not limit:
        return None
    from outbox.models import OutgoingMail

    since = timezone.now() - datetime.timedelta(hours=1)
    with rls_bypass():
        used = OutgoingMail.objects.filter(created_at__gte=since).count()
    return max(0, int(limit * (1 - RATE_RESERVE)) - used)


def send_pending(circular_id: int) -> int:
    """Hintergrund: offene Mails eines Rundschreibens verschicken.

    Mit Stundengrenze (``MAIL_RATE_PER_HOUR``) geht nur so viel hinaus, wie die
    Grenze erlaubt; der Rest folgt in einem späteren Durchlauf.
    """
    sent = 0
    budget = mail_budget()
    with rls_bypass():
        circular = (
            Circular.objects.select_related("organization", "department", "sent_by")
            .filter(pk=circular_id)
            .first()
        )
        if circular is None:
            return 0
        attachments = stored_attachments(circular)
        pending = circular.recipients.filter(status=CircularRecipient.Status.PENDING)
        for recipient in pending.iterator(chunk_size=200):
            if budget is not None and budget <= 0:
                break
            # Erst vermerken, dann senden: lieber eine Mail zu wenig als doppelt
            claimed = CircularRecipient.objects.filter(
                pk=recipient.pk, status=CircularRecipient.Status.PENDING
            ).update(status=CircularRecipient.Status.SENDING, sent_at=timezone.now())
            if not claimed:
                continue
            if recipient.channel == CircularRecipient.Channel.APP:
                if deliver_app(recipient, circular):
                    sent += 1
                    error = ""
                    if circular.also_mail and recipient.email:
                        # Zusätzlich per Mail (zählt zur Stundengrenze)
                        if budget is not None:
                            budget -= 1
                        if not deliver(recipient, circular, attachments):
                            error = "Per App zugestellt; die zusätzliche Mail schlug fehl."
                    CircularRecipient.objects.filter(pk=recipient.pk).update(
                        status=CircularRecipient.Status.SENT, error=error
                    )
                    continue
                if not recipient.email:
                    CircularRecipient.objects.filter(pk=recipient.pk).update(
                        status=CircularRecipient.Status.FAILED,
                        error="Push nicht zustellbar; im Mitgliederbereich sichtbar.",
                    )
                    continue
                # Kein Gerät erreicht: Ersatz per Mail
                recipient.channel = CircularRecipient.Channel.MAIL
                CircularRecipient.objects.filter(pk=recipient.pk).update(
                    channel=CircularRecipient.Channel.MAIL
                )
            if budget is not None:
                budget -= 1
            ok = deliver(recipient, circular, attachments)
            if ok:
                sent += 1
                CircularRecipient.objects.filter(pk=recipient.pk).update(
                    status=CircularRecipient.Status.SENT
                )
            else:
                CircularRecipient.objects.filter(pk=recipient.pk).update(
                    status=CircularRecipient.Status.FAILED,
                    error="Versand fehlgeschlagen (siehe Postausgang).",
                )
        if not circular.recipients.filter(status=CircularRecipient.Status.PENDING).exists():
            Circular.objects.filter(pk=circular.pk).update(status=Circular.Status.SENT)
            circular.status = Circular.Status.SENT
            _after_sending(circular)
        elif budget is not None and not settings.CELERY_TASK_ALWAYS_EAGER:
            # Stundengrenze erreicht: später weiter
            from .tasks import send_circular

            send_circular.apply_async((circular.pk,), countdown=RATE_RETRY_SECONDS)
    logger.info("Rundschreiben %s: %s zugestellt", circular_id, sent)
    return sent


UNCLEAR_AFTER = datetime.timedelta(minutes=15)


def is_unclear(recipient: CircularRecipient, now: datetime.datetime | None = None) -> bool:
    """Mail seit über 15 Minuten beansprucht, ohne Ergebnis: Ob sie rausging, ist offen."""
    now = now or timezone.now()
    return (
        recipient.status == CircularRecipient.Status.SENDING
        and recipient.sent_at is not None
        and recipient.sent_at < now - UNCLEAR_AFTER
    )


STALLED_AFTER = datetime.timedelta(minutes=15)


def resume_stalled() -> int:
    """Rundschreiben mit wartenden Empfängern, deren Versand nicht weiterläuft, erneut
    anstoßen (Wiederanlauf nach verlorenem Hintergrundauftrag, Audit 31.10. R-CIR-01)."""
    from .tasks import send_circular

    cutoff = timezone.now() - STALLED_AFTER
    with rls_bypass():
        stalled = list(
            Circular.objects.filter(status=Circular.Status.SENDING, sent_at__lt=cutoff)
            .filter(recipients__status=CircularRecipient.Status.PENDING)
            .values_list("pk", flat=True)
            .distinct()
        )
    for pk in stalled:
        send_circular.delay(pk)
    return len(stalled)


@transaction.atomic
def resend(circular: Circular) -> int:
    """Fehlgeschlagene und unklare Mails erneut einreihen. Unklare können doppelt
    ankommen; das entscheidet der Vorstand bewusst."""
    cutoff = timezone.now() - UNCLEAR_AFTER
    again = circular.recipients.filter(
        channel__in=(CircularRecipient.Channel.MAIL, CircularRecipient.Channel.APP)
    ).filter(
        Q(status=CircularRecipient.Status.FAILED)
        | Q(status=CircularRecipient.Status.SENDING, sent_at__lt=cutoff)
    )
    count = again.update(status=CircularRecipient.Status.PENDING, error="", sent_at=None)
    # Noch nie gestartete Empfänger (Auftrag nach dem Speichern verloren) ebenfalls
    # anstoßen (Audit 31.10. R-CIR-01); der Versand beansprucht jeden Empfänger atomar
    waiting = circular.recipients.filter(status=CircularRecipient.Status.PENDING).count()
    if count or waiting:
        Circular.objects.filter(pk=circular.pk).update(status=Circular.Status.SENDING)
        from .tasks import send_circular

        transaction.on_commit(lambda: send_circular.delay(circular.pk))
    return count


def send_test(circular: Circular, user) -> str:
    """Probemail an den angemeldeten Benutzer, mit den Werten des ersten Empfängers."""
    errors = problems(circular)
    if errors:
        raise serializers.ValidationError(errors)
    if not user.email:
        raise serializers.ValidationError("Für dein Konto ist keine E-Mail-Adresse hinterlegt.")
    selection = rcp.select(circular)
    rcp.fill_values(circular, selection, used_placeholders(circular))
    first = selection.chosen[0] if selection.chosen else None
    values = first.values if first else {"Vorname": user.first_name, "Nachname": user.last_name}
    content = render_mail(circular, values, first.membership_id if first else None)
    mail.send(
        user.email,
        f"[Probe] {content['subject']}",
        content["body"],
        html=content["html"],
        organization=circular.organization,
        kind="rundschreiben-probe",
        from_name=from_name(circular, user),
        reply_to=reply_to(circular, user) or None,
        stored_attachments=stored_attachments(circular),
    )
    return user.email


# --- Serienbrief ---


def render_letters(circular: Circular, items: list[tuple[str, dict]]) -> bytes:
    """Briefe als ein PDF: je Empfänger (Anschrift, Werte) eine neue Seite."""
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        Paragraph,
        Spacer,
    )

    from letterhead.data import letter_data
    from letterhead.pdf import LetterDocument, text_styles

    data = letter_data(circular.department or letter_org(circular))
    st = text_styles(data)
    body_style = st["body"]
    date = timezone.localtime(circular.sent_at or timezone.now()).date()
    info = [
        *((label, value) for label, value in data.contact if label in ("Telefon", "E-Mail")),
        ("Datum", f"{date:%d.%m.%Y}"),
    ]
    attachments = [a.name for a in circular.attachments.all()]
    story: list = []
    for n, (address, values) in enumerate(items):
        story.extend(LetterDocument.start(data, address.splitlines(), info, n == 0))
        subject = text.fill(circular.subject, values)
        story.append(Paragraph(escape(subject), st["title"]))
        story.append(Spacer(1, 2 * mm))
        for block in text.blocks(text.fill(circular.body, values)):
            if block.kind == "p":
                story.append(
                    Paragraph("<br/>".join(text.inline_html(x) for x in block.lines), body_style)
                )
            else:
                story.append(
                    ListFlowable(
                        [ListItem(Paragraph(text.inline_html(x), body_style)) for x in block.lines],
                        bulletType="bullet" if block.kind == "ul" else "1",
                        start=None if block.kind == "ol" else "•",
                        leftIndent=12,
                    )
                )
        if circular.department_id:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(escape(circular.department.name), body_style))
        if attachments:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Anlagen: " + escape(", ".join(attachments)), st["small"]))
    if not story:
        story.append(
            Paragraph("Keine Briefe: alle Empfänger haben eine E-Mail-Adresse.", st["normal"])
        )
    buf = io.BytesIO()
    LetterDocument(
        buf,
        [data],
        title=circular.subject or "Rundschreiben",
        author=data.name,
    ).build(story)
    return buf.getvalue()


def letters_pdf(circular: Circular, preview: bool = False) -> bytes:
    if circular.is_draft or preview:
        selection = rcp.select(circular)
        letters = [c for c in selection.chosen if c.channel == "letter"]
        if preview and not letters:
            letters = selection.chosen[:1]
        letters = letters[:1] if preview else letters
        sel = rcp.Selection(letters, selection.jubilees)
        rcp.fill_values(circular, sel, used_placeholders(circular))
        return render_letters(circular, [(c.address, c.values) for c in letters])
    rows = circular.recipients.filter(channel=CircularRecipient.Channel.LETTER)
    return render_letters(circular, [(r.address, r.values) for r in rows])


def apply_list(circular: Circular) -> None:
    """Rundschreiben an einen Verteiler: Empfängerkreis und Auswahl aus dessen Muster
    übernehmen (so zählt immer die aktuelle Auswahl des Verteilers)."""
    ml = circular.mailing_list
    if ml is None:
        return
    pattern = ml.pattern
    filters = dict(pattern.filters or {})
    if circular.audience != pattern.audience or (circular.filters or {}) != filters:
        circular.audience = pattern.audience
        circular.filters = filters
        circular.save(update_fields=["audience", "filters", "updated_at"])
