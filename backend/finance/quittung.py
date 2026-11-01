"""Quittungen mit Unterschrift: Unterschreiben, Abschließen, Stornieren, Versenden.

Ablauf und Regeln: konzepte/digitale-quittung.md. Fachfragen entschieden von Ralf am
30.10.2026: Unterschrift der Gegenseite Pflicht (beim Eingang mit begründeter Ausnahme),
hinterlegte Kassierer-Unterschrift vorbelegt mit Bestätigung, Unterschrift nur auf dem Gerät
des Kassierers, offline unterschreiben in der App (Datum = Zeitpunkt der Unterschrift),
Versand per Mail, Umsatzsteuer nur bei Bedarf, Storno statt Löschen. Ist das Jahr der
Quittung schon abgeschlossen, wird das Storno ein Gegenbeleg im laufenden Jahr; Quittung,
Buchung und Abschluss des alten Jahres bleiben unverändert (Gesamtaudit 31.10.b, Frage 10).
"""

from __future__ import annotations

import datetime
import hashlib

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from . import services, signature
from .models import Account, Booking, CashReceipt, Receipt

# Wie weit eine offline geleistete Unterschrift zurückliegen darf
MAX_OFFLINE_AGE = datetime.timedelta(days=30)


def euro(value) -> str:
    from billing.pdf import euro as fmt

    return fmt(value)


def confirmation_text(receipt: CashReceipt) -> str:
    """Was die Gegenseite mit ihrer Unterschrift bestätigt (steht im Vollbild darüber)."""
    org = receipt.organization.name
    amount = euro(receipt.amount)
    if receipt.receives:
        text = f"Ich habe {amount} an {org} gezahlt."
    else:
        text = f"Ich habe {amount} von {org} erhalten."
    return f"{text} Zweck: {receipt.purpose}"


def person_name(user) -> str:
    return (user.get_full_name() or user.email).strip()


def clear_signatures(receipt: CashReceipt) -> None:
    receipt.treasurer_signature = None
    receipt.treasurer_user = None
    receipt.treasurer_name = ""
    receipt.treasurer_signed_at = None
    receipt.counterparty_signature = None
    receipt.counterparty_signed_at = None
    receipt.counterparty_confirmed = ""
    receipt.no_signature_reason = ""


def _when(signed_at) -> datetime.datetime:
    """Zeitpunkt der Unterschrift: jetzt, oder aus der App, wenn offline unterschrieben."""
    now = timezone.now()
    if signed_at is None:
        return now
    if signed_at > now + datetime.timedelta(minutes=5):
        raise ValidationError({"signed_at": gettext("Der Zeitpunkt liegt in der Zukunft.")})
    if signed_at < now - MAX_OFFLINE_AGE:
        raise ValidationError(
            {
                "signed_at": gettext(
                    "Die Unterschrift ist älter als 30 Tage. Bitte neu unterschreiben."
                )
            }
        )
    return signed_at


def _draft(receipt: CashReceipt) -> None:
    if receipt.status != CashReceipt.Status.DRAFT:
        raise ValidationError(
            gettext("Die Quittung ist abgeschlossen und lässt sich nicht mehr ändern.")
        )


def sign_treasurer(receipt: CashReceipt, user, *, strokes=None, use_stored=False, signed_at=None):
    _draft(receipt)
    if use_stored:
        stored = getattr(user, "stored_signature", None)
        if stored is None or not signature.is_valid(stored.strokes):
            raise ValidationError(gettext("Du hast keine Unterschrift hinterlegt."))
        shape = stored.strokes
    else:
        shape = signature.normalize(strokes)
    receipt.treasurer_signature = shape
    receipt.treasurer_user = user
    receipt.treasurer_name = person_name(user)
    receipt.treasurer_signed_at = _when(signed_at)


def sign_counterparty(receipt: CashReceipt, *, strokes, signed_at=None):
    _draft(receipt)
    receipt.counterparty_signature = signature.normalize(strokes)
    receipt.counterparty_signed_at = _when(signed_at)
    receipt.counterparty_confirmed = confirmation_text(receipt)[:500]
    receipt.no_signature_reason = ""


