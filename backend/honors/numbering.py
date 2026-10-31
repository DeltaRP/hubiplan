"""Ordnungszahlen der Würdenträger: „Michael I.“, „Michael II.“ …

Bei einer Würde mit ``numbered`` zählt die Zahl je gleichem Vornamen hoch, in
der Reihenfolge der ersten Regentschaft. Wer die Würde mehrmals trug, behält
seine Zahl. Eine von Hand gesetzte Zahl (``Reign.ordinal``) gilt für die
Person, und die automatische Zählung dieses Vornamens läuft danach von ihr weiter.
"""

from __future__ import annotations

import datetime

ROMAN = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def roman(number: int) -> str:
    result = ""
    for value, letters in ROMAN:
        while number >= value:
            result += letters
            number -= value
    return result


# Zusätze hinter dem Nachnamen, die zum Nachnamen gehören („Josef Rongen sen.“)
SUFFIXES = {"sen.", "sen", "jun.", "jun", "jr.", "sr."}


def split_name(person, name: str) -> tuple[str, str]:
    """(Vorname, Nachname); ein Name als Text: letztes Wort ist der Nachname,
    ein Zusatz wie „sen.“ oder „jun.“ gehört mit zum Nachnamen."""
    if person is not None:
        return person.first_name.strip(), person.last_name.strip()
    parts = name.strip().split()
    tail = 1
    while len(parts) > tail + 1 and parts[-tail].lower() in SUFFIXES:
        tail += 1
    if len(parts) < tail + 1:
        return name.strip(), ""
    return " ".join(parts[:-tail]), " ".join(parts[-tail:])


def holder_key(reign) -> str:
    if reign.person_id:
        return f"p{reign.person_id}"
    return "n" + " ".join(reign.name.lower().split())


def ordinals(reigns, per_reign: bool = False) -> dict[int, int]:
    """Ordnungszahl je Regentschaft (pk) für die Regentschaften einer Würde.

    ``per_reign``: jede Regentschaft zählt neu, auch bei derselben Person
    (Otto I., Otto II. für zweimal Otto Muster). Sonst behält eine Person ihre Zahl.
    """
    ordered = sorted(
        reigns, key=lambda r: (r.sort_year, r.valid_from or datetime.date.min, r.pk or 0)
    )
    if per_reign:
        return _per_reign(ordered)
    manual: dict[str, int] = {}
    for reign in ordered:
        if reign.ordinal:
            manual.setdefault(holder_key(reign), reign.ordinal)
    counter: dict[str, int] = {}
    number_of: dict[str, int] = {}
    result: dict[int, int] = {}
    for reign in ordered:
        key = holder_key(reign)
        if key not in number_of:
            first = split_name(reign.person, reign.name)[0].lower()
            if key in manual:
                number_of[key] = manual[key]
                counter[first] = max(counter.get(first, 0), manual[key])
            else:
                counter[first] = counter.get(first, 0) + 1
                number_of[key] = counter[first]
        result[reign.pk] = reign.ordinal or number_of[key]
    return result


def _per_reign(ordered) -> dict[int, int]:
    counter: dict[str, int] = {}
    result: dict[int, int] = {}
    for reign in ordered:
        first = split_name(reign.person, reign.name)[0].lower()
        if reign.ordinal:
            counter[first] = max(counter.get(first, 0), reign.ordinal)
            result[reign.pk] = reign.ordinal
        else:
            counter[first] = counter.get(first, 0) + 1
            result[reign.pk] = counter[first]
    return result


def numbered_name(first: str, last: str, number: int | None) -> str:
    """„Vorname Zahl. Nachname“, ohne Zahl nur „Vorname Nachname“."""
    if number:
        first = f"{first} {roman(number)}.".strip()
    return f"{first} {last}".strip()
