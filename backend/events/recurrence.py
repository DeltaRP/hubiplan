"""Einzeltermine eines Zeitraums ausrechnen, auch für Serien.

Serien werden in deutscher Ortszeit gerechnet: Ein Termin „jeden Dienstag
19:30“ bleibt auch nach der Umstellung auf Sommer- oder Winterzeit um 19:30.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from dateutil import rrule
from django.utils import timezone

from .models import Event, EventException

FREQ = {
    Event.Repeat.WEEKLY: rrule.WEEKLY,
    Event.Repeat.MONTHLY: rrule.MONTHLY,
    Event.Repeat.YEARLY: rrule.YEARLY,
}

# Schutz gegen versehentlich endlose Auswertungen
MAX_PER_SERIES = 600


@dataclass
class Occurrence:
    event: Event
    # Beginn laut Regel (erkennt den Einzeltermin, auch wenn er verschoben ist)
    original_start: datetime.datetime
    starts_at: datetime.datetime
    ends_at: datetime.datetime
    is_cancelled: bool
    note: str = ""
    is_moved: bool = False

    @property
    def key(self) -> str:
        return f"{self.event.pk}-{self.original_start.astimezone(datetime.UTC):%Y%m%dT%H%M%SZ}"


def _local(value: datetime.datetime) -> datetime.datetime:
    return timezone.localtime(value).replace(tzinfo=None)


def _aware(value: datetime.datetime) -> datetime.datetime:
    return timezone.make_aware(value, timezone.get_current_timezone())


def _occurrence_end(
    event: Event, original: datetime.datetime, duration: datetime.timedelta
) -> datetime.datetime:
    """Ende eines Serientermins: gleiche Uhrzeit-Dauer wie der erste Termin.

    Der erste Termin behält sein gespeichertes Ende (auch in der doppelten Stunde bei
    der Umstellung auf Winterzeit, die als Uhrzeit nicht eindeutig ist). Fällt ein
    späteres Ende in eine mehrdeutige oder fehlende Stunde, endet der Termin nie vor
    seinem Beginn, sondern dauert dann so lange wie der erste in echter Zeit.
    """
    if original == event.starts_at:
        return event.ends_at
    finishes = _aware(_local(original) + duration)
    if finishes <= original:
        finishes = original + (event.ends_at - event.starts_at)
    return finishes


def series_starts(
    event: Event,
    until: datetime.datetime | None = None,
    since: datetime.datetime | None = None,
) -> list[datetime.datetime]:
    """Beginnzeiten laut Regel bis ``until`` (oder Serienende), ab ``since``.

    Die Obergrenze ``MAX_PER_SERIES`` zählt erst ab ``since``: Eine lange laufende
    Serie verschwindet so nicht nach einigen Jahren aus dem Kalender."""
    if not event.is_series:
        return [event.starts_at]
    first = _local(event.starts_at)
    end = None
    if event.repeat_until:
        end = datetime.datetime.combine(event.repeat_until, datetime.time.max)
    if until is not None:
        local_until = _local(until)
        end = local_until if end is None else min(end, local_until)
    rule = rrule.rrule(
        FREQ[event.repeat],
        dtstart=first,
        interval=event.repeat_interval or 1,
        until=end,
        # Am 31. ohne 31. im Monat (bzw. 29.2.) entfällt der Termin wie in Kalender-Apps
        count=None if end else MAX_PER_SERIES,
    )
    local_since = _local(since) if since is not None else None
    starts = []
    for value in rule:
        if local_since is not None and value < local_since:
            continue
        starts.append(_aware(value))
        if len(starts) >= MAX_PER_SERIES:
            break
    return starts


def occurrences(events, start: datetime.datetime, end: datetime.datetime) -> list[Occurrence]:
    """Einzeltermine, die sich mit dem Zeitraum [start, end) überschneiden."""
    events = list(events)
    exceptions: dict[int, dict[datetime.datetime, EventException]] = {}
    series_ids = [e.pk for e in events if e.is_series]
    if series_ids:
        for exc in EventException.objects.filter(event_id__in=series_ids):
            exceptions.setdefault(exc.event_id, {})[exc.original_start] = exc
    result: list[Occurrence] = []
    for event in events:
        # Dauer als Uhrzeit-Abstand: Über eine Zeitumstellung hinweg bleibt die Endzeit
        # (z. B. 04:00) gleich, statt sich um eine Stunde zu verschieben
        duration = _local(event.ends_at) - _local(event.starts_at)
        if not event.is_series:
            if event.starts_at < end and _effective_end(event, event.ends_at) >= start:
                result.append(
                    Occurrence(
                        event,
                        event.starts_at,
                        event.starts_at,
                        event.ends_at,
                        event.is_cancelled,
                        event.cancel_note,
                    )
                )
            continue
        own = exceptions.get(event.pk, {})
        # Verschobene Termine können aus einem früheren Regeltermin stammen
        moved_back = max(
            [
                exc.original_start - exc.starts_at
                for exc in own.values()
                if exc.starts_at and exc.original_start > exc.starts_at
            ],
            default=datetime.timedelta(0),
        )
        moved_ahead = max(
            [
                exc.starts_at - exc.original_start
                for exc in own.values()
                if exc.starts_at and exc.starts_at > exc.original_start
            ],
            default=datetime.timedelta(0),
        )
        since = start - duration - moved_ahead - datetime.timedelta(days=2)
        for original in series_starts(event, until=end + moved_back, since=since):
            exc = own.get(original)
            begins, finishes = original, _occurrence_end(event, original, duration)
            cancelled, note, moved = event.is_cancelled, event.cancel_note, False
            if exc is not None:
                if exc.starts_at:
                    begins = exc.starts_at
                    finishes = exc.ends_at or _aware(_local(exc.starts_at) + duration)
                    moved = True
                cancelled = cancelled or exc.is_cancelled
                note = exc.note or note
            if begins < end and _effective_end(event, finishes) >= start:
                result.append(Occurrence(event, original, begins, finishes, cancelled, note, moved))
    result.sort(key=lambda o: (o.starts_at, o.event.title, o.event.pk))
    return result


def _effective_end(event: Event, ends_at: datetime.datetime) -> datetime.datetime:
    """Ganztägig: das Ende ist der Beginn des letzten Tages, gilt also den ganzen Tag."""
    if event.all_day:
        return ends_at + datetime.timedelta(days=1) - datetime.timedelta(microseconds=1)
    return ends_at


def is_rule_start(event: Event, value: datetime.datetime) -> bool:
    """Liegt ``value`` auf der Serienregel?"""
    if not event.is_series:
        return value == event.starts_at
    return value in series_starts(event, until=value, since=value)


def shift_exceptions(event: Event, old_start: datetime.datetime) -> int:
    """Serie geändert: Absagen und Verschiebungen wandern mit.

    Abweichungen hängen am Beginn laut Regel. Ändert sich die Uhrzeit oder der Tag
    der Serie, gelten sie sonst für keinen Termin mehr. Sie werden um denselben
    Abstand (in Ortszeit) verschoben. Was danach nicht auf der Regel liegt (auch nach
    einer Änderung nur des Abstands oder Endes), entfällt, statt bei einer späteren
    Rückänderung wieder aufzutauchen. Gibt die Zahl der entfernten Abweichungen zurück."""
    if not event.is_series:
        return 0
    exceptions = list(event.exceptions.order_by("original_start"))
    if old_start != event.starts_at:
        delta = _local(event.starts_at) - _local(old_start)
        if delta > datetime.timedelta(0):
            exceptions.reverse()  # eindeutiger Beginn: von hinten verschieben
        for exc in exceptions:
            exc.original_start = _aware(_local(exc.original_start) + delta)
            exc.save(update_fields=["original_start"])
    removed = 0
    for exc in exceptions:
        if not is_rule_start(event, exc.original_start):
            exc.delete()
            removed += 1
    return removed
