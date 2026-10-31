"""Jubiläen von Einheiten aus dem Gründungsjahr (z. B. 100 Jahre Jägerzug).

Gezählt wird jahresgenau: Gegründet 1927 ergibt 100 Jahre im ganzen Jahr 2027.
"""

from __future__ import annotations

import datetime

from .models import Department, Organization
from .tree import UnitTree


def unit_jubilees(org: Organization, start: datetime.date, end: datetime.date) -> list[dict]:
    """Jubiläen der Einheit selbst und der Einheiten darunter im Zeitraum."""
    levels = sorted(set(org.unit_jubilee_years or []))
    candidates: list[tuple[Organization, str, str]] = [(org, "self", org.name)]
    if org.type == Organization.Type.CLUB:
        tree = UnitTree.of(org.pk)
        units = {u.pk: u for u in Department.objects.filter(organization=org, is_active=True)}
        candidates += [(units[i], "unit", tree.path(i)) for i in tree.ordered() if i in units]
    elif org.type == Organization.Type.FEDERATION:
        clubs = Organization.objects.filter(
            parent=org, type=Organization.Type.CLUB, is_active=True
        ).order_by("name")
        candidates += [(c, "club", c.name) for c in clubs]
    rows = []
    for unit, kind, path in candidates:
        if not unit.founding_year:
            continue
        for years in levels:
            year = unit.founding_year + years
            if start.year <= year <= end.year:
                rows.append(
                    {
                        "id": unit.pk,
                        "kind": kind,
                        "name": unit.name,
                        "short_name": unit.display_name,
                        "path": path,
                        "label": unit.kind_label,
                        # Für Überschriften wie „Jubiläen der Züge“ (eigene Bezeichnung)
                        "label_plural": unit.label_plural or unit.kind_label,
                        "label_gender": unit.label_gender or "f",
                        "label_genitive": unit.label_genitive,
                        "founding_year": unit.founding_year,
                        "years": years,
                        "year": year,
                    }
                )
    rows.sort(key=lambda r: (r["year"], -r["years"], r["path"]))
    return rows
