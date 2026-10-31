"""Mitgliederentwicklung: Bestand, Ein- und Austritte, Arten, Abteilungen, Alter.

Gerechnet wird aus den Zeiträumen (Mitgliedschaft, Mitgliedsart, Abteilung).
Ein Zeitraum zählt von seinem ersten bis einschließlich seinem letzten Tag. Der
Bestand an einem Stichtag sind die Mitglieder, die über den Stichtag hinaus
dabei sind; wer am Stichtag austritt, zählt als Austritt dieses Zeitraums.
So gilt immer: Bestand am Ende = Bestand am Anfang + Eintritte − Austritte.

Drei Sichten:

- Verein: alle Mitgliedschaften des Vereins
- Dachverband: Zeiten mit einer gemeldeten Mitgliedsart in allen Vereinen
- Abteilung: Zeiten in der Abteilung (innerhalb der Mitgliedschaft)
"""

from __future__ import annotations

import datetime
import statistics as pstats
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable

from core import timeline
from organizations.models import Department, Organization
from organizations.tree import subtree_ids

from .models import (
    DepartmentMembership,
    ExitReason,
    Membership,
    MembershipPeriod,
    MemberType,
    MemberTypeAssignment,
)

ONE_DAY = datetime.timedelta(days=1)
MAX = datetime.date.max

# (Mitgliedschaft, erster Tag, letzter Tag oder None)
Piece = tuple[int, datetime.date, datetime.date | None]

AGE_GROUPS = [
    (0, 17, "unter 18"),
    (18, 29, "18 bis 29"),
    (30, 39, "30 bis 39"),
    (40, 49, "40 bis 49"),
    (50, 59, "50 bis 59"),
    (60, 69, "60 bis 69"),
    (70, 79, "70 bis 79"),
    (80, 999, "80 und älter"),
]


def _intersect(a: list[Piece], b: list[Piece], *, sub: bool = False) -> list[Piece]:
    """Schnitt zweier Zeitraumlisten derselben Mitgliedschaften.

    ``sub``: Teilzeiten für Aufschlüsselungen (Art, Abteilung). Ein Wechsel
    innerhalb der Mitgliedschaft zählt schon am Vortag, wie das Ende der
    vorherigen Zeit – so ergeben die Teile am Stichtag immer den Bestand.
    """
    by_member: dict[int, list[Piece]] = defaultdict(list)
    for p in b:
        by_member[p[0]].append(p)
    out: list[Piece] = []
    for mid, a_from, a_until in a:
        for _, b_from, b_until in by_member.get(mid, ()):
            start = max(a_from, b_from)
            end = min(a_until or MAX, b_until or MAX)
            if start <= end:
                if sub and start > a_from:
                    start -= ONE_DAY
                out.append((mid, start, None if end == MAX else end))
    return out


def _merge(pieces: Iterable[Piece]) -> list[Piece]:
    """Aneinander grenzende oder überlappende Zeiten je Mitgliedschaft zusammenfassen."""
    out: list[Piece] = []
    for p in sorted(pieces, key=lambda p: (p[0], p[1])):
        if out and out[-1][0] == p[0]:
            last = out[-1]
            last_end = last[2] or MAX
            if last_end == MAX or p[1] <= last_end + ONE_DAY:
                end = None if (p[2] is None or last[2] is None) else max(last_end, p[2])
                out[-1] = (last[0], last[1], end)
                continue
        out.append(p)
    return out


class _Counter:
    """Bestand zu beliebigen Stichtagen über sortierte Anfangs- und Endtage."""

    def __init__(self, pieces: Iterable[Piece]):
        self.starts = sorted(p[1] for p in pieces)
        self.ends = sorted(p[2] for p in pieces if p[2] is not None)

    def at(self, day: datetime.date) -> int:
        return bisect_right(self.starts, day) - bisect_right(self.ends, day)


def _between(days: list[datetime.date], start: datetime.date, end: datetime.date) -> int:
    return bisect_right(days, end) - bisect_right(days, start - ONE_DAY)


