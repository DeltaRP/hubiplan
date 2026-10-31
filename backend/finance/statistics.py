"""Finanzentwicklung: Kontostände, Einnahmen und Ausgaben über die Zeit, Kategorien.

Ein Jahr im Raster ist das Geschäftsjahr. Der Vergleich nach Kategorie stellt
den gewählten Zeitraum dem gleich langen Zeitraum ein Jahr früher gegenüber.
"""

from __future__ import annotations

import datetime
from bisect import bisect_right
from collections import defaultdict
from decimal import Decimal
from itertools import accumulate

from dateutil.relativedelta import relativedelta

from core import timeline

from .models import Account, Booking, Category
from .services import _money

ZERO = Decimal("0.00")


def _earliest(org) -> datetime.date | None:
    days = [
        d
        for d in (
            Account.objects.filter(organization=org)
            .order_by("opening_date")
            .values_list("opening_date", flat=True)
            .first(),
            Booking.objects.filter(organization=org)
            .order_by("date")
            .values_list("date", flat=True)
            .first(),
        )
        if d is not None
    ]
    return min(days, default=None)


class _Balance:
    """Kontostand eines Kontos zu beliebigen Stichtagen (Ende des Tages)."""

    def __init__(self, account: Account, changes: list[tuple[datetime.date, Decimal]]):
        changes.sort()
        self.opening = account.opening_balance
        self.opening_date = account.opening_date
        self.days = [d for d, _ in changes]
        self.sums = list(accumulate(v for _, v in changes))

    def at(self, day: datetime.date) -> Decimal | None:
        if day < self.opening_date:
            return None
        i = bisect_right(self.days, day)
        return self.opening + (self.sums[i - 1] if i else ZERO)


def _totals(bookings, start: datetime.date, end: datetime.date, cats: dict) -> dict[int, dict]:
    per: dict[int, dict] = {}
    for day, kind, amount, _acc, _to, cat_id in bookings:
        if not (start <= day <= end) or kind == Booking.Kind.TRANSFER or cat_id not in cats:
            continue
        entry = per.setdefault(cat_id, {"income": ZERO, "expense": ZERO})
        entry["income" if kind == Booking.Kind.INCOME else "expense"] += amount
    return per


def statistics(org, params) -> dict:
    line = timeline.build(
        params,
        earliest=_earliest(org),
        year_start=org.fiscal_start,
        year_label=org.fiscal_label,
    )
    previous_start = line.start - relativedelta(years=1)
    previous_end = line.end - relativedelta(years=1)
    bookings = list(
        Booking.objects.filter(organization=org, date__lte=line.end).values_list(
            "date", "kind", "amount", "account_id", "to_account_id", "category_id"
        )
    )

    changes: dict[int, list] = defaultdict(list)
    for day, kind, amount, acc, to, _cat in bookings:
        if kind == Booking.Kind.INCOME:
            changes[acc].append((day, amount))
        elif kind == Booking.Kind.EXPENSE:
            changes[acc].append((day, -amount))
        else:
            changes[acc].append((day, -amount))
            changes[to].append((day, amount))

    accounts = []
    for a in Account.objects.filter(organization=org).order_by("position", "name"):
        if a.opening_date > line.end:
            continue
        bal = _Balance(a, changes.get(a.pk, []))
        values = [bal.at(b.end) for b in line.buckets]
        accounts.append(
            {
                "id": a.pk,
                "name": a.name,
                "kind_label": a.get_kind_display(),
                "is_active": a.is_active,
                "start": bal.at(line.start - datetime.timedelta(days=1)),
                "values": values,
            }
        )

    def balance_total(values) -> Decimal | None:
        """Summe der Konten; None, solange es noch kein Konto gibt."""
        known = [v for v in values if v is not None]
        return sum(known, ZERO) if known else None

    starts = [b.start for b in line.buckets]
    flows = [[ZERO, ZERO] for _ in line.buckets]
    for day, kind, amount, *_ in bookings:
        if day < line.start or kind == Booking.Kind.TRANSFER:
            continue
        flows[bisect_right(starts, day) - 1][0 if kind == Booking.Kind.INCOME else 1] += amount
    buckets = [
        {
            **b.as_dict(),
            "income": income,
            "expense": expense,
            "result": income - expense,
            "balance": balance_total(a["values"][i] for a in accounts),
        }
        for i, (b, (income, expense)) in enumerate(zip(line.buckets, flows, strict=True))
    ]

    cats = {c.pk: c for c in Category.objects.filter(organization=org)}
    now = _totals(bookings, line.start, line.end, cats)
    before = _totals(bookings, previous_start, previous_end, cats)
    categories = []
    for cat_id in sorted(set(now) | set(before), key=lambda c: cats[c].name.lower()):
        cur = now.get(cat_id, {"income": ZERO, "expense": ZERO})
        old = before.get(cat_id, {"income": ZERO, "expense": ZERO})
        categories.append(
            {
                "id": cat_id,
                "name": cats[cat_id].name,
                "income": cur["income"],
                "expense": cur["expense"],
                "previous_income": old["income"],
                "previous_expense": old["expense"],
            }
        )

    def total(key: str, data: dict) -> Decimal:
        return sum((v[key] for v in data.values()), ZERO)

    income, expense = total("income", now), total("expense", now)
    prev_income, prev_expense = total("income", before), total("expense", before)
    return _money(
        {
            **line.as_dict(),
            "earliest": _earliest(org),
            "previous": {"von": previous_start, "bis": previous_end},
            "buckets": buckets,
            "accounts": accounts,
            "categories": categories,
            "summary": {
                "income": income,
                "expense": expense,
                "result": income - expense,
                "previous_income": prev_income,
                "previous_expense": prev_expense,
                "previous_result": prev_income - prev_expense,
                "balance_start": balance_total(a["start"] for a in accounts) or ZERO,
                "balance_end": (buckets[-1]["balance"] if buckets else None) or ZERO,
            },
        }
    )
