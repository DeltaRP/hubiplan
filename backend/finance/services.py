"""Fachlogik der Kasse: Buchungsnummern, Bestände, Jahresübersicht."""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext

from .models import Account, Booking, Category, TaxArea, YearClosing

ZERO = Decimal("0.00")


def next_number(org_id: int, year: int) -> int:
    """Nächste Buchungsnummer im Jahr; Sperre verhindert doppelte Nummern."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [org_id, year])
    last = (
        Booking.objects.filter(organization_id=org_id, year=year)
        .order_by("-number")
        .values_list("number", flat=True)
        .first()
    )
    return (last or 0) + 1


# --- Jahresabschluss ---


def is_closed(org, year: int) -> bool:
    return YearClosing.objects.filter(organization=org, year=year).exists()


def _year_lock(org, year: int, *, shared: bool) -> None:
    """Sperre je Geschäftsjahr bis zum Ende der Transaktion.

    Buchen nimmt sie geteilt (viele Buchungen gleichzeitig), der Jahresabschluss
    exklusiv: Er wartet auf laufende Buchungen, und Buchungen danach sehen den Abschluss.
    Eigener Schlüsselbereich (200000 + Jahr), getrennt von der Nummernsperre.
    """
    func = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {func}(%s, %s)", [org.pk, 200000 + year])


def ensure_open(org, *, date: datetime.date | None = None, year: int | None = None) -> None:
    """Fehler, wenn das Geschäftsjahr (zum Datum) abgeschlossen ist.

    Sperrt das Jahr zugleich gegen einen gleichzeitigen Abschluss (siehe ``_year_lock``).
    """
    if not connection.in_atomic_block:
        # Die Sperre gilt nur bis zum Ende der Transaktion; ohne Transaktion endete sie
        # vor dem Schreiben (Gesamtaudit 30.10., B-S02).
        raise RuntimeError("ensure_open nur innerhalb einer Transaktion aufrufen.")
    if year is None and date is not None:
        year = org.fiscal_year_of(date)
    if year is not None:
        _year_lock(org, year, shared=True)
    if year is not None and is_closed(org, year):
        raise ValidationError(
            gettext(
                "Das Geschäftsjahr {x} ist abgeschlossen. Korrekturen bitte als neue "
                "Buchung im laufenden Geschäftsjahr."
            ).format(x=org.fiscal_label(year))
        )


def lock_years_from(org, first: int) -> None:
    """Geteilte Jahressperre für alle Geschäftsjahre ab ``first`` bis zum laufenden."""
    if not connection.in_atomic_block:
        raise RuntimeError("lock_years_from nur innerhalb einer Transaktion aufrufen.")
    last = max([org.fiscal_year_of(timezone.localdate()), first, *years(org)])
    for year in range(first, last + 1):
        _year_lock(org, year, shared=True)


def close_year(org, year: int, user) -> YearClosing:
    _year_lock(org, year, shared=False)
    start, last = org.fiscal_range(year)
    if last >= timezone.localdate():
        raise ValidationError(
            gettext("Das Geschäftsjahr {x} läuft noch bis {last:%d.%m.%Y}.").format(
                x=org.fiscal_label(year), last=last
            )
        )
    earlier = [
        y for y in years(org) if y < year and not is_closed(org, y) and _has_bookings(org, y)
    ]
    if earlier:
        raise ValidationError(
            gettext("Bitte zuerst das Geschäftsjahr {x} abschließen.").format(
                x=org.fiscal_label(min(earlier))
            )
        )
    if is_closed(org, year):
        raise ValidationError(gettext("Das Geschäftsjahr ist schon abgeschlossen."))
    freeze_categories(org, year)
    snap = overview(org, year)
    return YearClosing.objects.create(
        organization=org,
        year=year,
        closed_by=user,
        snapshot={"accounts": snap["accounts"], "totals": snap["totals"]},
    )


def freeze_categories(org, year: int) -> None:
    """Kategorie und steuerlichen Bereich jeder Buchung des Jahres festhalten (Frage 9)."""
    in_year = Booking.objects.filter(organization=org, year=year)
    for cat in Category.objects.filter(organization=org):
        in_year.filter(category=cat).update(
            frozen=True, frozen_category_name=cat.name, frozen_tax_area=cat.tax_area
        )
    in_year.filter(category__isnull=True).update(
        frozen=True, frozen_category_name="", frozen_tax_area=""
    )


def _has_bookings(org, year: int) -> bool:
    return Booking.objects.filter(organization=org, year=year).exists()


def _sum(qs) -> Decimal:
    return qs.aggregate(s=Sum("amount"))["s"] or ZERO


def balance(
    account: Account, before: datetime.date | None = None, *, all_dates: bool = False
) -> Decimal:
    """Bestand eines Kontos bis einschließlich gestern von ``before``. Ohne ``before``:
    Bestand heute (Fachfrage 3, Audit 31.10.); ``all_dates`` nimmt Buchungen mit Datum in
    der Zukunft (vorgemerkt) mit."""
    qs = Booking.objects.filter(organization_id=account.organization_id)
    if before is None and not all_dates:
        before = timezone.localdate() + datetime.timedelta(days=1)
    if before is not None:
        qs = qs.filter(date__lt=before)
    income = _sum(qs.filter(kind=Booking.Kind.INCOME, account=account))
    expense = _sum(qs.filter(kind=Booking.Kind.EXPENSE, account=account))
    out = _sum(qs.filter(kind=Booking.Kind.TRANSFER, account=account))
    into = _sum(qs.filter(kind=Booking.Kind.TRANSFER, to_account=account))
    return account.opening_balance + income - expense - out + into


def ensure_cash_ok(accounts, since: datetime.date) -> None:
    """Eine Barkasse darf an keinem Tag unter null fallen (Kassensturzfähigkeit, GoBD).

    Nach einer Änderung aufrufen (in derselben Transaktion): geprüft wird der Bestand am
    Ende jedes Tages ab ``since``. Bank- und Sparkonten dürfen ins Minus.
    """
    # Kassenkonten gemeinsam sperren (feste Reihenfolge): Zwei gleichzeitige Änderungen
    # verschiedener Buchungen sehen sonst jeweils den alten Stand der anderen.
    cash_ids = sorted({a.pk for a in accounts if a is not None and a.kind == Account.Kind.CASH})
    if cash_ids:
        list(
            Account.objects.select_for_update()
            .filter(pk__in=cash_ids)
            .order_by("pk")
            .values_list("pk")
        )
    seen: set[int] = set()
    for account in accounts:
        if account is None or account.pk in seen or account.kind != Account.Kind.CASH:
            continue
        seen.add(account.pk)
        running = balance(account, before=since)
        qs = Booking.objects.filter(organization_id=account.organization_id, date__gte=since)
        days: dict[datetime.date, Decimal] = defaultdict(Decimal)
        for b in qs.filter(Q(account=account) | Q(to_account=account)).only(
            "date", "kind", "amount", "account_id", "to_account_id"
        ):
            days[b.date] += b.effect_on(account.pk)
        for day in sorted(days):
            running += days[day]
            if running < 0:
                shown = f"{-running:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                raise ValidationError(
                    gettext(
                        "Die Barkasse „{name}“ fiele am {day:%d.%m.%Y} um {shown} € unter null. "
                        "Bitte zuerst die fehlenden Einnahmen erfassen oder Datum und Betrag "
                        "prüfen."
                    ).format(name=account.name, day=day, shown=shown)
                )


def _flows(bookings) -> dict[int, dict[str, Decimal]]:
    """Einnahmen, Ausgaben und Umbuchungen je Konto mit zwei Abfragen (B-P01, PERF-02)."""
    flows: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"income": ZERO, "expense": ZERO, "out": ZERO, "into": ZERO}
    )
    rows = (
        bookings.values("account_id")
        .annotate(
            income=Sum("amount", filter=Q(kind=Booking.Kind.INCOME)),
            expense=Sum("amount", filter=Q(kind=Booking.Kind.EXPENSE)),
            out=Sum("amount", filter=Q(kind=Booking.Kind.TRANSFER)),
        )
        .order_by()
    )
    for row in rows:
        f = flows[row["account_id"]]
        f["income"] = row["income"] or ZERO
        f["expense"] = row["expense"] or ZERO
        f["out"] = row["out"] or ZERO
    into = (
        bookings.filter(kind=Booking.Kind.TRANSFER, to_account__isnull=False)
        .values("to_account_id")
        .annotate(total=Sum("amount"))
        .order_by()
    )
    for row in into:
        flows[row["to_account_id"]]["into"] = row["total"] or ZERO
    return flows


def _net(f: dict[str, Decimal]) -> Decimal:
    return f["income"] - f["expense"] - f["out"] + f["into"]


def balances(
    org_id: int, before: datetime.date | None = None, *, all_dates: bool = False
) -> dict[int, Decimal]:
    """Bestände aller Konten (bis vor ``before``) mit zwei Abfragen statt vier je Konto.

    Ohne ``before``: Bestand heute (Fachfrage 3, Audit 31.10.); ``all_dates`` nimmt
    vorgemerkte Buchungen mit Datum in der Zukunft mit."""
    accounts = list(Account.objects.filter(organization_id=org_id))
    bookings = Booking.objects.filter(organization_id=org_id)
    if before is None and not all_dates:
        before = timezone.localdate() + datetime.timedelta(days=1)
    if before is not None:
        bookings = bookings.filter(date__lt=before)
    flows = _flows(bookings)
    return {a.pk: a.opening_balance + _net(flows[a.pk]) for a in accounts}


def years(org) -> list[int]:
    """Geschäftsjahre mit Buchungen oder Kontoeröffnungen, dazu das laufende."""
    found = set(Booking.objects.filter(organization=org).values_list("year", flat=True).distinct())
    found |= {
        org.fiscal_year_of(d)
        for d in Account.objects.filter(organization=org).values_list("opening_date", flat=True)
    }
    found.add(org.fiscal_year_of(timezone.localdate()))
    return sorted(found, reverse=True)


def _money(data):
    """Beträge als Text mit zwei Nachkommastellen (für die API)."""
    if isinstance(data, Decimal):
        return f"{data:.2f}"
    if isinstance(data, datetime.date):
        return data.isoformat()
    if isinstance(data, dict):
        return {k: _money(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_money(v) for v in data]
    return data


def overview(org, year: int) -> dict:
    return _money(_overview(org, year))


def _overview(org, year: int) -> dict:
    """Jahresübersicht: Bestände je Konto, Einnahmen/Ausgaben je Kategorie und Bereich."""
    start, last = org.fiscal_range(year)
    end = last + datetime.timedelta(days=1)
    in_year = Booking.objects.filter(organization=org, date__gte=start, date__lt=end)

    accounts = []
    # Je Konto keine eigenen Abfragen mehr (PERF-02): Bestände zum Jahresbeginn und
    # Bewegungen im Jahr gruppiert
    before = balances(org.pk, before=start)
    flows = _flows(in_year)
    for a in Account.objects.filter(organization=org):
        if a.opening_date >= end:
            continue
        opening = a.opening_balance if a.opening_date >= start else before[a.pk]
        f = flows[a.pk]
        income, expense, out, into = f["income"], f["expense"], f["out"], f["into"]
        accounts.append(
            {
                "id": a.pk,
                "name": a.name,
                "kind": a.kind,
                "kind_label": a.get_kind_display(),
                "is_active": a.is_active,
                "start": opening,
                "income": income,
                "expense": expense,
                "transfer_in": into,
                "transfer_out": out,
                "end": opening + income - expense - out + into,
            }
        )

    per_category: dict[tuple, dict] = {}
    rows = (
        in_year.exclude(kind=Booking.Kind.TRANSFER)
        .values("category", "kind", "frozen", "frozen_category_name", "frozen_tax_area")
        .annotate(total=Sum("amount"))
    )
    cats = {c.pk: c for c in Category.objects.filter(organization=org)}
    for row in rows:
        cat = cats.get(row["category"])
        if cat is None:
            continue
        # Abgeschlossenes Jahr: wie beim Abschluss festgehalten (Frage 9)
        frozen = row["frozen"]
        name = row["frozen_category_name"] if frozen else cat.name
        area = row["frozen_tax_area"] if frozen else cat.tax_area
        entry = per_category.setdefault(
            (cat.pk, name, area),
            {
                "id": cat.pk,
                "name": name,
                "tax_area": area,
                "income": ZERO,
                "expense": ZERO,
            },
        )
        entry["income" if row["kind"] == Booking.Kind.INCOME else "expense"] += row["total"]
    categories = sorted(per_category.values(), key=lambda c: c["name"].lower())

    areas = []
    if org.tax_areas_enabled:
        totals: dict[str, dict] = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
        for c in categories:
            totals[c["tax_area"]]["income"] += c["income"]
            totals[c["tax_area"]]["expense"] += c["expense"]
        labels = dict(TaxArea.choices)
        for key in [*TaxArea.values, ""]:
            if key in totals:
                areas.append(
                    {
                        "area": key,
                        "label": labels.get(key, "ohne Zuordnung"),
                        **totals[key],
                    }
                )

    income = sum((c["income"] for c in categories), ZERO)
    expense = sum((c["expense"] for c in categories), ZERO)
    return {
        "year": year,
        "label": org.fiscal_label(year),
        "start_date": start,
        "end_date": last,
        "years": [{"year": y, "label": org.fiscal_label(y)} for y in years(org)],
        "tax_areas_enabled": org.tax_areas_enabled,
        "accounts": accounts,
        "categories": categories,
        "tax_areas": areas,
        "totals": {
            "income": income,
            "expense": expense,
            "result": income - expense,
            "start": sum((a["start"] for a in accounts), ZERO),
            "end": sum((a["end"] for a in accounts), ZERO),
        },
        "booking_count": in_year.count(),
    }


def search_filter(term: str) -> Q:
    q = Q(text__icontains=term) | Q(reference__icontains=term) | Q(counterparty__icontains=term)
    if term.replace(",", ".").replace(".", "", 1).isdigit():
        q |= Q(amount=Decimal(term.replace(",", ".")))
    if "-" in term:
        y, _, n = term.partition("-")
        y = y.split("/")[0]
        if y.isdigit() and n.isdigit():
            q |= Q(year=int(y), number=int(n))
    elif term.isdigit():
        q |= Q(number=int(term))
    return q


# --- Festschreibung und Storno (GoBD Rz. 58 ff., 87, 110) ---


def auto_fix_cutoff(today: datetime.date | None = None) -> datetime.date:
    """Buchungen vor diesem Tag sind festgeschrieben: Ein Monat ist nach Ablauf des
    Folgemonats abgeschlossen (z. B. am 1. Mai alles bis Ende März)."""
    today = today or timezone.localdate()
    first = today.replace(day=1)
    return (first - datetime.timedelta(days=1)).replace(day=1)


def fixed_reason(booking: Booking, today: datetime.date | None = None) -> str:
    """Warum eine Buchung festgeschrieben ist; leer, wenn sie sich noch ändern lässt.

    Nachträglich erfasste Buchungen (Datum in einem alten Monat) bekommen die Frist ab dem
    Monat der Erfassung, sonst wären sie sofort gesperrt und ein Tippfehler nur per Storno
    zu beheben."""
    why = fixed_on(booking.organization, booking.date, booking.created_at, today)
    return f"Die Buchung {booking.display_number} ist festgeschrieben{why}" if why else ""


def fixed_on(org, date, created_at, today: datetime.date | None = None) -> str:
    """Begründung (Satzende), wenn eine Buchung mit diesem Datum festgeschrieben ist."""
    if org.finance_locked_until and date <= org.finance_locked_until:
        return f" (Kasse festgeschrieben bis {org.finance_locked_until:%d.%m.%Y})."
    cutoff = auto_fix_cutoff(today)
    created = timezone.localdate(created_at) if created_at else cutoff
    if date < cutoff and created < cutoff:
        return ": Der Folgemonat ist abgelaufen."
    return ""


FIX_HINT = " Korrekturen bitte als Storno mit neuer Buchung."


def ensure_not_fixed(booking: Booking) -> None:
    reason = fixed_reason(booking)
    if reason:
        raise ValidationError(reason + FIX_HINT)


def in_storno(booking: Booking) -> bool:
    """Gehört zu einem Storno (storniert oder selbst Gegenbuchung)."""
    if booking.cancels_id:
        return True
    try:
        booking.cancellation  # noqa: B018 (Rückverweis, beim Auflisten vorgeladen)
    except Booking.DoesNotExist:
        return False
    return True


def deletable(booking: Booking, today: datetime.date | None = None) -> bool:
    """Löschen nur am Tag der Erfassung und vor der Festschreibung (Fachfrage 1, 31.10.)."""
    today = today or timezone.localdate()
    created = timezone.localdate(booking.created_at) if booking.created_at else None
    return (
        created == today
        and not fixed_reason(booking, today)
        and not in_storno(booking)
        and not hasattr(booking, "payment")
    )


def cancel_booking(booking: Booking, user, reason: str, *, check_links: bool = True) -> Booking:
    """Storno: Gegenbuchung im offenen Geschäftsjahr mit heutigem Datum; die Buchung bleibt.

    Geht auch für Buchungen aus abgeschlossenen Jahren (Korrektur im laufenden Jahr).
    ``check_links=False`` für Aufrufer, die Zahlung bzw. Quittung selbst behandeln."""
    if not connection.in_atomic_block:
        raise RuntimeError("cancel_booking nur innerhalb einer Transaktion aufrufen.")
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise ValidationError({"reason": gettext("Bitte einen Grund für das Storno angeben.")})
    if booking.cancels_id:
        raise ValidationError(gettext("Eine Stornobuchung lässt sich nicht stornieren."))
    if Booking.objects.filter(cancels=booking).exists():
        raise ValidationError(
            gettext("Die Buchung {display_number} ist schon storniert.").format(
                display_number=booking.display_number
            )
        )
    if check_links:
        from .models import CashReceipt

        if CashReceipt.objects.filter(booking=booking).exists():
            raise ValidationError(
                gettext(
                    "Die Buchung gehört zu einer unterschriebenen Quittung. Bitte die "
                    "Quittung stornieren."
                )
            )
        if hasattr(booking, "payment"):
            raise ValidationError(
                gettext(
                    "Die Buchung gehört zu einer Zahlung. Bitte die Zahlung bei der Rechnung "
                    "entfernen; das storniert die Buchung."
                )
            )
    donation = getattr(booking, "donation", None)
    if donation is not None:
        if donation.statement_id:
            raise ValidationError(
                gettext(
                    "Die Buchung ist als Zuwendung in der Bestätigung {number} enthalten. "
                    "Bitte erst die Bestätigung stornieren."
                ).format(number=donation.statement.number)
            )
        donation.delete()
    org = booking.organization
    today = timezone.localdate()
    ensure_open(org, date=today)
    year = org.fiscal_year_of(today)
    counter = Booking(
        organization=org,
        year=year,
        number=next_number(org.pk, year),
        date=today,
        amount=booking.amount,
        # Gleiche Kategorie und Veranstaltung, damit sich beides in der Auswertung aufhebt
        category=booking.category,
        project=booking.project,
        counterparty=booking.counterparty,
        membership=booking.membership,
        department=booking.department,
        text=f"Storno {booking.display_number}: {reason}"[:200],
        reference=booking.display_number,
        cancels=booking,
        cancel_reason=reason[:300],
        created_by=user,
    )
    if booking.kind == Booking.Kind.TRANSFER:
        counter.kind = Booking.Kind.TRANSFER
        counter.account, counter.to_account = booking.to_account, booking.account
    else:
        counter.kind = (
            Booking.Kind.EXPENSE if booking.kind == Booking.Kind.INCOME else Booking.Kind.INCOME
        )
        counter.account = booking.account
    # Ohne full_clean: Die Kategorie passt evtl. nur zur Richtung der ursprünglichen Buchung
    counter.save()
    # Zugeordneter Kontoumsatz: im offenen Jahr wieder offen, damit er richtig gebucht wird
    from .models import BankLine

    for line in BankLine.objects.select_for_update().filter(booking=booking):
        if is_closed(org, org.fiscal_year_of(line.date)):
            continue
        line.status = BankLine.Status.OPEN
        line.booking = None
        line.done_by = None
        line.done_at = None
        line.save(update_fields=["status", "booking", "done_by", "done_at"])
    ensure_cash_ok([counter.account, counter.to_account], today)
    return counter


def fix_until(org, until: datetime.date) -> datetime.date:
    """Kasse bis einschließlich ``until`` festschreiben; nur vorwärts, nicht in die Zukunft."""
    if until > timezone.localdate():
        raise ValidationError({"until": gettext("Festschreiben geht nur bis heute.")})
    if org.finance_locked_until and until <= org.finance_locked_until:
        raise ValidationError(
            {
                "until": gettext(
                    "Die Kasse ist schon bis {finance_locked_until:%d.%m.%Y} festgeschrieben."
                ).format(finance_locked_until=org.finance_locked_until)
            }
        )
    org.finance_locked_until = until
    org.save(update_fields=["finance_locked_until"])
    return until


def renumber(org, year: int) -> int:
    """Alle Buchungen eines Geschäftsjahres nach Datum neu durchnummerieren.

    Gibt die Zahl der geänderten Nummern zurück.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [org.pk, year])
    from .models import CashReceipt

    if CashReceipt.objects.filter(organization=org, booking__year=year).exists():
        raise ValidationError(
            gettext(
                "In diesem Geschäftsjahr gibt es unterschriebene Quittungen. Ihre "
                "Belegnummern stehen auf dem Papier bzw. PDF und dürfen sich nicht "
                "ändern."
            )
        )
    bookings = list(
        Booking.objects.filter(organization=org, year=year)
        .select_related("organization")
        .order_by("date", "number", "pk")
    )
    # Festgeschriebene Buchungen behalten ihre Nummer (GoBD); Storno verweist auf Nummern
    if (
        any(fixed_reason(b) or b.cancels_id for b in bookings)
        or Booking.objects.filter(organization=org, cancels__year=year).exists()
    ):
        raise ValidationError(
            gettext(
                "In diesem Geschäftsjahr gibt es festgeschriebene oder stornierte "
                "Buchungen. Ihre Nummern dürfen sich nicht mehr ändern."
            )
        )
    changed = [b for i, b in enumerate(bookings, start=1) if b.number != i]
    if not changed:
        return 0
    # Erst aus dem Weg räumen, dann neu vergeben (Eindeutigkeit je Jahr)
    offset = len(bookings) + max(b.number for b in bookings)
    for b in changed:
        b.number += offset
    Booking.objects.bulk_update(changed, ["number"])
    for i, b in enumerate(bookings, start=1):
        b.number = i
    Booking.objects.bulk_update(changed, ["number"])
    return len(changed)