def _age(birth: datetime.date, on: datetime.date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


class _Source:
    """Rohdaten einer Sicht: Grundzeiten, Austrittsgründe, Gruppen."""

    def __init__(self):
        self.base: list[Piece] = []
        # Grund je (Mitgliedschaft, letzter Tag), wenn die Mitgliedschaft dort endet
        self.reasons: dict[tuple[int, datetime.date], str] = {}
        self.other_reason = ("", "")
        self.types: list[tuple[int, str, list[Piece]]] = []
        self.groups_title = ""
        self.groups: list[tuple[int, str, list[Piece]]] = []
        self.groups_rest: str = ""
        self.birth: dict[int, datetime.date] = {}

    def load_periods(self, periods):
        out: list[Piece] = []
        for mid, entry, exit_date, reason in periods:
            out.append((mid, entry, exit_date))
            if exit_date is not None:
                self.reasons[(mid, exit_date)] = reason or ExitReason.EXIT
        return out


def _type_pieces(assignments) -> dict[int, list[Piece]]:
    by_type: dict[int, list[Piece]] = defaultdict(list)
    for mid, type_id, valid_from, valid_until in assignments:
        by_type[type_id].append((mid, valid_from, valid_until))
    return by_type


def club_source(org: Organization) -> _Source:
    src = _Source()
    src.base = src.load_periods(
        MembershipPeriod.objects.filter(organization=org).values_list(
            "membership_id", "entry_date", "exit_date", "exit_reason"
        )
    )
    by_type = _type_pieces(
        MemberTypeAssignment.objects.filter(organization=org).values_list(
            "membership_id", "member_type_id", "valid_from", "valid_until"
        )
    )
    for t in MemberType.objects.filter(organization=org):
        if t.pk in by_type:
            src.types.append((t.pk, t.name, _merge(_intersect(src.base, by_type[t.pk], sub=True))))
    by_dept: dict[int, list[Piece]] = defaultdict(list)
    for mid, dept_id, valid_from, valid_until in DepartmentMembership.objects.filter(
        organization=org
    ).values_list("membership_id", "department_id", "valid_from", "valid_until"):
        by_dept[dept_id].append((mid, valid_from, valid_until))
    if by_dept:
        src.groups_title = org.department_label or "Abteilung"
        for d in Department.objects.filter(organization=org).order_by("sort_order", "name"):
            if d.pk in by_dept:
                src.groups.append(
                    (d.pk, d.display_name, _merge(_intersect(src.base, by_dept[d.pk], sub=True)))
                )
        src.groups_rest = f"ohne {org.department_label or 'Abteilung'}"
    src.birth = dict(
        Membership.objects.filter(organization=org).values_list("pk", "person__birth_date")
    )
    return src


def federation_source(federation: Organization) -> _Source:
    src = _Source()
    periods = src.load_periods(
        MembershipPeriod.objects.filter(membership__scope=federation).values_list(
            "membership_id", "entry_date", "exit_date", "exit_reason"
        )
    )
    assignments = MemberTypeAssignment.objects.filter(membership__scope=federation)
    reported = _merge(
        (mid, a, b)
        for mid, a, b in assignments.filter(member_type__reported=True).values_list(
            "membership_id", "valid_from", "valid_until"
        )
    )
    src.base = _merge(_intersect(periods, reported))
    src.other_reason = ("unreported", "Wechsel zu nicht gemeldeter Mitgliedsart")
    by_type = _type_pieces(
        assignments.filter(member_type__reported=True).values_list(
            "membership_id", "member_type_id", "valid_from", "valid_until"
        )
    )
    # Mitgliedsarten heißen in den Vereinen oft gleich: nach Namen zusammenfassen
    names: dict[str, list[Piece]] = defaultdict(list)
    for t in MemberType.objects.filter(pk__in=by_type.keys()):
        names[t.name].extend(by_type[t.pk])
    for i, name in enumerate(sorted(names, key=str.lower), start=1):
        src.types.append((i, name, _merge(_intersect(src.base, names[name], sub=True))))
    club_of = dict(Membership.objects.filter(scope=federation).values_list("pk", "organization_id"))
    by_club: dict[int, list[Piece]] = defaultdict(list)
    for p in src.base:
        by_club[club_of[p[0]]].append(p)
    src.groups_title = federation.department_label or "Verein"
    for club in Organization.objects.filter(pk__in=by_club.keys()).order_by("name"):
        src.groups.append((club.pk, club.display_name, by_club[club.pk]))
    src.birth = dict(
        Membership.objects.filter(scope=federation).values_list("pk", "person__birth_date")
    )
    return src


def department_source(dept: Department) -> _Source:
    org = dept.organization
    src = _Source()
    periods = src.load_periods(
        MembershipPeriod.objects.filter(organization=org).values_list(
            "membership_id", "entry_date", "exit_date", "exit_reason"
        )
    )
    in_dept = DepartmentMembership.objects.filter(
        organization=org, department_id__in=subtree_ids(dept)
    ).values_list("membership_id", "valid_from", "valid_until")
    src.base = _merge(_intersect(periods, list(in_dept)))
    src.other_reason = (
        "department",
        f"{dept.organization.department_label or 'Abteilung'} verlassen",
    )
    by_type = _type_pieces(
        MemberTypeAssignment.objects.filter(organization=org).values_list(
            "membership_id", "member_type_id", "valid_from", "valid_until"
        )
    )
    for t in MemberType.objects.filter(organization=org):
        if t.pk in by_type:
            pieces = _merge(_intersect(src.base, by_type[t.pk], sub=True))
            if pieces:
                src.types.append((t.pk, t.name, pieces))
    ids = {p[0] for p in src.base}
    src.birth = dict(Membership.objects.filter(pk__in=ids).values_list("pk", "person__birth_date"))
    return src


def _series(items, line: timeline.Timeline, total: _Counter | None = None, rest: str = ""):
    series = []
    for key, name, pieces in items:
        c = _Counter(pieces)
        values = [c.at(b.end) for b in line.buckets]
        if any(values) or c.at(line.start - ONE_DAY):
            series.append({"id": key, "name": name, "values": values})
    if rest and total is not None:
        anywhere = _Counter(_merge(p for _, _, pieces in items for p in pieces))
        values = [total.at(b.end) - anywhere.at(b.end) for b in line.buckets]
        if any(values):
            series.append({"id": None, "name": rest, "values": values})
    return series


def _member_ages(src: _Source, base: list[Piece], day: datetime.date) -> list[int]:
    """Alter aller Mitglieder mit Geburtsdatum, die am Stichtag Mitglied sind."""
    current = {p[0] for p in base if p[1] <= day and (p[2] is None or p[2] > day)}
    ages = [_age(src.birth[mid], day) for mid in current if src.birth.get(mid) is not None]
    # Unmögliche Alter (Geburt nach dem Stichtag) weder im Durchschnitt noch in den Gruppen,
    # damit beide dieselbe Grundgesamtheit haben (Audit 31.10. M31-03)
    return [a for a in ages if a >= 0]


def _ages(ages: list[int]) -> list[int]:
    counts = [0] * len(AGE_GROUPS)
    for age in ages:
        for i, (low, high, _) in enumerate(AGE_GROUPS):
            if low <= age <= high:
                counts[i] += 1
                break
    return counts


def _age_summary(ages: list[int]) -> dict:
    """Durchschnittsalter und Standardabweichung, auf eine Stelle gerundet.

    Der Bestand ist vollständig erfasst, keine Stichprobe: Streuung über alle (n, nicht n−1),
    bei einer Person 0 (Fachfrage 7, Audit 31.10.)."""
    if not ages:
        return {"count": 0, "mean": None, "sd": None}
    sd = round(pstats.pstdev(ages), 1)
    return {"count": len(ages), "mean": round(pstats.fmean(ages), 1), "sd": sd}


def statistics(src: _Source, params) -> dict:
    earliest = min((p[1] for p in src.base), default=None)
    line = timeline.build(params, earliest=earliest)
    total = _Counter(src.base)
    starts = total.starts
    ends = total.ends
    before = line.start - ONE_DAY

    buckets = []
    for b in line.buckets:
        buckets.append(
            {
                **b.as_dict(),
                "count": total.at(b.end),
                "entries": _between(starts, b.start, b.end),
                "exits": _between(ends, b.start, b.end),
            }
        )

    labels = dict(ExitReason.choices)
    reasons: dict[str, int] = defaultdict(int)
    for mid, _, last in src.base:
        if last is not None and line.start <= last <= line.end:
            reason = src.reasons.get((mid, last))
            reasons[reason or src.other_reason[0] or ExitReason.EXIT] += 1
    if src.other_reason[0]:
        labels[src.other_reason[0]] = src.other_reason[1]
    order = [*ExitReason.values, src.other_reason[0]]
    exit_reasons = [
        {"reason": r, "label": labels.get(r, r), "count": reasons[r]}
        for r in order
        if reasons.get(r)
    ]

    start_ages = _member_ages(src, src.base, before)
    end_ages = _member_ages(src, src.base, line.end)
    return {
        **line.as_dict(),
        "earliest": earliest,
        "buckets": buckets,
        "summary": {
            "start": total.at(before),
            "end": total.at(line.end),
            "entries": _between(starts, line.start, line.end),
            "exits": _between(ends, line.start, line.end),
        },
        "types": _series(src.types, line),
        "groups_title": src.groups_title,
        "groups": _series(src.groups, line, total, src.groups_rest),
        "exit_reasons": exit_reasons,
        "ages": {
            "groups": [g[2] for g in AGE_GROUPS],
            # Stichtag der Anfangswerte: der Tag vor Beginn des Zeitraums
            "start_on": before,
            "start": _ages(start_ages),
            "end": _ages(end_ages),
            "start_summary": _age_summary(start_ages),
            "end_summary": _age_summary(end_ages),
        },
    }
