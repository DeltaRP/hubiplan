"""Erfundene Demo-Termine für die Pilotorganisationen (wiederholbar)."""

from __future__ import annotations

import datetime

from django.utils import timezone

from .models import Event, EventCategory
from .services import ensure_categories


def _at(day: datetime.date, hour: int = 0, minute: int = 0) -> datetime.datetime:
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, minute)),
        timezone.get_current_timezone(),
    )


def _cat(org, name: str) -> EventCategory | None:
    return EventCategory.objects.filter(organization=org, name=name).first()


def _event(org, title: str, start, end, department=None, **extra) -> None:
    Event.objects.get_or_create(
        organization=org,
        department=department,
        title=title,
        defaults={"starts_at": start, "ends_at": end, **extra},
    )


def _next(month: int, day: int) -> datetime.date:
    """Nächster Jahrestag ab heute, damit die Demo-Termine in der Zukunft liegen."""
    today = timezone.localdate()
    value = datetime.date(today.year, month, day)
    return value if value >= today else datetime.date(today.year + 1, month, day)


def seed_events(orgs) -> None:
    federation, club = orgs["federation"], orgs["club"]
    year = timezone.localdate().year
    for org in (federation, club):
        ensure_categories(org)
    if not Event.objects.filter(organization__in=[federation, club]).exists():
        _seed(federation, club, year)
    _seed_rsvp(club)


def _seed_rsvp(club) -> None:
    """Zu- und Absagen für zwei Vereinstermine (M13), auch bei schon angelegten Demo-Daten."""
    for title, guests in (("Jahreshauptversammlung", False), ("Königsschießen", True)):
        event = Event.objects.filter(
            organization=club, department__isnull=True, title=title, repeat="none"
        ).first()
        if event is None or event.rsvp_enabled:
            continue
        event.rsvp_enabled = True
        event.rsvp_guests = guests
        event.rsvp_deadline = event.starts_at - datetime.timedelta(days=3)
        event.remind_days = 2
        event.save(update_fields=["rsvp_enabled", "rsvp_guests", "rsvp_deadline", "remind_days"])


def _seed(federation, club, year: int) -> None:
    d = datetime.date
    # Dachverband
    _event(
        federation,
        "Schützenfest",
        _at(_next(8, 29)),
        _at(_next(8, 29) + datetime.timedelta(days=3)),
        all_day=True,
        visibility="public",
        location="Festplatz Grimlinghausen",
        category=_cat(federation, "Fest"),
        description="Großes Schützenfest mit Parade, Königsehrung und Festball.",
    )
    _event(
        federation,
        "Martinszug",
        _at(_next(11, 11), 17, 30),
        _at(_next(11, 11), 19),
        visibility="public",
        location="Kirchplatz",
        category=_cat(federation, "Umzug"),
    )
    _event(
        federation,
        "Frühjahrsversammlung der Vereine",
        _at(_next(3, 20), 19, 30),
        _at(_next(3, 20), 22),
        visibility="members",
        location="Bürgerhaus",
        category=_cat(federation, "Versammlung"),
    )
    _event(
        federation,
        "Vorstandssitzung BSV",
        _at(d(year, 1, 12), 19),
        _at(d(year, 1, 12), 21),
        visibility="board",
        repeat="monthly",
        category=_cat(federation, "Versammlung"),
    )
    # Verein
    _event(
        club,
        "Jahreshauptversammlung",
        _at(_next(2, 27), 19),
        _at(_next(2, 27), 22),
        visibility="members",
        location="Vereinsheim",
        address="Hubertusweg 1, 41468 Neuss",
        category=_cat(club, "Versammlung"),
    )
    _event(
        club,
        "Königsschießen",
        _at(_next(6, 13), 14),
        _at(_next(6, 13), 19),
        visibility="public",
        location="Schießstand",
        category=_cat(club, "Schießen"),
    )
    _event(
        club,
        "Übungsschießen",
        _at(_next(4, 7), 19, 30),
        _at(_next(4, 7), 21, 30),
        visibility="members",
        repeat="weekly",
        repeat_interval=2,
        repeat_until=_next(4, 7) + datetime.timedelta(weeks=9),
        location="Schießstand",
        category=_cat(club, "Schießen"),
    )
    _event(
        club,
        "Vorstandssitzung",
        _at(d(year, 1, 6), 19),
        _at(d(year, 1, 6), 21),
        visibility="board",
        repeat="monthly",
        category=_cat(club, "Versammlung"),
    )
    # Zwei Züge mit eigenen Terminen
    for i, zug in enumerate(club.departments.order_by("sort_order")[:2]):
        _event(
            club,
            "Zugversammlung",
            _at(d(year, 1, 15 + i), 20),
            _at(d(year, 1, 15 + i), 22),
            department=zug,
            visibility="members",
            repeat="monthly",
            category=_cat(club, "Versammlung"),
        )