def finance_records_of(unit) -> str:
    """Grund, warum eine Einheit wegen ihrer Finanzdaten nicht gelöscht werden darf ("" = keiner).

    Buchungen, Belege und Rechnungen sind aufbewahrungspflichtig (§ 147 AO). Beim Löschen
    der Einheit würden ihre eigenen Finanzdaten mitgelöscht und Zuordnungen in den Büchern
    des Vereins verloren gehen."""
    from billing.models import DebitRun, Invoice
    from core.tenancy import rls_bypass

    from .models import BankStatement, CashReceipt, Donation, DonationStatement

    checks = [
        (Booking.objects.filter(organization=unit), "Buchungen"),
        (Booking.objects.filter(department=unit), "zugeordnete Buchungen"),
        (Invoice.objects.filter(organization=unit), "Rechnungen"),
        (Invoice.objects.filter(department=unit), "zugeordnete Rechnungen"),
        (DebitRun.objects.filter(organization=unit), "Lastschriftläufe"),
        (CashReceipt.objects.filter(organization=unit), "Quittungen"),
        (Donation.objects.filter(organization=unit), "Zuwendungen"),
        (DonationStatement.objects.filter(organization=unit), "Zuwendungsbestätigungen"),
        (BankStatement.objects.filter(organization=unit), "Kontoauszüge"),
        (YearClosing.objects.filter(organization=unit), "Jahresabschlüsse"),
    ]
    with rls_bypass():
        return next((label for qs, label in checks if qs.exists()), "")


