"""Ämter: heutige und frühere Inhaber der Rollen (Mitglieder › Ämter).

Frühere Inhaber sind oft keine Mitglieder mehr und hatten nie ein Konto (Ralf
2026-10-31). Sie stehen als freie Einträge in ``RoleAssignment`` mit ``name``, ohne
Konto und ohne Mitgliedschaft, optional mit einer Mitgliedsakte (ehemaliges Mitglied).

Jahresgenau: Für Ämter genügt das Jahr. Ein freier Eintrag speichert den 1. 1. des
Anfangs- und des Endjahres; er ist immer abgeschlossen (Endjahr höchstens das laufende
Jahr) und zählt deshalb nirgends als heutiger Inhaber (Impressum, Briefbogen, Rechte).

Import (Excel/CSV) wie bei den Würden in zwei Schritten: Vorschau mit Vorschlägen für
Mitgliedsakten, dann Übernahme. Echte Listen gehören nie ins Repository.
"""

from __future__ import annotations

import datetime

from django.db.models import Q

from exchange.reading import ReadError, read_table
from honors.importer import Matcher, _plain, _too_long, _year
from members.models import today
from organizations.terms import department_terms

from .models import Role, RoleAssignment

MAX_ROWS = 3000
NAME_MAX = 200
COLUMNS = {
    "role": ("amt", "rolle", "funktion", "ämter", "aemter"),
    "unit": ("einheit", "untereinheit", "abteilung", "zug"),
    "name": ("name", "inhaber", "amtsinhaber", "person"),
    "from_year": ("von", "ab", "beginn", "anfang", "startjahr", "von jahr", "jahr"),
    "until_year": ("bis", "ende", "endjahr", "bis jahr"),
}


def year_start(year: int) -> datetime.date:
    return datetime.date(year, 1, 1)


def check_years(from_year, until_year) -> str:
    """Fehlermeldung zu einem Zeitraum oder leer."""
    this_year = today().year
    if from_year is None or not (1000 <= from_year <= this_year):
        return "Anfangsjahr fehlt oder ist ungültig."
    if until_year is None:
        return "Endjahr fehlt: frühere Inhaber brauchen ein Endjahr."
    if not (1000 <= until_year <= this_year):
        return f"Endjahr ist ungültig (höchstens {this_year})."
    if until_year < from_year:
        return "Das Endjahr liegt vor dem Anfangsjahr."
    return ""


def roles_of(org):
    """Rollen der Einheit und ihrer Untereinheiten im Datenbereich."""
    return (
        Role.all_objects.filter(organization=org)
        .select_related("department")
        .order_by("department__name", "position", "name")
    )


def holder_name(a: RoleAssignment) -> str:
    if a.membership_id:
        p = a.membership.person
        return f"{p.first_name} {p.last_name}".strip()
    if a.person_id:
        return f"{a.person.first_name} {a.person.last_name}".strip()
    if a.user_id:
        return a.user.get_full_name() or a.user.email
    return a.name


def holder_entry(a: RoleAssignment) -> dict:
    person_id = a.membership.person_id if a.membership_id else a.person_id
    return {
        "id": a.pk,
        "role": a.role_id,
        "name": holder_name(a),
        "person": person_id,
        "from_year": a.valid_from.year,
        "until_year": a.valid_until.year if a.valid_until else None,
        "current": a.valid_until is None or a.valid_until >= today(),
        "former_entry": a.is_former_entry,
    }


def overview(org) -> list[dict]:
    """Alle Rollen mit allen Inhabern, ältere zuerst."""
    roles = list(roles_of(org))
    holders: dict[int, list[dict]] = {r.pk: [] for r in roles}
    rows = (
        RoleAssignment.all_objects.filter(role__in=roles)
        .select_related("person", "user", "membership__person")
        .order_by("valid_from", "pk")
    )
    for a in rows:
        holders[a.role_id].append(holder_entry(a))
    return [
        {
            "id": r.pk,
            "name": r.name,
            "unit": r.department_id,
            "unit_name": r.department.name if r.department_id else None,
            "in_chronicle": r.in_chronicle,
            "is_board": r.is_board,
            "holders": holders[r.pk],
        }
        for r in roles
    ]


# --- Import ---


def map_columns(headers: list[str], org) -> dict[str, int]:
    names = {k: set(v) for k, v in COLUMNS.items()}
    label = department_terms(org).get("sg")
    if label:
        names["unit"].add(str(label).strip().lower())
    result: dict[str, int] = {}
    for index, header in enumerate(headers):
        h = str(header).strip().lower()
        for target, options in names.items():
            if target not in result and h in options:
                result[target] = index
    return result