def without_counterparty(receipt: CashReceipt, reason: str):
    """Zahler unterschreibt nicht (nur wenn der Verein Geld erhält)."""
    _draft(receipt)
    reason = " ".join((reason or "").split())
    if not receipt.receives:
        raise ValidationError(
            gettext(
                "Bei einer Auszahlung muss der Empfänger unterschreiben: das ist der "
                "eigentliche Beleg."
            )
        )
    if len(reason) < 3:
        raise ValidationError(
            {"reason": gettext("Bitte kurz begründen, warum der Zahler nicht unterschreibt.")}
        )
    receipt.counterparty_signature = None
    receipt.counterparty_signed_at = None
    receipt.counterparty_confirmed = ""
    receipt.no_signature_reason = reason[:300]


def missing(receipt: CashReceipt) -> list[str]:
    """Was zum Abschluss noch fehlt (leer = bereit)."""
    result = []
    if not receipt.treasurer_signature:
        result.append("Unterschrift des Kassierers")
    if not receipt.counterparty_signature and not receipt.no_signature_reason:
        result.append(
            "Unterschrift des Zahlers" if receipt.receives else "Unterschrift des Empfängers"
        )
    return result


def validate_account(org, account: Account) -> None:
    if account.organization_id != org.pk or not account.is_active:
        raise ValidationError({"account": gettext("Unbekannte Kasse.")})
    if account.kind != Account.Kind.CASH:
        raise ValidationError({"account": gettext("Quittungen gibt es nur für eine Barkasse.")})


def _store_pdf(receipt: CashReceipt, booking: Booking, content: bytes, name: str, user):
    doc = Receipt(
        organization=receipt.organization,
        booking=booking,
        name=name,
        content_type="application/pdf",
        size=len(content),
        uploaded_by=user,
    )
    doc.file.save(name, ContentFile(content), save=False)
    doc.save()
    return doc, hashlib.sha256(content).hexdigest()


@transaction.atomic
def finalize(receipt: CashReceipt, user, *, confirmed: bool, signed_at=None) -> CashReceipt:
    """Abschluss: Buchung im Kassenbuch, Belegnummer, unveränderliches PDF als Beleg."""
    from billing import pdf
    from billing import services as billing_services

    receipt = CashReceipt.objects.select_for_update().get(pk=receipt.pk)
    _draft(receipt)
    org = receipt.organization
    if gaps := missing(receipt):
        raise ValidationError("Es fehlt noch: " + ", ".join(gaps) + ".")
    if receipt.treasurer_user_id != user.pk:
        raise ValidationError(
            gettext(
                "Abschließen kann nur, wer als Kassierer unterschrieben hat. Bitte "
                "selbst unterschreiben."
            )
        )
    if not confirmed:
        raise ValidationError(
            {
                "confirmed": gettext(
                    "Bitte bestätigen, dass du den Betrag erhalten bzw. ausgezahlt hast."
                )
            }
        )
    validate_account(org, receipt.account)
    when = receipt.counterparty_signed_at or receipt.treasurer_signed_at
    if signed_at is not None:
        when = _when(signed_at)
    date = timezone.localdate(when)
    services.ensure_open(org, date=date)
    year = org.fiscal_year_of(date)
    if receipt.invoice_id:
        payment = billing_services.add_payment(
            receipt.invoice,
            date=date,
            amount=receipt.amount,
            method="cash",
            account=receipt.account,
            user=user,
        )
        booking = payment.booking
        receipt.payment = payment
    else:
        booking = Booking(
            organization=org,
            year=year,
            number=services.next_number(org.pk, year),
            date=date,
            kind=Booking.Kind.INCOME if receipt.receives else Booking.Kind.EXPENSE,
            amount=receipt.amount,
            account=receipt.account,
            category=receipt.category,
            text=receipt.purpose[:200],
            reference="Quittung",
            counterparty=receipt.counterparty_name[:200],
            membership=receipt.membership,
            project=receipt.project,
            created_by=user,
        )
        booking.full_clean(exclude=["organization", "created_by"])
        booking.save()
    services.ensure_cash_ok([receipt.account], date)
    receipt.booking = booking
    receipt.number = booking.display_number
    receipt.receipt_date = date
    receipt.status = CashReceipt.Status.FINAL
    receipt.finalized_at = timezone.now()
    receipt.finalized_by = user
    content = pdf.render_cash_receipt(receipt)
    receipt.document, receipt.pdf_sha256 = _store_pdf(
        receipt, booking, content, pdf.cash_receipt_filename(receipt), user
    )
    receipt.save()
    return receipt


