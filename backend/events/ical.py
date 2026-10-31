"""Kalenderdateien im iCalendar-Format (RFC 5545) für Abos und Downloads.

Serien werden als einzelne Termine ausgegeben. Das ist robuster als Regeln mit
Ausnahmen und wird von allen Kalender-Apps gleich verstanden.
"""

from __future__ import annotations

import datetime

from django.utils import timezone

from .recurrence import Occurrence


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Zeilen nach höchstens 75 Bytes umbrechen (Folgezeilen beginnen mit Leerzeichen)."""
    out, current = [], ""
    for char in line:
        limit = 75 if not out else 74
        if len((current + char).encode()) > limit:
            out.append(current)
            current = char
        else:
            current += char
    out.append(current)
    return [out[0], *(" " + part for part in out[1:])]


def _utc(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _date(value: datetime.datetime) -> str:
    return timezone.localtime(value).strftime("%Y%m%d")


def calendar(
    name: str, items: list[Occurrence], host: str, url_for=None, description: str = ""
) -> bytes:
    """``url_for(occ)`` liefert optional einen Link zum Termin.

    ``description``: Beschreibung des Kalenders (z. B. Link zum Impressum).
    """
    stamp = _utc(timezone.now())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//hubiplan//Terminkalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-WR-TIMEZONE:Europe/Berlin",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    if description:
        lines.append(f"X-WR-CALDESC:{_escape(description)}")
    for occ in items:
        event = occ.event
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{occ.key}@{host}")
        lines.append(f"DTSTAMP:{stamp}")
        if event.all_day:
            last = timezone.localtime(occ.ends_at).date() + datetime.timedelta(days=1)
            lines.append(f"DTSTART;VALUE=DATE:{_date(occ.starts_at)}")
            lines.append(f"DTEND;VALUE=DATE:{last:%Y%m%d}")
        else:
            lines.append(f"DTSTART:{_utc(occ.starts_at)}")
            lines.append(f"DTEND:{_utc(occ.ends_at)}")
        title = event.title
        if occ.is_cancelled:
            title = f"Abgesagt: {title}"
        lines.append(f"SUMMARY:{_escape(title)}")
        place = ", ".join(p for p in (event.location, event.address) if p)
        if place:
            lines.append(f"LOCATION:{_escape(place)}")
        text = event.description
        if occ.note:
            text = f"{occ.note}\n\n{text}" if text else occ.note
        if text:
            lines.append(f"DESCRIPTION:{_escape(text)}")
        if event.category_id:
            lines.append(f"CATEGORIES:{_escape(event.category.name)}")
        lines.append(f"STATUS:{'CANCELLED' if occ.is_cancelled else 'CONFIRMED'}")
        if url_for is not None:
            link = url_for(occ)
            if link:
                lines.append(f"URL:{link}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return ("\r\n".join(folded) + "\r\n").encode()
