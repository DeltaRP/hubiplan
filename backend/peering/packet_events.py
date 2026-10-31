"""Paket „Termine“ (P3): nach oben gemäß „nach oben freigeben“, nach unten gemäß
„nach unten freigeben“ – dieselben Schalter wie innerhalb einer Instanz.

Übermittelt werden nur nicht interne Termine der Einheit selbst (ohne die ihrer
Untereinheiten), ab 90 Tagen in der Vergangenheit. Zu- und Absagen,
Teilnehmerlisten, Erinnerungen und Anhänge fließen nie.
"""

from __future__ import annotations

import datetime

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .packets import BOTH, DOWN, Packet, direction_of, register

LIMIT = 2000
PAST = datetime.timedelta(days=90)
FIELDS = (
    "title",
    "description",
    "location",
    "address",
    "all_day",
    "visibility",
    "repeat",
    "repeat_interval",
    "is_cancelled",
    "cancel_note",
)


def _events(coupling):
    from events.models import Event
    from events.services import SHARED, down, up

    flag = down("organization") if direction_of(coupling) == DOWN else up("organization")
    since = timezone.now() - PAST
    return (
        Event.objects.filter(
            organization=coupling.local_unit,
            department__isnull=True,
            visibility__in=SHARED,
            remote_uid="",
        )
        .filter(flag)
        .filter(
            Q(ends_at__gte=since)
            | ~Q(repeat="none") & (Q(repeat_until__isnull=True) | Q(repeat_until__gte=since.date()))
        )
        .select_related("category")
        .prefetch_related("exceptions")
        .order_by("starts_at", "pk")[:LIMIT]
    )


def build(coupling, level):
    items = []
    for e in _events(coupling):
        item = {f: getattr(e, f) for f in FIELDS}
        item.update(
            {
                "uid": str(e.pk),
                "starts_at": e.starts_at.isoformat(),
                "ends_at": e.ends_at.isoformat(),
                "repeat_until": e.repeat_until.isoformat() if e.repeat_until else None,
                "changed_at": e.changed_at.isoformat() if e.changed_at else None,
                "category": {"name": e.category.name, "color": e.category.color}
                if e.category
                else None,
                "exceptions": [
                    {
                        "original_start": x.original_start.isoformat(),
                        "is_cancelled": x.is_cancelled,
                        "starts_at": x.starts_at.isoformat() if x.starts_at else None,
                        "ends_at": x.ends_at.isoformat() if x.ends_at else None,
                        "note": x.note,
                    }
                    for x in e.exceptions.all()
                ],
            }
        )
        items.append(item)
    return {"events": items}


def _dt(value):
    parsed = parse_datetime(str(value)) if value else None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _category(org, data):
    from events.models import EventCategory

    if not isinstance(data, dict) or not data.get("name"):
        return None
    name = str(data["name"])[:80]
    color = str(data.get("color") or "")
    if not (len(color) == 7 and color.startswith("#")):
        color = "#2f6f4f"
    cat, _ = EventCategory.objects.get_or_create(
        organization=org, name=name, defaults={"color": color}
    )
    return cat


def apply(coupling, data):
    from core.tenancy import unit_context

    # Termine gehören dem Platzhalter der fernen Einheit: nur in dessen Bereich schreiben.
    # Eine ferne Untereinheit eines Vereins (Schritt 8) liegt im Datenbereich des Vereins.
    placeholder = coupling.remote_unit
    with unit_context(placeholder.organization_id or placeholder.pk):
        _apply(coupling, data)


def _apply(coupling, data):
    from events.models import Event, EventException
    from organizations.models import Organization

    placeholder = coupling.remote_unit
    if placeholder.type == Organization.Type.UNIT:
        org = placeholder.organization
        own = {"organization": org, "department_id": placeholder.pk}
    else:
        org = placeholder
        own = {"organization": org}
    items = data.get("events") if data.get("level") else []
    if not isinstance(items, list):
        items = []
    keep = set()
    choices = {
        "visibility": {"public", "members"},
        "repeat": {"none", "weekly", "monthly", "yearly"},
    }
    for item in items[:LIMIT]:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid", ""))[:80]
        starts, ends = _dt(item.get("starts_at")), _dt(item.get("ends_at"))
        if not uid or starts is None or ends is None or ends < starts:
            continue
        values = {
            "title": str(item.get("title") or "Termin")[:200],
            "description": str(item.get("description") or "")[:5000],
            "location": str(item.get("location") or "")[:200],
            "address": str(item.get("address") or "")[:300],
            "all_day": bool(item.get("all_day")),
            "starts_at": starts,
            "ends_at": ends,
            "is_cancelled": bool(item.get("is_cancelled")),
            "cancel_note": str(item.get("cancel_note") or "")[:300],
            "changed_at": _dt(item.get("changed_at")),
            "repeat_until": parse_date(str(item["repeat_until"]))
            if item.get("repeat_until")
            else None,
            "share_up": True,
            "share_down": True,
            "rsvp_enabled": False,
            "category": _category(org, item.get("category")),
        }
        for field, allowed in choices.items():
            value = str(item.get(field) or "")
            values[field] = (
                value if value in allowed else ("members" if field == "visibility" else "none")
            )
        try:
            values["repeat_interval"] = max(1, min(int(item.get("repeat_interval") or 1), 52))
        except (TypeError, ValueError):
            values["repeat_interval"] = 1
        event, _ = Event.objects.update_or_create(**own, remote_uid=uid, defaults=values)
        keep.add(event.pk)
        EventException.objects.filter(event=event).delete()
        for x in (item.get("exceptions") or [])[:200]:
            original = _dt(x.get("original_start")) if isinstance(x, dict) else None
            if original is None:
                continue
            EventException.objects.get_or_create(
                organization=org,
                event=event,
                original_start=original,
                defaults={
                    "is_cancelled": bool(x.get("is_cancelled")),
                    "starts_at": _dt(x.get("starts_at")),
                    "ends_at": _dt(x.get("ends_at")),
                    "note": str(x.get("note") or "")[:300],
                },
            )
    # Nur Kopien aus dem Verbund: eine ausgegliederte Untereinheit behält ihre alten Termine
    Event.objects.filter(**own).exclude(remote_uid="").exclude(pk__in=keep).delete()


def persons(data):
    return 0


register(
    Packet(
        "events",
        "Termine (nicht interne, nach den Schaltern „nach oben/unten freigeben“)",
        BOTH,
        default="on",
        build=build,
        apply=apply,
        under_club=True,
    )
)
