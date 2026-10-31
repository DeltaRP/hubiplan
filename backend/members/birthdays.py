"""Anstehende Geburtstage der aktuellen Mitglieder (Kachel auf der Startseite)."""

from __future__ import annotations

import datetime

from django.db.models import Exists, OuterRef, Q

from organizations.models import Organization

from .models import DepartmentMembership, Membership, MembershipPeriod


def unit_names(membership_ids, on: datetime.date) -> dict[int, str]:
    """Kurznamen der Untereinheiten (z. B. Züge), in denen die Mitglieder am Tag sind."""
    names: dict[int, list[str]] = {}
    rows = (
        DepartmentMembership.objects.filter(membership_id__in=list(membership_ids))
        .filter(valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .select_related("department")
        .order_by("department__name")
    )
    for dm in rows:
        name = dm.department.display_name
        if name not in names.setdefault(dm.membership_id, []):
            names[dm.membership_id].append(name)
    return {mid: ", ".join(n) for mid, n in names.items()}


def _birthday_in(birth: datetime.date, year: int) -> datetime.date:
    """Geburtstag im Jahr ``year``; der 29. Februar fällt sonst auf den 28."""
    try:
        return birth.replace(year=year)
    except ValueError:
        return datetime.date(year, 2, 28)


def birthdays_between(org: Organization, start: datetime.date, end: datetime.date) -> list[dict]:
    """Geburtstage im Zeitraum [start, end] von Mitgliedern, die darin Mitglied sind."""
    # Vorauswahl: eine einzelne Periode berührt den Zeitraum (nicht Beginn aus der einen,
    # Ende aus einer anderen Periode)
    touching = MembershipPeriod.objects.filter(
        membership=OuterRef("pk"), entry_date__lte=end
    ).filter(Q(exit_date__isnull=True) | Q(exit_date__gte=start))
    memberships = (
        Membership.objects.filter(organization=org, purged_at__isnull=True)
        .filter(Exists(touching))
        .select_related("person")
        .prefetch_related("periods")
    )
    rows = []
    for m in memberships:
        birth = m.person.birth_date
        if birth is None:
            continue
        periods = [(p.entry_date, p.exit_date) for p in m.periods.all()]
        for year in range(start.year, end.year + 1):
            day = _birthday_in(birth, year)
            # Nur wer am Geburtstag selbst Mitglied ist (Audit 31.10. M31-01): nicht nach
            # dem Austritt, nicht vor dem (Wieder-)Eintritt
            member_then = any(a <= day and (b is None or day <= b) for a, b in periods)
            if start <= day <= end and day > birth and member_then:
                rows.append(
                    {
                        "member_id": m.pk,
                        "first_name": m.person.first_name,
                        "last_name": m.person.last_name,
                        "date": day,
                        "age": year - birth.year,
                    }
                )
    units = unit_names({r["member_id"] for r in rows}, start)
    for r in rows:
        r["units"] = units.get(r["member_id"], "")
    rows.sort(key=lambda r: (r["date"], r["last_name"], r["first_name"]))
    return rows