def _key(role_name: str, unit_name: str) -> tuple[str, str]:
    return (role_name.strip().lower(), unit_name.strip().lower())


def preview(org, path, file_name: str) -> dict:
    try:
        headers, rows = read_table(path, file_name)
    except ReadError as exc:
        return {"error": str(exc), "rows": []}
    columns = map_columns(headers, org)
    missing = [
        label
        for key, label in (("role", "Amt"), ("name", "Name"), ("from_year", "von"))
        if key not in columns
    ]
    if missing:
        return {
            "error": f"Es fehlen die Spalten: {', '.join(missing)}. "
            f"Gefunden: {', '.join(str(h) for h in headers)}.",
            "rows": [],
        }
    if len(rows) > MAX_ROWS:
        return {"error": f"Höchstens {MAX_ROWS} Zeilen je Datei.", "rows": []}
    roles = list(roles_of(org))
    by_key = {_key(r.name, r.department.name if r.department_id else ""): r for r in roles}
    units = {r.department.name.strip().lower(): r.department for r in roles if r.department_id}
    from organizations.models import Department

    for d in Department.objects.filter(organization=org):
        units.setdefault(d.name.strip().lower(), d)
    existing = {
        (a.role_id, a.valid_from.year, _plain(holder_name(a)))
        for a in RoleAssignment.all_objects.filter(role__in=roles).select_related(
            "person", "user", "membership__person"
        )
    }
    matcher = Matcher(org)

    def cell(row, key):
        index = columns.get(key)
        value = row[index] if index is not None and index < len(row) else None
        return "" if value is None else value

    result = []
    seen = set()
    for line, row in enumerate(rows, start=2):
        errors = []
        role_name = str(cell(row, "role")).strip()
        unit_name = str(cell(row, "unit")).strip()
        name = str(cell(row, "name")).strip()
        from_raw, until_raw = cell(row, "from_year"), cell(row, "until_year")
        from_year, until_year = _year(from_raw), _year(until_raw)
        if not role_name:
            errors.append("Amt fehlt.")
        if not name:
            errors.append("Name fehlt.")
        if str(until_raw).strip() and until_year is None:
            errors.append("Endjahr ist ungültig.")
        elif until_year is None and from_year is not None:
            until_year = from_year  # nur ein Jahr angegeben
        if message := check_years(from_year, until_year):
            errors.append(message)
        for value, limit, label in ((role_name, 100, "Amt"), (name, NAME_MAX, "Name")):
            if message := _too_long(value, limit, label):
                errors.append(message)
        unit = units.get(unit_name.lower()) if unit_name else None
        if unit_name and unit is None:
            errors.append(f"Untereinheit „{unit_name}“ gibt es nicht.")
        role = by_key.get(_key(role_name, unit.name if unit else "")) if role_name else None
        person_id, candidates = matcher.candidates(name) if name else (None, [])
        key = (role_name.lower(), unit_name.lower(), from_year, _plain(name))
        duplicate = bool(role and (role.pk, from_year, _plain(name)) in existing) or key in seen
        seen.add(key)
        result.append(
            {
                "line": line,
                "role": role_name,
                "role_id": role.pk if role else None,
                "unit": unit.name if unit else "",
                "unit_id": unit.pk if unit else None,
                "name": name,
                "person_id": person_id,
                "candidates": candidates,
                "from_year": from_year,
                "until_year": until_year,
                "duplicate": duplicate,
                "errors": errors,
            }
        )
    new_roles = sorted(
        {
            f"{r['role']} ({r['unit']})" if r["unit"] else r["role"]
            for r in result
            if r["role"] and r["role_id"] is None and not r["errors"]
        },
        key=str.lower,
    )
    return {"error": "", "rows": result, "new_roles": new_roles}


def create_entry(role: Role, *, name: str, person, from_year: int, until_year: int):
    if person is not None:
        name = f"{person.first_name} {person.last_name}".strip() or name
    return RoleAssignment.all_objects.create(
        organization=role.organization,
        role=role,
        name=name.strip(),
        person=person,
        valid_from=year_start(from_year),
        valid_until=year_start(until_year),
    )


def former_entries(org):
    """Freie Einträge der Einheit (nur diese sind hier änderbar)."""
    return RoleAssignment.all_objects.filter(
        organization=org, user__isnull=True, membership__isnull=True
    ).exclude(Q(name=""))