_TOTAL_LABELS = {
    "income": "Einnahmen",
    "expense": "Ausgaben",
    "result": "Ergebnis",
    "start": "Anfangsbestand",
    "end": "Endbestand",
}


def _eur(value) -> str:
    return f"{Decimal(value or 0):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def closing_changes(old: dict, new: dict) -> list[str]:
    """Unterschiede zwischen zwei Abschlussständen, als lesbare Zeilen (B4)."""
    lines = []
    for key, label in _TOTAL_LABELS.items():
        a, b = (old.get("totals") or {}).get(key), (new.get("totals") or {}).get(key)
        if a != b:
            lines.append(f"{label}: {_eur(a)} → {_eur(b)}")
    before = {a["name"]: a for a in old.get("accounts") or []}
    after = {a["name"]: a for a in new.get("accounts") or []}
    for name in sorted(before.keys() | after.keys(), key=str.lower):
        a, b = before.get(name, {}).get("end"), after.get(name, {}).get("end")
        if a != b:
            lines.append(f"{name}, Endbestand: {_eur(a)} → {_eur(b)}")
    return lines


def reopen_year(closing: YearClosing, user, reason: str):
    """Abschluss aufheben; der alte Stand bleibt mit Grund erhalten (B4)."""
    from .models import ReopenedClosing

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationError(
            gettext("Bitte einen Grund angeben, warum der Abschluss aufgehoben wird.")
        )
    by = closing.closed_by
    archived = ReopenedClosing.objects.create(
        organization=closing.organization,
        year=closing.year,
        closed_at=closing.closed_at,
        closed_by_name=(by.get_full_name() or by.email) if by else "",
        snapshot=closing.snapshot,
        reopened_by=user,
        reopened_by_name=(user.get_full_name() or user.email) if user else "",
        reason=reason[:500],
    )
    closing.delete()
    return archived
