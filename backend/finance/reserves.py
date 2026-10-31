"""Rücklagen nach § 62 AO (Finanzamt-Prüfung C4, zuschaltbar je Einheit).

Rücklagen binden einen Teil der Mittel für einen Zweck, ohne Geld zu bewegen: Die
Buchungen bleiben, wie sie sind. Zuführungen und Auflösungen gehören zu einem
Geschäftsjahr; ist es abgeschlossen, lassen sie sich nicht mehr ändern oder löschen.
Eine Rücklage kann nie unter null fallen.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Sum

from . import services
from .models import Reserve, ReserveMovement

ZERO = Decimal("0.00")
# Projekt- und Wiederbeschaffungsrücklagen brauchen einen konkreten Zweck
NEEDS_PURPOSE = {Reserve.Kind.PURPOSE, Reserve.Kind.REPLACEMENT}


def check_enabled(org) -> None:
    if not org.reserves_enabled:
        raise ValidationError("Rücklagen sind für diese Einheit nicht eingeschaltet.")


def balance(reserve: Reserve, until: datetime.date | None = None) -> Decimal:
    qs = ReserveMovement.objects.filter(reserve=reserve)
    if until is not None:
        qs = qs.filter(date__lte=until)
    add = qs.filter(direction=ReserveMovement.Direction.ADD).aggregate(s=Sum("amount"))["s"]
    rel = qs.filter(direction=ReserveMovement.Direction.RELEASE).aggregate(s=Sum("amount"))["s"]
    return (add or ZERO) - (rel or ZERO)


def balances(org, until: datetime.date | None = None) -> dict[int, Decimal]:
    return {r.pk: balance(r, until) for r in Reserve.objects.filter(organization=org)}


def _never_negative(reserve: Reserve, extra: list[tuple[datetime.date, Decimal]], skip=None):
    """Prüft den Verlauf der Rücklage Tag für Tag (mit geplanten Änderungen)."""
    steps = [
        (m.date, m.signed)
        for m in ReserveMovement.objects.filter(reserve=reserve).order_by("date", "pk")
        if m.pk != skip
    ] + extra
    running = ZERO
    for day, amount in sorted(steps, key=lambda s: (s[0], -s[1])):
        running += amount
        if running < 0:
            raise ValidationError(
                f"Die Rücklage „{reserve.name}“ fiele am {day:%d.%m.%Y} unter null."
            )


def validate_reserve(data: dict) -> None:
    kind = data.get("kind")
    if kind in NEEDS_PURPOSE and not (data.get("purpose") or "").strip():
        raise ValidationError(
            {"purpose": "Bitte den Zweck bzw. das Vorhaben angeben (§ 62 Abs. 1 Nr. 1/2 AO)."}
        )


def add_movement(org, reserve: Reserve, data: dict, user) -> ReserveMovement:
    """Zuführung oder Auflösung anlegen (innerhalb einer Transaktion aufrufen)."""
    check_enabled(org)
    direction = data.get("direction")
    if direction not in ReserveMovement.Direction.values:
        raise ValidationError({"direction": "Bitte Zuführung oder Auflösung wählen."})
    try:
        day = datetime.date.fromisoformat(str(data.get("date") or ""))
    except ValueError as exc:
        raise ValidationError({"date": "Bitte ein Datum angeben."}) from exc
    try:
        amount = Decimal(str(data.get("amount") or "")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValidationError({"amount": "Bitte einen Betrag angeben."}) from exc
    if amount <= 0:
        raise ValidationError({"amount": "Der Betrag muss größer als null sein."})
    if direction == ReserveMovement.Direction.ADD and not reserve.is_active:
        raise ValidationError("Einer archivierten Rücklage lässt sich nichts zuführen.")
    services.ensure_open(org, date=day)
    signed = amount if direction == ReserveMovement.Direction.ADD else -amount
    _never_negative(reserve, [(day, signed)])
    return ReserveMovement.objects.create(
        organization=org,
        reserve=reserve,
        direction=direction,
        date=day,
        year=org.fiscal_year_of(day),
        amount=amount,
        note=(data.get("note") or "").strip()[:500],
        created_by=user,
        created_by_name=(user.get_full_name() or user.email)[:200],
    )


def delete_movement(org, movement: ReserveMovement) -> None:
    services.ensure_open(org, year=movement.year)
    _never_negative(movement.reserve, [], skip=movement.pk)
    movement.delete()


def overview(org) -> dict:
    """Rücklagen heute und die Mittel auf den Konten (heute)."""
    today = datetime.date.today()
    reserves = list(Reserve.objects.filter(organization=org))
    by_id = balances(org)
    funds = sum(services.balances(org.pk).values(), ZERO)
    total = sum(by_id.values(), ZERO)
    return {
        "reserves": reserves,
        "balances": by_id,
        "total": total,
        "funds": funds,
        "free": funds - total,
        "date": today,
    }
