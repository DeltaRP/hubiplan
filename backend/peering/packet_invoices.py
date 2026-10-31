"""Rechnungen zwischen gekoppelten Einheiten (P8) und Zahlungsstand (P9).

Anders als die übrigen Pakete sind Rechnungen kein Stand, sondern einzelne
Vorgänge: Die obere Einheit schreibt eine Rechnung an einen fernen Verein fest
(``invoice.issue``, mit PDF und Positionen), storniert sie (``invoice.cancel``)
oder bucht Zahlungen (``invoice.status``). Der Verein sieht sie als
Eingangsrechnung, kann sie in der eigenen Kasse als Ausgabe buchen und meldet
„bezahlt am …“ zurück (``invoice.paid``). Maßgeblich für den Ausgleich bleibt der
Zahlungseingang beim Aussteller.

Personenbezug: keiner, Empfänger ist die Einheit.
"""

from __future__ import annotations

import base64
import datetime
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from core.files import delete_on_commit

from .models import Coupling, RemoteInvoice
from .packets import DOWN, Packet, register

KEY = "invoices"
PDF_LIMIT = 8 * 1024 * 1024


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _date(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# --- Aussteller (obere Einheit) ---


def _coupling_for(invoice) -> Coupling | None:
    """Kopplung, über die eine Rechnung an einen fernen Verein geht (sonst None)."""
    from billing.models import Invoice

    if invoice.recipient_kind != Invoice.Recipient.CLUB or invoice.club_id is None:
        return None
    club = invoice.club
    if not club.is_remote:
        return None
    coupling = Coupling.objects.filter(remote_unit_id=club.pk).first()
    if (
        coupling is None
        or coupling.direction != Coupling.Direction.CHILD
        or not coupling.is_open
        or not coupling.level(KEY)
    ):
        return None
    return coupling


def _issue_data(invoice, uid: str) -> dict:
    from billing import pdf
    from billing.services import settings_for

    account = settings_for(invoice.organization).account
    try:
        content = pdf.render([invoice])
    except Exception:  # noqa: BLE001 - die Rechnung geht auch ohne PDF raus
        content = b""
    return {
        "uid": uid,
        "number": invoice.display_number,
        "subject": invoice.subject,
        "date": invoice.date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "total": str(invoice.total),
        "note": invoice.note,
        "lines": [
            {"text": line.text, "detail": line.detail, "amount": str(line.amount)}
            for line in invoice.lines.order_by("position")
        ],
        "bank": {
            "holder": invoice.organization.name,
            "iban": account.iban if account else "",
            "bic": account.bic if account else "",
            "bank_name": account.bank_name if account else "",
        },
        "pdf": base64.b64encode(content).decode() if 0 < len(content) <= PDF_LIMIT else None,
    }


def on_finalize(invoice) -> None:
    """Festgeschriebene Rechnung an einen fernen Verein senden."""
    from . import services

    coupling = _coupling_for(invoice)
    if coupling is None:
        return
    remote, _ = RemoteInvoice.objects.update_or_create(
        invoice=invoice,
        defaults={
            "coupling": coupling,
            "uid": uuid.uuid4().hex,
            "number": invoice.display_number,
            "subject": invoice.subject[:200],
            "date": invoice.date,
            "due_date": invoice.due_date,
            "total": invoice.total,
            "status": RemoteInvoice.Status.OPEN,
        },
    )
    services.enqueue(coupling, "invoice.issue", _issue_data(invoice, remote.uid))


def _sent(invoice) -> RemoteInvoice | None:
    remote = RemoteInvoice.objects.filter(invoice=invoice).select_related("coupling").first()
    if remote is None or not remote.coupling.is_open:
        return None
    return remote


def on_cancel(invoice) -> None:
    from . import services

    remote = _sent(invoice)
    if remote is None:
        return
    remote.status = RemoteInvoice.Status.CANCELLED
    remote.save(update_fields=["status", "updated_at"])
    services.enqueue(remote.coupling, "invoice.cancel", {"uid": remote.uid})


def on_paid_changed(invoice) -> None:
    """Zahlungsstand (P9) an den Verein melden, wenn sich ``paid`` geändert hat."""
    from . import services

    remote = _sent(invoice)
    if remote is None:
        return
    paid = str(invoice.paid)
    if (remote.data or {}).get("paid") == paid:
        return
    remote.data = {**(remote.data or {}), "paid": paid}
    remote.save(update_fields=["data", "updated_at"])
    services.enqueue(
        remote.coupling,
        "invoice.status",
        {"uid": remote.uid, "paid": paid, "settled": invoice.paid >= invoice.total},
    )


# --- Empfänger (untere Einheit) ---


def receive(coupling: Coupling, kind: str, data: dict) -> None:
    uid = str(data.get("uid") or "")[:80]
    if not uid:
        raise ValidationError("Rechnung ohne Kennung.")
    if kind == "invoice.issue":
        if coupling.direction != Coupling.Direction.PARENT:
            raise ValidationError("Rechnungen kommen nur von der Einheit darüber.")
        _receive_issue(coupling, uid, data)
        return
    remote = RemoteInvoice.objects.filter(coupling=coupling, uid=uid).first()
    if remote is None:
        raise ValidationError("Rechnung unbekannt.")
    if kind == "invoice.cancel" and coupling.direction == Coupling.Direction.PARENT:
        remote.status = RemoteInvoice.Status.CANCELLED
        remote.save(update_fields=["status", "updated_at"])
    elif kind == "invoice.status" and coupling.direction == Coupling.Direction.PARENT:
        remote.data = {
            **(remote.data or {}),
            "paid": str(_money(data.get("paid"))),
            "settled": bool(data.get("settled")),
        }
        remote.save(update_fields=["data", "updated_at"])
    elif kind == "invoice.paid" and coupling.direction == Coupling.Direction.CHILD:
        remote.paid_reported_on = _date(data.get("date")) or timezone.localdate()
        remote.save(update_fields=["paid_reported_on", "updated_at"])
        from .services import _audit

        _audit(
            coupling,
            None,
            f"Rechnung {remote.number} als bezahlt gemeldet",
            **{"bezahlt am": remote.paid_reported_on.isoformat()},
        )
    else:
        raise ValidationError("Unpassende Rechnungsmeldung.")


def _receive_issue(coupling: Coupling, uid: str, data: dict) -> None:
    lines = []
    for line in (data.get("lines") or [])[:200]:
        if isinstance(line, dict):
            lines.append(
                {
                    "text": str(line.get("text") or "")[:300],
                    "detail": str(line.get("detail") or "")[:200],
                    "amount": str(_money(line.get("amount"))),
                }
            )
    bank = data.get("bank") if isinstance(data.get("bank"), dict) else {}
    remote, _ = RemoteInvoice.objects.update_or_create(
        coupling=coupling,
        uid=uid,
        defaults={
            "number": str(data.get("number") or "")[:40],
            "subject": str(data.get("subject") or "")[:200],
            "date": _date(data.get("date")),
            "due_date": _date(data.get("due_date")),
            "total": _money(data.get("total")),
            "status": RemoteInvoice.Status.OPEN,
            "data": {
                "note": str(data.get("note") or "")[:2000],
                "lines": lines,
                "bank": {
                    k: str(bank.get(k) or "")[:100] for k in ("holder", "iban", "bic", "bank_name")
                },
                "paid": "0.00",
                "settled": False,
            },
        },
    )
    content = b""
    if data.get("pdf"):
        try:
            content = base64.b64decode(str(data["pdf"]), validate=True)
        except (ValueError, TypeError):
            content = b""
    if content.startswith(b"%PDF") and len(content) <= PDF_LIMIT:
        delete_on_commit(remote.file)  # erst nach dem Commit (INF-F02)
        remote.file.save(f"{uid}.pdf", ContentFile(content), save=True)


@transaction.atomic
def report_paid(remote: RemoteInvoice, *, date, account=None, category=None, user=None):
    """Eingangsrechnung als bezahlt melden, auf Wunsch mit Ausgabe in der eigenen Kasse."""
    from finance import services as finance_services
    from finance.models import Booking, Receipt

    from . import services

    # Gesperrt und frisch gelesen: Ein zweiter (auch gleichzeitiger) Klick legt keine
    # zweite Ausgabe an (Gesamtaudit 31.10.b, INF-F06)
    remote = RemoteInvoice.objects.select_for_update().select_related("coupling").get(pk=remote.pk)
    if remote.paid_reported_on is not None:
        raise ValidationError(
            f"Die Rechnung wurde am {remote.paid_reported_on:%d.%m.%Y} schon als bezahlt gemeldet."
        )
    coupling = remote.coupling
    if coupling.direction != Coupling.Direction.PARENT:
        raise ValidationError("Nur Eingangsrechnungen lassen sich als bezahlt melden.")
    if remote.status != RemoteInvoice.Status.OPEN:
        raise ValidationError("Die Rechnung ist storniert.")
    if not coupling.is_open:
        raise ValidationError("Die Kopplung ist nicht aktiv.")
    org = coupling.local_unit
    booking = None
    if account is not None:
        if account.organization_id != org.pk:
            raise ValidationError("Bitte ein Konto dieser Einheit wählen.")
        if category is None or category.organization_id != org.pk:
            raise ValidationError("Bitte eine Kategorie wählen.")
        if not category.allows(Booking.Kind.EXPENSE):
            raise ValidationError("Die Kategorie ist nicht für Ausgaben vorgesehen.")
        finance_services.ensure_open(org, date=date)
        year = org.fiscal_year_of(date)
        booking = Booking(
            organization=org,
            year=year,
            number=finance_services.next_number(org.pk, year),
            date=date,
            kind=Booking.Kind.EXPENSE,
            amount=remote.total,
            account=account,
            category=category,
            text=f"Rechnung {remote.number} {coupling.remote_unit.name}"[:200],
            reference=remote.number[:100],
            counterparty=coupling.remote_unit.name[:200],
            created_by=user,
        )
        booking.full_clean(exclude=["organization", "created_by"])
        booking.save()
        if remote.file:
            remote.file.open("rb")
            try:
                content = remote.file.read()
            finally:
                remote.file.close()
            name = f"Rechnung-{remote.number or remote.uid}.pdf"
            Receipt.objects.create(
                organization=org,
                booking=booking,
                file=ContentFile(content, name=name),
                name=name,
                content_type="application/pdf",
                size=len(content),
                uploaded_by=user,
            )
    remote.paid_reported_on = date
    remote.data = {**(remote.data or {}), "booking_id": booking.pk if booking else None}
    remote.save(update_fields=["paid_reported_on", "data", "updated_at"])
    services.enqueue(coupling, "invoice.paid", {"uid": remote.uid, "date": date.isoformat()})
    services._audit(coupling, user, f"Rechnung {remote.number} als bezahlt gemeldet")
    return booking


def invoice_data(remote: RemoteInvoice) -> dict:
    data = remote.data or {}
    coupling = remote.coupling
    return {
        "id": remote.id,
        "incoming": coupling.direction == Coupling.Direction.PARENT,
        "number": remote.number,
        "subject": remote.subject,
        "date": remote.date,
        "due_date": remote.due_date,
        "total": str(remote.total),
        "status": remote.status,
        "status_label": remote.get_status_display(),
        "paid": data.get("paid") if remote.invoice is None else str(remote.invoice.paid),
        "settled": bool(data.get("settled"))
        if remote.invoice is None
        else remote.invoice.paid >= remote.invoice.total,
        "paid_reported_on": remote.paid_reported_on,
        "booking_id": data.get("booking_id"),
        "lines": data.get("lines") or [],
        "bank": data.get("bank") or {},
        "invoice_id": remote.invoice_id,
        "download_url": (
            f"/api/orgs/{coupling.local_unit_id}/peering/couplings/{coupling.pk}"
            f"/invoices/{remote.pk}/file/"
        )
        if remote.file
        else None,
    }


register(
    Packet(
        KEY,
        "Rechnungen an die Einheit darunter (mit PDF und Zahlungsstand)",
        (DOWN,),
        personal="keiner (Empfänger ist die Einheit)",
        default="on",
    )
)
