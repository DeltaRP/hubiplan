"""Kontoauszug (CAMT.053) einlesen, Umsätze zuordnen und buchen.

Ablauf: Datei hochladen → jeder gebuchte Umsatz wird einmal gespeichert (zweites Einlesen
derselben Umsätze wird erkannt) → HUBIplan schlägt eine Zuordnung vor → die Kasse übernimmt
den Vorschlag, bucht mit Kategorie oder übergeht den Umsatz.

Vorschläge, in dieser Reihenfolge (Audit 31.10. FIN31-03: Referenzen vor Betrag/Datum):
1. Rechnung: Rechnungsnummer im Verwendungszweck, offen mindestens in Höhe des Betrags
2. schon im Kassenbuch: gleiches Konto, Betrag und Richtung, Datum ±3 Tage, noch keinem
   Umsatz zugeordnet (z. B. von Hand gebucht oder gebuchter Lastschriftlauf). Nur bei genau
   einer solchen Buchung; „sicher“ nur, wenn auch die Gegenseite oder Referenz passt.
3. Lastschriftlauf: Gutschrift in Höhe genau eines noch nicht gebuchten Laufs auf dieses
   Konto, Einzug ±10 Tage
4. Rechnung über die IBAN eines SEPA-Mandats und genau eine offene Rechnung mit diesem Betrag
5. Rücklastschrift: Lastschrift mit Rückgabegrund und bekannter End-to-End-Referenz
   (nur Hinweis; gebucht wird mit Kategorie, die Rechnung öffnet der Kassierer selbst)

Sammelbuchungen (mehrere Einzelposten) werden nie einer einzelnen Rechnung zugeordnet.
„Alle Vorschläge übernehmen“ nimmt nur sichere Vorschläge; die anderen prüft die Kasse
einzeln.
"""

from __future__ import annotations

import datetime
import hashlib
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from . import camt, services
from .models import Account, BankLine, BankStatement, Booking, Category

DAYS_BOOKED = 3
DAYS_RUN = 10


def _account_for(org, iban: str, chosen: Account | None) -> Account:
    if chosen is not None:
        if chosen.organization_id != org.pk:
            raise ValidationError({"account": gettext("Unbekanntes Konto.")})
        own = chosen.iban.replace(" ", "").upper()
        if own and iban and own != iban:
            raise ValidationError(
                {
                    "account": gettext(
                        "Der Auszug gehört zur IBAN {iban}, das Konto „{name}“ hat {own}. Bitte "
                        "das passende Konto wählen."
                    ).format(iban=iban, name=chosen.name, own=own)
                }
            )
        return chosen
    matches = [
        a
        for a in Account.objects.filter(organization=org, is_active=True)
        if a.iban.replace(" ", "").upper() == iban and iban
    ]
    if len(matches) == 1:
        return matches[0]
    raise ValidationError(
        {
            "account": gettext(
                "Zur IBAN {x} gibt es kein eindeutiges Konto. Bitte das Konto wählen "
                "oder die IBAN beim Konto eintragen."
            ).format(x=iban or "(ohne)")
        }
    )


@transaction.atomic
def import_file(org, data: bytes, file_name: str, user, account: Account | None = None) -> dict:
    try:
        statements = camt.parse(data)
    except camt.CamtError as exc:
        raise ValidationError(str(exc)) from exc
    result = {"statements": [], "lines": 0, "duplicates": 0}
    digest = hashlib.sha256(data).hexdigest()
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in file_name)[-100:] or "auszug"
    for st in statements:
        if st.currency and st.currency != "EUR":
            raise ValidationError(
                gettext("Nur Konten in Euro (Auszug in {currency}).").format(currency=st.currency)
            )
        acc = _account_for(org, st.iban, account)
        record = BankStatement.objects.create(
            organization=org,
            account=acc,
            file_name=file_name[:200],
            reference=st.ref[:100],
            date_from=st.date_from,
            date_to=st.date_to,
            opening_balance=st.opening,
            closing_balance=st.closing,
            imported_by=user,
            source_sha256=digest,
        )
        # Originaldatei unverändert aufbewahren (GoBD), je Auszug eine Kopie
        record.source.save(safe, ContentFile(data), save=False)
        record.save(update_fields=["source"])
        new = dup = 0
        for line in st.lines:
            fingerprint = line.fingerprint(st.iban or str(acc.pk))
            # Nur ein schon gespeicherter gleicher Umsatz ist eine Dublette (FIN31-01);
            # andere Datenbankfehler brechen den Import ab statt still zu zählen
            if BankLine.objects.filter(
                organization=org, account=acc, fingerprint=fingerprint
            ).exists():
                dup += 1
                continue
            obj = BankLine(
                organization=org,
                statement=record,
                account=acc,
                date=line.date,
                value_date=line.value_date,
                amount=line.amount,
                credit=line.credit,
                name=line.name,
                iban=line.iban,
                purpose=line.purpose,
                end_to_end=line.end_to_end,
                bank_ref=line.bank_ref,
                return_code=line.return_code,
                batch_count=line.batch_count,
                details=line.details,
                fingerprint=fingerprint,
            )
            obj.full_clean(exclude=["organization", "statement", "account"])
            obj.save()
            new += 1
        record.line_count = new
        record.duplicate_count = dup
        record.save(update_fields=["line_count", "duplicate_count"])
        result["statements"].append(record)
        result["lines"] += new
        result["duplicates"] += dup
    suggest_all(org)
    return result


