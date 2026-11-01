"""Ende der Aufbewahrungsfrist (Finanzamt-Prüfung C6).

Nach § 147 AO (Fassung ab 2025) sind Buchungsbelege 8 Jahre, Bücher und Abschlüsse
10 Jahre aufzubewahren, jeweils ab dem Ende des Kalenderjahres, in dem das Geschäftsjahr
endet. Danach dürfen (und nach der DSGVO sollen) die personenbezogenen Daten weg.

Zwei Stufen je abgeschlossenem Geschäftsjahr, beide von Hand ausgelöst:

1. **Belege** (ab Beginn des 9. Jahres): Belegdateien, archivierte Rechnungs-, Quittungs-,
   Zuwendungs- und Zählprotokoll-PDFs, Kontoauszugsdateien, SEPA-Dateien und
   Unterschriften werden gelöscht.
2. **Bücher** (ab Beginn des 11. Jahres): Namen, Anschriften, Texte und Bankdaten werden
   anonymisiert. Beträge, Daten, Konten, Kategorien und Nummern bleiben, damit Bestände und
   Vorjahresvergleiche weiter stimmen. Protokolleinträge dieser Daten werden geleert
   (die Protokollkette bleibt prüfbar).
"""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

ANON = "anonymisiert"
DOCUMENT_YEARS = 8
RECORD_YEARS = 10


def due_dates(org, year: int) -> tuple[datetime.date, datetime.date]:
    """Ab wann Belege bzw. Bücher des Geschäftsjahres weg dürfen."""
    end = org.fiscal_range(year)[1]
    return (
        datetime.date(end.year + DOCUMENT_YEARS + 1, 1, 1),
        datetime.date(end.year + RECORD_YEARS + 1, 1, 1),
    )


def _today() -> datetime.date:
    return timezone.localdate()


def state(org, closing) -> dict:
    today = _today()
    docs_from, records_from = due_dates(org, closing.year)
    return {
        "documents_from": docs_from,
        "records_from": records_from,
        "documents_purged_at": closing.documents_purged_at,
        "records_purged_at": closing.records_purged_at,
        "purged_by": closing.purged_by_name,
        "documents_due": closing.documents_purged_at is None and today >= docs_from,
        "records_due": closing.records_purged_at is None and today >= records_from,
    }


def _delete_file(field) -> None:
    """Datei erst nach dem Commit löschen: Rollt die Bereinigung zurück, bleibt der Beleg
    (Gesamtaudit 01.11., GA-F07)."""
    from core.files import delete_on_commit

    delete_on_commit(field)


def _purge_documents(org, start, end) -> dict[str, int]:
    from billing.models import DebitRun, Invoice

    from .models import BankStatement, Booking, CashCount, CashReceipt, DonationStatement, Receipt

    counts: dict[str, int] = {}
    bookings = Booking.objects.filter(organization=org, date__gte=start, date__lte=end)
    receipts = Receipt.objects.filter(organization=org, booking__in=bookings)
    # Quittungen verweisen auf ihre PDFs (RESTRICT): Verweise und Unterschriften zuerst
    cash = CashReceipt.objects.filter(organization=org, booking__in=bookings)
    counts["Unterschriften"] = cash.update(
        document=None, cancel_document=None, treasurer_signature=None, counterparty_signature=None
    )
    cash_other = CashReceipt.objects.filter(
        organization=org, cancel_document__in=receipts
    ) | CashReceipt.objects.filter(organization=org, document__in=receipts)
    cash_other.update(document=None, cancel_document=None)
    n = 0
    for r in receipts:
        _delete_file(r.file)
        n += 1
    receipts.delete()
    counts["Belege"] = n

    n = 0
    for i in Invoice.objects.filter(organization=org, date__gte=start, date__lte=end).exclude(
        issued_pdf=""
    ):
        _delete_file(i.issued_pdf)
        i.issued_pdf = ""
        i.save(update_fields=["issued_pdf"])
        n += 1
    counts["Rechnungs-PDFs"] = n

    n = 0
    for s in DonationStatement.objects.filter(
        organization=org, issued_on__gte=start, issued_on__lte=end
    ).exclude(file=""):
        _delete_file(s.file)
        s.file = ""
        s.save(update_fields=["file"])
        n += 1
    counts["Zuwendungsbestätigungen"] = n

    n = 0
    for cc in CashCount.objects.filter(organization=org, date__gte=start, date__lte=end).exclude(
        pdf=""
    ):
        _delete_file(cc.pdf)
        cc.pdf = ""
        cc.save(update_fields=["pdf"])
        n += 1
    counts["Zählprotokolle"] = n

    n = 0
    for st in BankStatement.objects.filter(
        organization=org, date_to__gte=start, date_to__lte=end
    ).exclude(source=""):
        _delete_file(st.source)
        st.source = ""
        st.save(update_fields=["source"])
        n += 1
    counts["Kontoauszugsdateien"] = n

    counts["SEPA-Dateien"] = (
        DebitRun.objects.filter(
            organization=org, collection_date__gte=start, collection_date__lte=end
        )
        .exclude(xml="")
        .update(xml="")
    )
    return counts


