"""Mitgliedsdauer und Jubiläen (Meilenstein 4).

- Dauer im Verein: Summe der Zeiträume, in denen eine Art galt, die „zählt für
  Mitgliedsdauer“ trägt.
- Dauer im Dachverband: alle gemeldeten Zeiten in allen seinen Vereinen
  (Überschneidungen zählen einmal), je nach Regel des Dachverbands alle
  gemeldeten oder nur gemeldete aktive Zeiten.
- Jubiläum: der Tag, an dem die gezählte Zeit N Jahre erreicht. Lücken
  verschieben das Jubiläum entsprechend nach hinten.
- Genauigkeit (je Organisation): tagesgenau wie oben; monats- oder jahresgenau
  zählen ganze Monate bzw. Jahre (angefangene zählen voll), das Jubiläum fällt
  dann auf einen ganzen Monat bzw. ein ganzes Jahr (Eintritt 2001 → 25 Jahre
  im ganzen Jahr 2026). Gespeichert bleibt alles tagesgenau.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from dateutil.relativedelta import relativedelta

from core.tenancy import rls_bypass
from organizations.models import Organization

from .models import Membership, overlaps, today

Range = tuple[datetime.date, datetime.date | None]


def merge(ranges: Iterable[Range]) -> list[Range]:
    """Überschneidende oder angrenzende Zeiträume zusammenfassen."""
    result: list[list] = []
    for start, end in sorted(ranges, key=lambda r: r[0]):
        if result:
            last = result[-1]
            last_end = last[1]
            if last_end is None or start <= last_end + datetime.timedelta(days=1):
                if last_end is not None and (end is None or end > last_end):
                    last[1] = end
                continue
        result.append([start, end])
    return [(s, e) for s, e in result]


def counted_ranges(membership: Membership, predicate) -> list[Range]:
    """Teile der Zeiträume, in denen eine Art galt, die ``predicate`` erfüllt."""
    ranges = []
    periods = list(membership.periods.all())
    assignments = list(membership.type_assignments.all())
    for period in periods:
        for ta in assignments:
            if not predicate(ta.member_type):
                continue
            if overlaps(period.entry_date, period.exit_date, ta.valid_from, ta.valid_until):
                start = max(period.entry_date, ta.valid_from)
                ends = [d for d in (period.exit_date, ta.valid_until) if d]
                ranges.append((start, min(ends) if ends else None))
    return merge(ranges)


def days_in(ranges: list[Range], until: datetime.date) -> int:
    total = 0
    for start, end in ranges:
        if start > until:
            continue
        stop = min(end, until) if end else until
        total += (stop - start).days + 1
    return total


DAY, MONTH, YEAR = "day", "month", "year"


def _unit(d: datetime.date, precision: str) -> int:
    return d.year * 12 + d.month - 1 if precision == MONTH else d.year


def _unit_start(index: int, precision: str) -> datetime.date:
    if precision == MONTH:
        return datetime.date(index // 12, index % 12 + 1, 1)
    return datetime.date(index, 1, 1)


def unit_end(d: datetime.date, precision: str) -> datetime.date:
    """Letzter Tag des Monats bzw. Jahres, in dem ``d`` liegt (tagesgenau: ``d``)."""
    if precision == MONTH:
        return d.replace(day=1) + relativedelta(months=1, days=-1)
    if precision == YEAR:
        return datetime.date(d.year, 12, 31)
    return d


def jubilee_date(ranges: list[Range], years: int, precision: str = DAY) -> datetime.date | None:
    """Tag, an dem die gezählte Zeit ``years`` Jahre erreicht (kann in der Zukunft liegen).

    Monats-/jahresgenau: erster Tag des Monats bzw. Jahres, in dem das Jubiläum liegt.
    """
    if not ranges:
        return None
    try:
        return _jubilee_date(ranges, years, precision)
    except (OverflowError, ValueError):
        return None  # liegt jenseits des darstellbaren Kalenders (Jahr 9999)


def _jubilee_date(ranges: list[Range], years: int, precision: str) -> datetime.date | None:
    if precision in (MONTH, YEAR):
        return _unit_jubilee(ranges, years, precision)
    first = ranges[0][0]
    needed = (first + relativedelta(years=years) - first).days
    counted = 0
    for start, end in ranges:
        length = None if end is None else (end - start).days + 1
        if length is None or counted + length >= needed:
            return start + datetime.timedelta(days=needed - counted)
        counted += length
    return None  # mit den bisherigen (beendeten) Zeiten nicht erreicht


def _unit_jubilee(ranges: list[Range], years: int, precision: str) -> datetime.date | None:
    units: list[list] = []
    for start, end in ranges:
        s, e = _unit(start, precision), (None if end is None else _unit(end, precision))
        if units and (units[-1][1] is None or s <= units[-1][1] + 1):
            if units[-1][1] is not None and (e is None or e > units[-1][1]):
                units[-1][1] = e
            continue
        units.append([s, e])
    needed = years * (12 if precision == MONTH else 1)
    counted = 0
    for s, e in units:
        length = None if e is None else e - s + 1
        if length is None or counted + length >= needed:
            return _unit_start(s + needed - counted, precision)
        counted += length
    return None


@dataclass
class Duration:
    days: int
    years: int
    ranges: list[Range]

    @classmethod
    def of(cls, ranges: list[Range], on: datetime.date, precision: str = DAY) -> Duration:
        days = days_in(ranges, on)
        years = 0
        while True:
            d = jubilee_date(ranges, years + 1, precision)
            if d is None or d > on:
                break
            years += 1
        return cls(days=days, years=years, ranges=ranges)


def club_ranges(membership: Membership) -> list[Range]:
    return counted_ranges(membership, lambda t: t.counts_for_duration)


def federation_predicate(federation: Organization):
    only_active = federation.federation_duration_rule == "active_reported"
    return lambda t: t.reported and (t.active or not only_active)


def federation_ranges(person, federation: Organization) -> list[Range]:
    """Gemeldete Zeiten der Person in allen Vereinen des Dachverbands (Systemabfrage)."""
    predicate = federation_predicate(federation)
    ranges: list[Range] = []
    with rls_bypass():
        memberships = Membership.objects.filter(person=person, scope=federation).prefetch_related(
            "periods", "type_assignments__member_type"
        )
        for membership in memberships:
            ranges.extend(counted_ranges(membership, predicate))
    return merge(ranges)


def duration_info(membership: Membership, on: datetime.date | None = None) -> dict:
    on = on or today()
    club = membership.organization
    club_d = Duration.of(club_ranges(membership), on, club.date_precision)
    info = {
        "club": {
            "days": club_d.days,
            "years": club_d.years,
            "precision": club.date_precision,
            "next": next_jubilee(club_d.ranges, club.jubilee_years, on, club.date_precision),
        },
        "federation": None,
    }
    federation = club.federation
    if federation is not None:
        fed_p = federation.date_precision
        fed_d = Duration.of(federation_ranges(membership.person, federation), on, fed_p)
        info["federation"] = {
            "days": fed_d.days,
            "years": fed_d.years,
            "precision": fed_p,
            "rule": federation.get_federation_duration_rule_display(),
            "next": next_jubilee(fed_d.ranges, federation.jubilee_years, on, fed_p),
        }
    return info


def next_jubilee(
    ranges: list[Range], levels: list[int], on: datetime.date, precision: str = DAY
) -> dict | None:
    for years in sorted(levels):
        d = jubilee_date(ranges, years, precision)
        if d and d > on:
            return {"years": years, "date": d}
    return None


def jubilees_between(club: Organization, start: datetime.date, end: datetime.date) -> list[dict]:
    """Jubiläen der Mitglieder eines Vereins im Zeitraum [start, end], die am Jubiläum
    selbst Mitglied waren.

    Enthält die Vereinsjubiläen und – bei Vereinen im Dachverband – die
    Dachverbandsjubiläen nach dessen Stufen und Regel. Monats-/jahresgenau
    zählt ein Jubiläum, wenn sein Monat bzw. Jahr den Zeitraum berührt.
    """
    result = []
    memberships = (
        Membership.objects.filter(organization=club, purged_at__isnull=True)
        .select_related("person", "person__federation")
        .prefetch_related("periods", "type_assignments__member_type")
    )
    federation = club.federation
    fed_levels = federation.jubilee_years if federation else []
    for membership in memberships:
        periods = list(membership.periods.all())

        def member_during(a, b, periods=periods):
            # Fachfrage 10 (Audit 31.10.): wer am Jubiläum selbst Mitglied war, nicht nur
            # wer am Anfang oder Ende des gewählten Zeitraums dabei war
            return any(
                p.entry_date <= b and (p.exit_date is None or p.exit_date >= a) for p in periods
            )

        if not member_during(start, end):
            continue
        ranges = club_ranges(membership)
        precision = club.date_precision
        for years in club.jubilee_years:
            d = jubilee_date(ranges, years, precision)
            if d and d <= end and unit_end(d, precision) >= start:
                if member_during(d, unit_end(d, precision)):
                    result.append(_row(membership, "club", club, years, d, precision))
        if federation and fed_levels:
            f_ranges = federation_ranges(membership.person, federation)
            fed_p = federation.date_precision
            for years in fed_levels:
                d = jubilee_date(f_ranges, years, fed_p)
                if d and d <= end and unit_end(d, fed_p) >= start:
                    if member_during(d, unit_end(d, fed_p)):
                        result.append(_row(membership, "federation", federation, years, d, fed_p))
    from .birthdays import unit_names

    units = unit_names({r["member_id"] for r in result}, start)
    for r in result:
        r["units"] = units.get(r["member_id"], "")
    result.sort(key=lambda r: (r["date"], r["last_name"], r["first_name"]))
    return result


def _row(
    membership: Membership,
    kind: str,
    org,
    years: int,
    d: datetime.date,
    precision: str = DAY,
) -> dict:
    fm = getattr(membership.person, "federation", None)
    return {
        "member_id": membership.pk,
        "last_name": membership.person.last_name,
        "first_name": membership.person.first_name,
        "birth_date": membership.person.birth_date,
        "member_number": fm.member_number if fm else None,
        "kind": kind,
        "organization": org.name,
        "organization_label": org.label,
        # Kurzname für enge Stellen (Startseite, Liste); Exporte nutzen den vollen Namen
        "organization_short": org.display_name,
        "years": years,
        "date": d,
        "precision": precision,
    }