# --- Vorschläge ---


def _clear(line: BankLine) -> None:
    line.suggestion = BankLine.Suggestion.NONE
    line.suggestion_sure = False
    line.suggested_invoice = None
    line.suggested_run = None
    line.suggested_booking = None
    line.suggested_membership = None


def _taken_bookings(org) -> set[int]:
    return set(
        BankLine.objects.filter(organization=org, booking__isnull=False).values_list(
            "booking_id", flat=True
        )
    ) | set(
        BankLine.objects.filter(
            organization=org, status=BankLine.Status.OPEN, suggested_booking__isnull=False
        ).values_list("suggested_booking_id", flat=True)
    )


def _membership_by_iban(org, iban: str):
    if not iban:
        return None
    from billing.models import Mandate

    ids = {
        m.membership_id
        for m in Mandate.objects.filter(organization=org, membership__isnull=False)
        if m.iban.replace(" ", "").upper() == iban
    }
    if len(ids) != 1:
        return None
    from members.models import Membership

    return Membership.objects.filter(pk=ids.pop(), organization=org).first()


def _open_invoices(org):
    from billing.models import Invoice

    return Invoice.objects.filter(organization=org, status=Invoice.Status.OPEN)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _same_party(line: BankLine, booking: Booking) -> bool:
    """Passt die gebuchte Gegenseite oder Referenz zum Bankumsatz?"""
    if line.name and _norm(booking.counterparty) == _norm(line.name):
        return True
    refs = [r for r in (line.bank_ref, line.end_to_end) if r]
    haystack = f"{booking.reference} {booking.text}"
    return any(r in haystack for r in refs)


def suggest(line: BankLine, taken: set[int]) -> None:
    from billing.models import DebitItem, DebitRun

    org = line.organization
    _clear(line)
    batch = line.batch_count > 1
    invoices = _open_invoices(org)
    # 1. Rechnungsnummer im Verwendungszweck: die stärkste Referenz
    if line.credit and not batch:
        for year, number in camt.invoice_numbers(line.purpose):
            inv = invoices.filter(year=year, number=number).first()
            if inv is not None and inv.outstanding >= line.amount:
                line.suggestion = BankLine.Suggestion.INVOICE
                line.suggested_invoice = inv
                line.suggested_membership = inv.membership
                line.suggestion_sure = True
                return
    # 2. schon im Kassenbuch: nur bei genau einem Kandidaten
    window = datetime.timedelta(days=DAYS_BOOKED)
    kind = Booking.Kind.INCOME if line.credit else Booking.Kind.EXPENSE
    candidates = list(
        Booking.objects.filter(
            organization=org,
            account=line.account,
            kind=kind,
            amount=line.amount,
            date__gte=line.date - window,
            date__lte=line.date + window,
        )
        .exclude(pk__in=taken)
        .order_by("date", "pk")[:2]
    )
    if candidates:
        if len(candidates) == 1:
            existing = candidates[0]
            line.suggestion = BankLine.Suggestion.BOOKED
            line.suggested_booking = existing
            line.suggestion_sure = _same_party(line, existing)
            taken.add(existing.pk)
        # mehrere passende Buchungen: die Kasse entscheidet selbst, kein Vorschlag
        return
    if line.credit:
        run_window = datetime.timedelta(days=DAYS_RUN)
        runs = list(
            DebitRun.objects.filter(
                organization=org,
                account=line.account,
                status=DebitRun.Status.CREATED,
                total=line.amount,
                collection_date__gte=line.date - run_window,
                collection_date__lte=line.date + run_window,
            ).order_by("collection_date")[:2]
        )
        if len(runs) == 1:
            line.suggestion = BankLine.Suggestion.DEBIT_RUN
            line.suggested_run = runs[0]
            line.suggestion_sure = True
            return
        if runs:
            return
        if batch:
            return
        member = _membership_by_iban(org, line.iban)
        if member is not None:
            line.suggested_membership = member
            matching = [
                i for i in invoices.filter(membership=member) if i.outstanding == line.amount
            ]
            if len(matching) == 1:
                line.suggestion = BankLine.Suggestion.INVOICE
                line.suggested_invoice = matching[0]
                line.suggestion_sure = True
        return
    if line.return_code and line.end_to_end:
        item = (
            DebitItem.objects.filter(organization=org, end_to_end_id=line.end_to_end)
            .select_related("invoice")
            .first()
        )
        if item is not None:
            line.suggestion = BankLine.Suggestion.RETURN
            line.suggested_invoice = item.invoice
            line.suggested_membership = item.invoice.membership


