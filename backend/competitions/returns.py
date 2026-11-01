"""Ergebnisse zurück an die meldenden Untereinheiten (Wettbewerbe Schritt 3, Konzept
Abschnitt 9, gleiche Instanz).

Eine Ausschreibung an Untereinheiten legt beim Ausrichter einen eigenen Wettbewerb an; die
bestätigten Meldungen werden Starter und Mannschaften. Ist er endgültig, sieht jede meldende
Untereinheit in ihrer Meldung:

- Plätze und Werte ihrer eigenen Starter und Mannschaften,
- die Wertung der Untereinheiten und die Mannschaftswertung (nur Namen von Untereinheiten
  und Mannschaften, Mitglieder nur bei eigenen Mannschaften),
- die ganze Einzelrangliste mit fremden Namen nur, wenn der Ausrichter sie freigibt
  (``Competition.share_ranking``).
"""

from __future__ import annotations

from .models import Competition, Scoring

TEAM_KINDS = (Scoring.Kind.UNIT, Scoring.Kind.TEAM)


def competition_of(entry):
    call = entry.call
    if not call.internal or not call.competition_id:
        return None
    return call.competition


def _own(entry) -> tuple[set[int], set[int]]:
    from entries.models import EntryPerson

    starters = set(
        EntryPerson.objects.filter(entry=entry, starter__isnull=False).values_list(
            "starter_id", flat=True
        )
    )
    starters |= set((entry.synced or {}).get("starters", []))
    teams = set(entry.teams.filter(team__isnull=False).values_list("team_id", flat=True))
    teams |= set((entry.synced or {}).get("teams", []))
    return starters, teams


def entry_results(entry) -> dict | None:
    """Ergebnisse für die Meldung einer Untereinheit; ``None`` ohne Wettbewerb."""
    from . import services

    comp = competition_of(entry)
    if comp is None or entry.department_id is None:
        return None
    head = {
        "title": comp.title,
        "date": comp.date.isoformat(),
        "status": comp.status,
        "status_label": comp.get_status_display(),
        "final": comp.status == Competition.Status.FINAL,
        "share_ranking": comp.share_ranking,
        "scorings": [],
        "prizes": [],
    }
    if not head["final"]:
        return head
    own_starters, own_teams = _own(entry)
    unit = entry.department_id
    full = comp.share_ranking
    data = services.standings(comp)
    for s in data.get("scorings", []):
        kind = s["kind"]
        placed = [r for r in s["rows"] if r.get("place") is not None]
        rows = []
        for r in s["rows"]:
            if kind == Scoring.Kind.UNIT:
                own = r.get("unit") == unit
            elif kind == Scoring.Kind.TEAM:
                # Eigener Wettbewerb rechnet Mannschaften je Untereinheit, ein fremder je Team
                own = r.get("team") in own_teams if "team" in r else r.get("unit") == unit
            else:
                own = r.get("starter") in own_starters
            if kind not in TEAM_KINDS and not (own or full):
                continue
            if r.get("place") is None and not r.get("value_text") and not own:
                continue
            row = {
                "place": r.get("place"),
                "name": r.get("name", ""),
                "value_text": r.get("value_text", ""),
                "own": own,
            }
            if kind not in TEAM_KINDS:
                row["unit_name"] = r.get("unit_name", "")
                if r.get("club"):
                    row["club"] = r["club"]
            if kind == Scoring.Kind.TEAM and own and r.get("members"):
                row["members"] = r["members"]
            rows.append(row)
        head["scorings"].append(
            {
                "name": s["name"],
                "kind": kind,
                "field": len(placed) or s.get("field_size"),
                "complete": kind in TEAM_KINDS or full,
                "rows": rows,
            }
        )
    if comp.form == Competition.Form.BIRD:
        for p in comp.prizes.select_related("winner__unit"):
            if not p.fallen:
                continue
            own = p.winner_id in own_starters
            entry_ = {"name": p.name, "own": own}
            if p.winner_id:
                entry_["unit_name"] = p.winner.unit.name if p.winner.unit_id else ""
                if own or full:
                    entry_["winner"] = p.winner.name
            elif full:
                entry_["winner"] = p.winner_name
            head["prizes"].append(entry_)
    return head
