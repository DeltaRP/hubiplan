"""Paket „Wettbewerbsergebnisse“ (Wettbewerbe Schritt 7) nach unten.

Die obere Einheit (Dachverband bzw. Verein mit ferner Untereinheit) richtet Wettbewerbe aus;
jede gekoppelte Einheit darunter bekommt die endgültigen Ergebnisse der letzten zwei Jahre:

- Stufe „units“: nur die Wertungen der Einheiten und Mannschaften (Namen von Einheiten,
  keine Personen), die eigene Zeile markiert;
- Stufe „own“: dazu die eigenen Starter mit Platz und Wert in der Einzelwertung.

„Eigen“ heißt: Untereinheit des Starters ist der Platzhalter der fernen Einheit, oder sein
Verein (Text) heißt wie sie. Fremde Personen gehen nie hinaus. Standard: aus.
"""

from __future__ import annotations

import datetime

from django.utils import timezone

from .models import RemoteState
from .packets import DOWN, Packet, register

LEVEL_UNITS = "units"
LEVEL_OWN = "own"
YEARS = 2
LIMIT = 50


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _is_own_starter(row: dict, coupling, names: set[str]) -> bool:
    if row.get("unit") and row.get("unit") == coupling.remote_unit_id:
        return True
    return bool(row.get("club")) and _norm(row["club"]) in names


def build(coupling, level):
    from competitions import services
    from competitions.models import Competition, Scoring
    from core.tenancy import tenant_context

    org = coupling.local_unit
    remote = coupling.remote_unit
    names = {_norm(n) for n in (remote.name, remote.short_name) if n}
    since = timezone.localdate() - datetime.timedelta(days=365 * YEARS)
    team_kinds = (Scoring.Kind.UNIT, Scoring.Kind.TEAM)
    out = []
    with tenant_context(org.pk):
        comps = Competition.objects.filter(
            organization=org, own=True, status=Competition.Status.FINAL, date__gte=since
        ).order_by("-date", "-pk")[:LIMIT]
        for comp in comps:
            if comp.form == Competition.Form.BIRD:
                continue
            data = services.standings(comp)
            scorings = []
            for s in data.get("scorings", []):
                team = s["kind"] in team_kinds
                if not team and level != LEVEL_OWN:
                    continue
                placed = [r for r in s["rows"] if r.get("place") is not None]
                rows = []
                for r in s["rows"]:
                    if team:
                        own = r.get("unit") == remote.pk or _norm(r.get("name", "")) in names
                    else:
                        own = _is_own_starter(r, coupling, names)
                        if not own:
                            continue
                    if r.get("place") is None and not r.get("value_text"):
                        continue
                    rows.append(
                        {
                            "place": r.get("place"),
                            "name": r.get("name", ""),
                            "value": r.get("value_text", ""),
                            "own": own,
                        }
                    )
                if rows:
                    scorings.append(
                        {"name": s["name"], "kind": s["kind"], "field": len(placed), "rows": rows}
                    )
            if scorings:
                out.append(
                    {
                        "uid": str(comp.pk),
                        "title": comp.title,
                        "date": comp.date.isoformat(),
                        "location": comp.location,
                        "scorings": scorings,
                    }
                )
    return {"competitions": out}


def _text(value, limit) -> str:
    return str(value or "")[:limit]


def _int(value):
    return value if isinstance(value, int) and 0 < value < 100000 else None


def _clean(data: dict) -> dict:
    comps = []
    for c in (data.get("competitions") or [])[:LIMIT]:
        if not isinstance(c, dict):
            continue
        scorings = []
        for s in (c.get("scorings") or [])[:20]:
            if not isinstance(s, dict):
                continue
            rows = [
                {
                    "place": _int(r.get("place")),
                    "name": _text(r.get("name"), 200),
                    "value": _text(r.get("value"), 40),
                    "own": bool(r.get("own")),
                }
                for r in (s.get("rows") or [])[:500]
                if isinstance(r, dict)
            ]
            scorings.append(
                {
                    "name": _text(s.get("name"), 100),
                    "kind": _text(s.get("kind"), 20),
                    "field": _int(s.get("field")),
                    "rows": rows,
                }
            )
        comps.append(
            {
                "uid": _text(c.get("uid"), 40),
                "title": _text(c.get("title"), 200),
                "date": _text(c.get("date"), 10),
                "location": _text(c.get("location"), 200),
                "scorings": scorings,
            }
        )
    return {"level": data.get("level"), "competitions": comps}


def apply(coupling, data):
    if not data.get("level"):
        RemoteState.objects.filter(coupling=coupling, key="results").delete()
        return
    state, _ = RemoteState.objects.get_or_create(coupling=coupling, key="results")
    state.data = _clean(data)
    state.save()


def persons(data) -> int:
    return sum(
        1
        for c in data.get("competitions") or []
        for s in c.get("scorings") or []
        if s.get("kind") == "einzel"
        for r in s.get("rows") or []
    )


register(
    Packet(
        "results",
        "Wettbewerbsergebnisse (endgültige Wettbewerbe der letzten zwei Jahre)",
        (DOWN,),
        levels=(
            (LEVEL_UNITS, "nur Wertungen der Einheiten und Mannschaften"),
            (LEVEL_OWN, "dazu die eigenen Starter mit Platz"),
        ),
        personal="Stufe „eigene Starter“: Namen, Plätze und Werte der Starter der Einheit",
        build=build,
        apply=apply,
        persons=persons,
        under_club=True,
    )
)