def suggest_all(org) -> None:
    taken = _taken_bookings(org)
    lines = BankLine.objects.filter(organization=org, status=BankLine.Status.OPEN).select_related(
        "organization", "account"
    )
    for line in lines:
        if line.suggested_booking_id:
            taken.discard(line.suggested_booking_id)
        suggest(line, taken)
        line.save(
            update_fields=[
                "suggestion",
                "suggestion_sure",
                "suggested_invoice",
                "suggested_run",
                "suggested_booking",
                "suggested_membership",
            ]
        )


# --- Erledigen ---


def _done(line: BankLine, user, booking: Booking | None, status=BankLine.Status.DONE) -> BankLine:
    line.status = status
    line.booking = booking
    line.done_by = user
    line.done_at = timezone.now()
    _clear(line)
    line.save()
    return line


def _lock(line: BankLine) -> BankLine:
    line = (
        BankLine.objects.select_for_update()
        .select_related("account", "organization")
        .get(pk=line.pk)
    )
    if line.status != BankLine.Status.OPEN:
        raise ValidationError(gettext("Der Umsatz ist schon erledigt."))
    return line


@transaction.atomic
def pay_invoice(line: BankLine, invoice, user) -> BankLine:
    from billing import services as billing_services

    line = _lock(line)
    if not line.credit:
        raise ValidationError(gettext("Nur Gutschriften lassen sich einer Rechnung zuordnen."))
    if invoice.organization_id != line.organization_id:
        raise ValidationError({"invoice": gettext("Unbekannte Rechnung.")})
    if line.batch_count > 1:
        raise ValidationError(
            gettext(
                "Das ist eine Sammelbuchung mit mehreren Einzelposten. Sie lässt sich "
                "nicht einer einzelnen Rechnung zuordnen; bitte die Zahlungen bei den "
                "Rechnungen erfassen und den Umsatz der Buchung zuordnen oder mit "
                "Kategorie buchen."
            )
        )
    payment = billing_services.add_payment(
        invoice,
        date=line.date,
        amount=line.amount,
        method="transfer",
        account=line.account,
        user=user,
    )
    return _done(line, user, payment.booking)


@transaction.atomic
def book_debit_run(line: BankLine, run, user) -> BankLine:
    from billing import sepa

    line = _lock(line)
    if run.organization_id != line.organization_id or run.account_id != line.account_id:
        raise ValidationError(
            {"run": gettext("Der Lastschriftlauf gehört zu einem anderen Konto.")}
        )
    if run.total != line.amount:
        raise ValidationError({"run": gettext("Der Betrag passt nicht zum Lastschriftlauf.")})
    sepa.book_run(run, user)
    return _done(line, user, None)


@transaction.atomic
def link_booking(line: BankLine, booking: Booking, user) -> BankLine:
    line = _lock(line)
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.organization_id != line.organization_id or booking.account_id != line.account_id:
        raise ValidationError({"booking": gettext("Die Buchung gehört zu einem anderen Konto.")})
    kind = Booking.Kind.INCOME if line.credit else Booking.Kind.EXPENSE
    if booking.kind != kind or booking.amount != line.amount:
        raise ValidationError(
            {"booking": gettext("Betrag oder Richtung der Buchung passen nicht zu diesem Umsatz.")}
        )
    if BankLine.objects.filter(booking=booking).exists():
        raise ValidationError(
            {"booking": gettext("Die Buchung ist schon einem Umsatz zugeordnet.")}
        )
    return _done(line, user, booking)