@transaction.atomic
def cancel(receipt: CashReceipt, user, reason: str) -> CashReceipt:
    """Storno: Gegenbuchung und neues PDF mit Vermerk. Die Quittung bleibt erhalten."""
    from billing import pdf
    from billing import services as billing_services

    receipt = CashReceipt.objects.select_for_update().get(pk=receipt.pk)
    if receipt.status != CashReceipt.Status.FINAL:
        raise ValidationError(gettext("Stornieren lassen sich nur abgeschlossene Quittungen."))
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise ValidationError({"reason": gettext("Bitte einen Grund für das Storno angeben.")})
    org = receipt.organization
    original = receipt.booking
    today = timezone.localdate()
    services.ensure_open(org, date=today)
    # Abgeschlossenes Ursprungsjahr: Gegenbeleg im laufenden Jahr, das alte Jahr bleibt
    old_year_closed = services.is_closed(org, original.year)
    if receipt.payment_id:
        # Die Rechnung ist wieder offen; Buchung und Beleg bleiben, die Gegenbuchung gleicht aus
        invoice = receipt.payment.invoice
        billing_services.lock_invoice(invoice)
        receipt.payment.delete()
        receipt.payment = None
        billing_services._update_paid(invoice)
    year = org.fiscal_year_of(today)
    counter = Booking(
        organization=org,
        year=year,
        number=services.next_number(org.pk, year),
        date=today,
        kind=Booking.Kind.EXPENSE if original.kind == Booking.Kind.INCOME else Booking.Kind.INCOME,
        amount=original.amount,
        account=original.account,
        # Gleiche Kategorie wie die Quittung, damit sich beides in der Auswertung aufhebt
        category=original.category,
        text=(
            f"Gegenbeleg zu Quittung {receipt.number} aus {org.fiscal_label(original.year)}: "
            f"{reason}"
            if old_year_closed
            else f"Storno Quittung {receipt.number}: {reason}"
        )[:200],
        reference=receipt.number,
        cancels=original,
        cancel_reason=reason[:300],
        counterparty=original.counterparty,
        membership=original.membership,
        department=original.department,
        project=original.project,
        created_by=user,
    )
    counter.save()
    services.ensure_cash_ok([original.account], today)
    receipt.status = CashReceipt.Status.CANCELLED
    receipt.cancel_booking = counter
    receipt.cancel_reason = reason[:300]
    receipt.cancelled_at = timezone.now()
    receipt.cancelled_by = user
    content = pdf.render_cash_receipt(receipt, cancelled=True)
    receipt.cancel_document, receipt.cancel_sha256 = _store_pdf(
        receipt, counter, content, pdf.cash_receipt_filename(receipt, cancelled=True), user
    )
    receipt.save()
    return receipt


def document_bytes(receipt: CashReceipt) -> tuple[bytes, str]:
    """Gespeichertes PDF (bei Storno das mit Vermerk), sonst die Entwurfsvorschau."""
    from billing import pdf

    doc = receipt.cancel_document or receipt.document
    if doc is None:
        return pdf.render_cash_receipt(receipt), pdf.cash_receipt_filename(receipt)
    with doc.file.open("rb") as fh:
        return fh.read(), doc.name


def send(receipt: CashReceipt, email: str | None = None) -> bool:
    from outbox import mail

    if receipt.status == CashReceipt.Status.DRAFT:
        raise ValidationError(gettext("Verschicken lässt sich erst die abgeschlossene Quittung."))
    address = (email or receipt.email or "").strip()
    if not address:
        raise ValidationError({"email": gettext("Bitte eine E-Mail-Adresse angeben.")})
    org = receipt.organization
    content, name = document_bytes(receipt)
    body = (
        "Guten Tag,\n\n"
        f"anbei erhalten Sie die Quittung {receipt.number} von {org.name} über "
        f"{euro(receipt.amount)}.\n\nZweck: {receipt.purpose}\n\n"
        f"Viele Grüße\n{org.name}\n"
    )
    sent = mail.send(
        address,
        f"Quittung {receipt.number} – {org.name}",
        body,
        organization=org,
        kind="quittung",
        attachments=[(name, content, "application/pdf")],
        reply_to=[org.contact_email] if org.contact_email else None,
        fail_silently=True,
    )
    if sent:
        receipt.email = address
        receipt.sent_at = timezone.now()
        receipt.save(update_fields=["email", "sent_at", "updated_at"])
    return sent
