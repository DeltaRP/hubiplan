"""Königsliste aus Excel oder CSV übernehmen.

Erwartete Spalten (Reihenfolge egal, Groß-/Kleinschreibung egal):
Jahr, Würde, Name, optional Endjahr, Begleitung, Bemerkung, Ordnungszahl, Aus.

„Aus“ nennt die Einheit, aus der der Würdenträger kam (z. B. Zug oder Verein). Passt der
Text zu einer Einheit darunter, wird sie zugeordnet, sonst bleibt er als freier Text.

„Endjahr“ für Würden über mehrere Jahre (z. B. 2019 bis 2022); leer = nur ein Jahr.

„Ordnungszahl“ nimmt die Zahl aus einer alten Liste unverändert mit, römisch
(„IV“, „IV.“) oder als Ziffer („4“). Leer heißt: HUBIplan zählt selbst.

„Begleitung“ enthält Einträge der Form „Funktion: Name“, getrennt durch
Semikolon oder Zeilenumbruch, z. B. „Königin: Erika Muster; Minister: Max Beispiel“.

Der Import läuft in zwei Schritten: Die Vorschau liest die Datei und schlägt zu
jedem Namen passende Mitglieder vor. Der Vorstand prüft die Zuordnung und
übernimmt erst dann. Echte Listen gehören nie ins Repository.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from exchange.reading import ReadError, read_table
from members.models import Membership

from .models import Dignity, Reign
from .numbering import roman

MAX_ROWS = 3000
COLUMNS = {
    "year": ("jahr", "startjahr", "von", "schützenfest", "schuetzenfest", "festjahr"),
    "end_year": ("endjahr", "bis", "bis jahr"),
    "dignity": ("würde", "wuerde", "titel", "majestät", "majestaet"),
    "name": ("name", "regent", "majestät name", "könig", "koenig", "person"),
    "companions": ("begleitung", "begleitpersonen", "gefolge", "hofstaat"),
    "note": ("bemerkung", "notiz", "hinweis"),
    "ordinal": ("ordnungszahl", "zahl"),
    "origin": ("aus", "herkunft", "zug", "verein", "einheit"),
}
DEFAULT_COMPANION = "Begleitung"


def _plain(text: str) -> str:
    """Kleinbuchstaben ohne Satzzeichen; Umlaute und ß wie ae/oe/ue/ss."""
    text = str(text or "").lower().strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    # Akzente entfernen, andere Schriften (z. B. 李明) aber behalten (Audit 29.10. H-F01)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[\W_]", " ", text)).strip()


def name_keys(text: str) -> set[str]:
    """Schreibweisen eines Namens: „Vorname Name“ und „Name, Vorname“."""
    raw = str(text or "").strip()
    keys = {_plain(raw)}
    if "," in raw:
        last, first = raw.split(",", 1)
        keys.add(_plain(f"{first} {last}"))
    return {k for k in keys if k}


def map_columns(headers: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, header in enumerate(headers):
        h = str(header).strip().lower()
        for target, names in COLUMNS.items():
            if target not in result and h in names:
                result[target] = index
    return result


class Matcher:
    """Mitglieder der Einheit (auch ehemalige) nach Namen."""

    def __init__(self, org):
        self.people: dict[int, dict] = {}
        rows = (
            Membership.objects.filter(organization=org, purged_at__isnull=True)
            .select_related("person")
            .order_by("person_id")
        )
        for m in rows:
            p = m.person
            if p.pk in self.people:
                continue
            self.people[p.pk] = {
                "id": p.pk,
                "name": f"{p.first_name} {p.last_name}".strip(),
                "birth_year": p.birth_date.year if p.birth_date else None,
                "key": _plain(f"{p.first_name} {p.last_name}"),
            }
        self.by_key: dict[str, list[int]] = {}
        for pid, info in self.people.items():
            self.by_key.setdefault(info["key"], []).append(pid)

    def candidates(self, name: str) -> tuple[int | None, list[dict]]:
        """Vorschlag (bei genau einem Treffer) und Liste möglicher Mitglieder."""
        keys = name_keys(name)
        if not keys:  # nur Satzzeichen o. Ä.: nichts zuzuordnen
            return None, []
        exact = sorted({pid for k in keys for pid in self.by_key.get(k, [])})
        if exact:
            found = [self._public(pid) for pid in exact]
            return (exact[0] if len(exact) == 1 else None), found
        close = []
        for pid, info in self.people.items():
            ratio = max(difflib.SequenceMatcher(None, k, info["key"]).ratio() for k in keys)
            if ratio >= 0.85:
                close.append((ratio, pid))
        close.sort(reverse=True)
        return None, [self._public(pid) for _, pid in close[:5]]

    def _public(self, pid: int) -> dict:
        info = self.people[pid]
        return {"id": pid, "name": info["name"], "birth_year": info["birth_year"]}


def parse_companions(text) -> list[dict]:
    result = []
    for part in re.split(r"[;\n]+", str(text or "")):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            label, name = (x.strip() for x in part.split(":", 1))
        else:
            label, name = DEFAULT_COMPANION, part
        if name:
            result.append({"label": label or DEFAULT_COMPANION, "name": name})
    return result


# Feldlängen wie in den Modellen; längere Angaben werden gemeldet, nie still gekürzt
LIMITS = {"dignity": (100, "Würde"), "name": (200, "Name"), "note": (200, "Bemerkung")}
COMPANION_LIMITS = {"label": (60, "Begleitung (Bezeichnung)"), "name": (200, "Begleitung")}


def _too_long(value: str, limit: int, label: str) -> str:
    if len(value) <= limit:
        return ""
    return f"{label} ist zu lang ({len(value)} Zeichen, höchstens {limit})."


def _year(value) -> int | None:
    if value in (None, ""):
        return None
    if hasattr(value, "year"):
        return value.year
    match = re.fullmatch(r"\s*(\d{4})(?:\s*/\s*\d{2,4})?\s*", str(value))
    return int(match.group(1)) if match else None


ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def parse_ordinal(value) -> tuple[int | None, str]:
    """(Zahl, Fehlermeldung) aus „IV“, „iv.“, „4“ oder leer."""
    text = str(value if value is not None else "").strip().rstrip(".").strip()
    if not text:
        return None, ""
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    if text.isdigit():
        number = int(text)
    elif re.fullmatch(r"[IVXLCDM]+", text.upper()):
        letters = text.upper()
        number = 0
        for i, letter in enumerate(letters):
            v = ROMAN_VALUES[letter]
            nxt = ROMAN_VALUES[letters[i + 1]] if i + 1 < len(letters) else 0
            number += -v if v < nxt else v
        if number < 1 or roman(number) != letters:  # z. B. „IIII“ oder „VX“
            return None, f"Ordnungszahl „{text}“ ist keine gültige römische Zahl."
    else:
        return None, f"Ordnungszahl „{text}“ ist weder römisch noch eine Ziffer."
    if not 1 <= number <= 3999:
        return None, "Ordnungszahl muss zwischen 1 und 3999 liegen."
    return number, ""


def preview(org, path, file_name: str) -> dict:
    try:
        headers, rows = read_table(path, file_name)
    except ReadError as exc:
        return {"error": str(exc), "rows": []}
    columns = map_columns(headers)
    missing = [
        label
        for key, label in (("year", "Jahr"), ("dignity", "Würde"), ("name", "Name"))
        if key not in columns
    ]
    if missing:
        return {
            "error": f"Es fehlen die Spalten: {', '.join(missing)}. "
            f"Gefunden: {', '.join(headers)}.",
            "rows": [],
        }
    if len(rows) > MAX_ROWS:
        return {"error": f"Höchstens {MAX_ROWS} Zeilen je Datei.", "rows": []}
    matcher = Matcher(org)
    from .views import origin_choices

    origins = {_plain(o.name): o for o in origin_choices(org)}
    dignities = {
        d.name.strip().lower(): d for d in Dignity.objects.filter(organization=org, unit=None)
    }
    existing = {
        (r.dignity_id, r.year, _plain(r.display_name))
        for r in Reign.objects.filter(organization=org).select_related("person")
    }

    def cell(row, key):
        index = columns.get(key)
        value = row[index] if index is not None else None
        return "" if value is None else value

    result = []
    for line, row in enumerate(rows, start=2):
        errors = []
        year = _year(cell(row, "year"))
        if year is None or not (1000 <= year <= 2999):
            errors.append("Jahr fehlt oder ist ungültig.")
        end_raw = cell(row, "end_year")
        end_year = _year(end_raw)
        if str(end_raw).strip() and end_year is None:
            errors.append("Endjahr ist ungültig.")
        elif end_year is not None and not (1000 <= end_year <= 2999):
            errors.append("Endjahr ist ungültig.")
            end_year = None
        elif end_year is not None and year is not None and end_year < year:
            errors.append("Das Endjahr liegt vor dem Startjahr.")
        if end_year == year:
            end_year = None
        dignity_name = str(cell(row, "dignity")).strip()
        if not dignity_name:
            errors.append("Würde fehlt.")
        name = str(cell(row, "name")).strip()
        if not name:
            errors.append("Name fehlt.")
        note = str(cell(row, "note")).strip()
        origin_raw = str(cell(row, "origin")).strip()
        origin = origins.get(_plain(origin_raw)) if origin_raw else None
        if not origin and (message := _too_long(origin_raw, 200, "Aus")):
            errors.append(message)
        ordinal, ordinal_error = parse_ordinal(cell(row, "ordinal"))
        if ordinal_error:
            errors.append(ordinal_error)
        for key, value in (("dignity", dignity_name), ("name", name), ("note", note)):
            if message := _too_long(value, *LIMITS[key]):
                errors.append(message)
        dignity = dignities.get(dignity_name.lower())
        person_id, candidates = matcher.candidates(name) if name else (None, [])
        companions = []
        for c in parse_companions(cell(row, "companions")):
            for key in ("label", "name"):
                if message := _too_long(c[key], *COMPANION_LIMITS[key]):
                    errors.append(message)
            cid, ccands = matcher.candidates(c["name"])
            companions.append({**c, "person_id": cid, "candidates": ccands})
        duplicate = bool(dignity and year and (dignity.pk, year, _plain(name)) in existing) or any(
            r["year"] == year
            and r["dignity"].lower() == dignity_name.lower()
            and _plain(r["name"]) == _plain(name)
            for r in result
        )
        result.append(
            {
                "line": line,
                "year": year,
                "end_year": end_year,
                "dignity": dignity_name,
                "dignity_id": dignity.pk if dignity else None,
                "name": name,
                "person_id": person_id,
                "candidates": candidates,
                "companions": companions,
                "note": note,
                "origin": origin.pk if origin else None,
                "origin_name": "" if origin else origin_raw,
                "origin_text": origin.name if origin else origin_raw,
                "ordinal": ordinal,
                "ordinal_text": roman(ordinal) if ordinal else "",
                "duplicate": duplicate,
                "errors": errors,
            }
        )
    new_dignities = sorted(
        {r["dignity"] for r in result if r["dignity"] and r["dignity_id"] is None},
        key=str.lower,
    )
    return {"error": "", "rows": result, "new_dignities": new_dignities}