@transaction.atomic
def book(
    line: BankLine,
    user,
    *,
    category: Category,
    membership=None,
    text: str = "",
    project=None,
) -> BankLine:
    line = _lock(line)
    org = line.organization
    kind = Booking.Kind.INCOME if line.credit else Booking.Kind.EXPENSE
    if category is None or category.organization_id != org.pk:
        raise ValidationError({"category": gettext("Bitte eine Kategorie wählen.")})
    if not category.allows(kind):
        raise ValidationError(
            {"category": gettext("Die Kategorie passt nicht zu dieser Richtung.")}
        )
    services.ensure_open(org, date=line.date)
    year = org.fiscal_year_of(line.date)
    booking = Booking(
        organization=org,
        year=year,
        number=services.next_number(org.pk, year),
        date=line.date,
        kind=kind,
        amount=line.amount,
        account=line.account,
        category=category,
        text=(text.strip() or line.purpose or line.name or "Kontoumsatz")[:200],
        reference="Kontoauszug",
        counterparty=line.name[:200],
        membership=membership,
        project=project,
        created_by=user,
    )
    booking.full_clean(exclude=["organization", "created_by"])
    booking.save()
    services.ensure_cash_ok([line.account], line.date)
    return _done(line, user, booking)


@transaction.atomic
def ignore(line: BankLine, user) -> BankLine:
    line = _lock(line)
    return _done(line, user, None, BankLine.Status.IGNORED)


@transaction.atomic
def reopen(line: BankLine) -> BankLine:
    line = BankLine.objects.select_for_update().get(pk=line.pk)
    if line.status != BankLine.Status.IGNORED:
        raise ValidationError(
            gettext(
                "Nur übergangene Umsätze lassen sich wieder öffnen. Gebuchte bitte im "
                "Kassenbuch korrigieren."
            )
        )
    line.status = BankLine.Status.OPEN
    line.done_by = None
    line.done_at = None
    line.save()
    suggest(line, _taken_bookings(line.organization))
    line.save()
    return line


def apply_suggestions(org, user, statement: BankStatement | None = None) -> dict:
    """Alle sicheren Vorschläge übernehmen (Rechnung, Lastschriftlauf, schon gebucht).

    Vorschläge nur nach Betrag und Datum („bitte prüfen“) bleiben offen (FIN31-03).
    """
    qs = BankLine.objects.filter(
        organization=org, status=BankLine.Status.OPEN, suggestion_sure=True
    ).exclude(suggestion__in=[BankLine.Suggestion.NONE, BankLine.Suggestion.RETURN])
    if statement is not None:
        qs = qs.filter(statement=statement)
    done, failed = 0, []
    for line in qs.select_related("suggested_invoice", "suggested_run", "suggested_booking"):
        try:
            with transaction.atomic():
                if line.suggestion == BankLine.Suggestion.INVOICE and line.suggested_invoice:
                    pay_invoice(line, line.suggested_invoice, user)
                elif line.suggestion == BankLine.Suggestion.DEBIT_RUN and line.suggested_run:
                    book_debit_run(line, line.suggested_run, user)
                elif line.suggestion == BankLine.Suggestion.BOOKED and line.suggested_booking:
                    link_booking(line, line.suggested_booking, user)
                else:
                    continue
            done += 1
        except ValidationError as exc:
            failed.append(f"{line.date:%d.%m.%Y} {line.amount} €: {' '.join(exc.messages)}")
    return {"done": done, "failed": failed}


def balance_check(statement: BankStatement) -> dict | None:
    """Endsaldo des Auszugs gegen den Stand im Kassenbuch am selben Tag."""
    if statement.closing_balance is None or statement.date_to is None:
        return None
    book_balance = services.balance(
        statement.account, before=statement.date_to + datetime.timedelta(days=1)
    )
    diff = (statement.closing_balance - book_balance).quantize(Decimal("0.01"))
    return {
        "bank": str(statement.closing_balance),
        "book": str(book_balance),
        "difference": str(diff),
        "ok": diff == 0,
    }