def _anonymize_records(org, start, end) -> dict[str, int]:
    from audit.log import OBJECT_TYPES
    from audit.models import AuditEntry
    from billing.models import Dunning, Invoice

    from .models import (
        BankLine,
        Booking,
        CashCount,
        CashReceipt,
        Donation,
        DonationStatement,
        ReserveMovement,
    )

    counts: dict[str, int] = {}
    touched: dict[str, list] = {}

    def ids(qs, label):
        touched[label] = [str(pk) for pk in qs.values_list("pk", flat=True)]
        return qs

    bookings = ids(
        Booking.objects.filter(organization=org, date__gte=start, date__lte=end), "booking"
    )
    counts["Buchungen"] = bookings.update(
        text=ANON, counterparty="", reference="", membership=None, cancel_reason=""
    )
    invoices = ids(
        Invoice.objects.filter(organization=org, date__gte=start, date__lte=end), "invoice"
    )
    Dunning.objects.filter(invoice__in=invoices).update(text="")
    counts["Rechnungen"] = invoices.update(
        recipient_name=ANON, recipient_address="", recipient_email="", note="", membership=None
    )
    counts["Quittungen"] = ids(
        CashReceipt.objects.filter(organization=org, booking__in=bookings), "cashreceipt"
    ).update(
        counterparty_name=ANON,
        counterparty_address="",
        email="",
        purpose=ANON,
        membership=None,
        counterparty_confirmed="",
        no_signature_reason="",
        cancel_reason="",
        treasurer_signature=None,
        counterparty_signature=None,
    )
    counts["Zuwendungen"] = ids(
        Donation.objects.filter(organization=org, date__gte=start, date__lte=end), "donation"
    ).update(donor_name=ANON, donor_address="", note="", membership=None)
    counts["Zuwendungsbestätigungen"] = ids(
        DonationStatement.objects.filter(
            organization=org, issued_on__gte=start, issued_on__lte=end
        ),
        "donationstatement",
    ).update(donor_name=ANON, donor_address="", membership=None, items=[], cancel_reason="")
    counts["Kontoumsätze"] = ids(
        BankLine.objects.filter(organization=org, date__gte=start, date__lte=end), "bankline"
    ).update(name="", iban="", purpose="", details=[], suggested_membership=None)
    counts["Kassenzählungen"] = ids(
        CashCount.objects.filter(organization=org, date__gte=start, date__lte=end), "cashcount"
    ).update(counted_by=ANON, witness="", note="")
    counts["Rücklagenbewegungen"] = ids(
        ReserveMovement.objects.filter(organization=org, date__gte=start, date__lte=end),
        "reservemovement",
    ).update(note="", created_by_name="", created_by=None)

    # Protokolleinträge dieser Daten leeren (Kette bleibt prüfbar, siehe audit/chain.py)
    cleared = 0
    for model, pks in touched.items():
        if pks:
            cleared += AuditEntry.objects.filter(
                organization=org, object_type=OBJECT_TYPES.get(model, model), object_id__in=pks
            ).update(changes={}, object_repr=ANON, cleared=True)
    counts["Protokolleinträge"] = cleared
    return counts


@transaction.atomic
def purge(org, year: int, user) -> dict:
    """Führt aus, was für das Geschäftsjahr fällig ist; gibt die Anzahlen zurück."""
    from audit.log import record

    from .models import YearClosing

    closing = YearClosing.objects.select_for_update().filter(organization=org, year=year).first()
    if closing is None:
        raise ValidationError("Nur abgeschlossene Geschäftsjahre lassen sich bereinigen.")
    info = state(org, closing)
    if not (info["documents_due"] or info["records_due"]):
        raise ValidationError(
            f"Die Aufbewahrungsfrist läuft noch: Belege ab {info['documents_from']:%d.%m.%Y}, "
            f"Bücher ab {info['records_from']:%d.%m.%Y}."
        )
    start, end = org.fiscal_range(year)
    counts: dict[str, int] = {}
    now = timezone.now()
    if info["documents_due"]:
        counts.update(_purge_documents(org, start, end))
        closing.documents_purged_at = now
    if info["records_due"]:
        counts.update(_anonymize_records(org, start, end))
        closing.records_purged_at = now
    closing.purged_by_name = (user.get_full_name() or user.email)[:200]
    closing.save(update_fields=["documents_purged_at", "records_purged_at", "purged_by_name"])
    what = "Belege gelöscht" if not info["records_due"] else "Belege gelöscht, Bücher anonymisiert"
    if info["records_due"] and not info["documents_due"]:
        what = "Bücher anonymisiert"
    record(
        org,
        user,
        "update",
        closing,
        {
            "Aufbewahrungsfrist abgelaufen": [
                None,
                f"Geschäftsjahr {org.fiscal_label(year)}: {what}",
            ],
            **{k: [None, v] for k, v in counts.items() if v},
        },
    )
    return {"done": what, "counts": counts}
