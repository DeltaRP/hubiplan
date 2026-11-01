"""Auswertung eines Wettbewerbs: Ranglisten aller Wertungen und Kennzahlen."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from members.models import DepartmentMembership, Membership

from . import ranking
from .models import Competition, Scoring, ShootOff, Starter


def fmt(value: Decimal | None, decimals: int) -> str:
    if value is None:
        return ""
    q = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    text = f"{value.quantize(q, rounding=ROUND_HALF_UP):f}"
    return text.replace(".", ",")


def default_unit(org, membership: Membership, on):
    """Untereinheit, der das Mitglied am Tag angehört (bei mehreren oder keiner: None)."""
    ids = set(
        DepartmentMembership.objects.filter(
            organization=org, membership=membership, valid_from__lte=on
        )
        .exclude(valid_until__lt=on)
        .values_list("department_id", flat=True)
    )
    return ids.pop() if len(ids) == 1 else None


def units_on(org, on) -> dict[int, int]:
    """Mitgliedschaft → Untereinheit am Tag (nur bei genau einer)."""
    seen: dict[int, set] = {}
    for mid, dep in (
        DepartmentMembership.objects.filter(organization=org, valid_from__lte=on)
        .exclude(valid_until__lt=on)
        .values_list("membership_id", "department_id")
    ):
        seen.setdefault(mid, set()).add(dep)
    return {mid: deps.pop() for mid, deps in seen.items() if len(deps) == 1}


def _shootoffs(scoring: Scoring) -> list[tuple[int, dict]]:
    out = []
    for so in ShootOff.objects.filter(scoring=scoring).prefetch_related("entries"):
        out.append((so.number, {e.key: e.value for e in so.entries.all()}))
    return out


def _individual(scoring: Scoring, starters: list[Starter]) -> dict:
    values = {s.starter_id: s.value for s in scoring.scores.all()}
    entries = [ranking.Entry(f"s{s.pk}", values.get(s.pk), s.out_of_competition) for s in starters]
    res = ranking.rank(
        entries,
        higher_better=scoring.higher_better,
        prize_places=scoring.prize_places,
        shootoffs=_shootoffs(scoring),
    )
    by_key = {f"s{s.pk}": s for s in starters}
    rows = []
    for p in res.placed:
        s = by_key[p.key]
        rows.append(_starter_row(s, p, scoring))
    for key in res.unranked:
        s = by_key[key]
        if values.get(s.pk) is not None:  # außer Konkurrenz mit Wert
            rows.append(
                {
                    **_starter_row(s, None, scoring),
                    "value": values[s.pk],
                    "value_text": fmt(values[s.pk], scoring.decimals),
                }
            )
    rows.sort(key=lambda r: (r["place"] is None, r["place"] or 0, r["name"]))
    return {
        "rows": rows,
        "open": [_open(t, by_key, None) for t in res.open],
        "without_value": [
            {"key": f"s{s.pk}", "name": s.name}
            for s in starters
            if values.get(s.pk) is None and not s.out_of_competition
        ],
        "values": values,
    }


def _starter_row(s: Starter, p: ranking.Placed | None, scoring: Scoring) -> dict:
    return {
        "key": f"s{s.pk}",
        "starter": s.pk,
        "place": p.place if p else None,
        "name": s.name,
        "club": s.club,
        "unit": s.unit_id,
        "unit_name": s.unit.name if s.unit_id else "",
        "guest": s.is_guest,
        "out_of_competition": s.out_of_competition,
        "value": p.value if p else None,
        "value_text": fmt(p.value, scoring.decimals) if p else "",
        "shootoff": {
            str(n): fmt(v, scoring.decimals) for n, v in (p.shootoff_values if p else {}).items()
        },
        "tie": p.tie if p else False,
        "prize": bool(p and p.place <= scoring.prize_places),
    }


def _open(t: ranking.OpenTie, by_key: dict, units: dict | None) -> dict:
    names = []
    for k in t.keys:
        if units is not None:
            names.append(units[k]["name"])
        else:
            names.append(by_key[k].name)
    return {"keys": t.keys, "names": sorted(names), "place": t.place, "shootoff": t.shootoff}


def _team(scoring: Scoring, starters: list[Starter], source_values: dict, unit_names) -> dict:
    by_unit: dict[int, list[Starter]] = {}
    for s in starters:
        if s.unit_id:
            by_unit.setdefault(s.unit_id, []).append(s)
    src = scoring.source
    higher = src.higher_better if src else True
    decimals = (src.decimals if src else 0) + (2 if scoring.team_mode == "durchschnitt" else 0)
    units: dict[str, dict] = {}
    entries = []
    unranked_rows = []
    for unit_id, members in by_unit.items():
        tv = ranking.team_value(
            [
                ranking.Entry(f"s{s.pk}", source_values.get(s.pk), s.out_of_competition)
                for s in members
            ],
            mode=scoring.team_mode,
            size=scoring.team_size,
            higher_better=higher,
        )
        key = f"u{unit_id}"
        valued = [
            s for s in members if source_values.get(s.pk) is not None and not s.out_of_competition
        ]
        best = max(valued, key=lambda s: source_values[s.pk] * (1 if higher else -1), default=None)
        info = {
            "key": key,
            "unit": unit_id,
            "name": unit_names.get(unit_id, ""),
            "count": tv.count,
            "counted": [int(k[1:]) for k in tv.counted],
            "best": best.name if best else "",
            "best_starter": best.pk if best else None,
            "reason": tv.reason,
        }
        units[key] = info
        if tv.value is None:
            unranked_rows.append({**info, "place": None, "value": None, "value_text": ""})
        else:
            entries.append(ranking.Entry(key, tv.value))
    res = ranking.rank(
        entries,
        higher_better=higher,
        prize_places=scoring.prize_places,
        shootoffs=_shootoffs(scoring),
    )
    rows = []
    for p in res.placed:
        rows.append(
            {
                **units[p.key],
                "place": p.place,
                "value": p.value,
                "value_text": fmt(p.value, decimals),
                "shootoff": {
                    str(n): fmt(v, src.decimals if src else 0) for n, v in p.shootoff_values.items()
                },
                "tie": p.tie,
                "prize": p.place <= scoring.prize_places,
            }
        )
    rows.sort(key=lambda r: (r["place"], r["name"]))
    unranked_rows.sort(key=lambda r: r["name"])
    return {
        "rows": rows + unranked_rows,
        "open": [_open(t, {}, units) for t in res.open],
        "without_value": [],
    }


def standings(competition: Competition) -> dict:
    org = competition.organization
    starters = list(
        Starter.objects.filter(competition=competition)
        .select_related("unit")
        .order_by("name", "pk")
    )
    scorings = list(
        Scoring.objects.filter(competition=competition)
        .select_related("source")
        .prefetch_related("scores")
    )
    from organizations.models import Department

    unit_names = dict(Department.objects.filter(organization=org).values_list("pk", "name"))
    individual: dict[int, dict] = {}
    out = []
    for sc in scorings:
        if sc.kind == Scoring.Kind.INDIVIDUAL:
            individual[sc.pk] = _individual(sc, starters)
    for sc in scorings:
        if sc.kind == Scoring.Kind.INDIVIDUAL:
            data = dict(individual[sc.pk])
            data.pop("values")
        else:
            src_values = individual.get(sc.source_id, {}).get("values", {})
            data = _team(sc, starters, src_values, unit_names)
        out.append({"scoring": sc.pk, "name": sc.name, "kind": sc.kind, **data})
    return {
        "scorings": out,
        "open_shootoffs": sum(len(s["open"]) for s in out),
        "stats": statistics(competition, starters, scorings, individual, unit_names),
    }


def statistics(competition, starters, scorings, individual, unit_names) -> dict:
    """Kennzahlen der ersten Einzelwertung: Anzahl, Durchschnitt, Höchst- und Tiefstwert,
    je Untereinheit Schützen, Beteiligung und Durchschnitt."""
    first = next((s for s in scorings if s.kind == Scoring.Kind.INDIVIDUAL), None)
    if first is None:
        return {}
    values = individual[first.pk]["values"]
    shooters = [s for s in starters if values.get(s.pk) is not None]
    vals = [values[s.pk] for s in shooters]
    guests = sum(1 for s in shooters if s.is_guest)

    def avg(items):
        if not items:
            return None
        return (sum(items, Decimal(0)) / len(items)).quantize(Decimal("0.01"))

    on = competition.date
    org = competition.organization
    unit_members: dict[int, int] = {}
    for dep_id in (
        DepartmentMembership.objects.filter(
            organization=org,
            valid_from__lte=on,
            membership__purged_at__isnull=True,
        )
        .exclude(valid_until__lt=on)
        .values_list("department_id", flat=True)
    ):
        unit_members[dep_id] = unit_members.get(dep_id, 0) + 1
    per_unit = []
    for unit_id in sorted(
        {s.unit_id for s in shooters if s.unit_id}, key=lambda u: unit_names.get(u, "")
    ):
        uv = [values[s.pk] for s in shooters if s.unit_id == unit_id]
        members = unit_members.get(unit_id, 0)
        own = sum(1 for s in shooters if s.unit_id == unit_id and not s.is_guest)
        per_unit.append(
            {
                "unit": unit_id,
                "name": unit_names.get(unit_id, ""),
                "count": len(uv),
                "members": members,
                "participation": round(own * 100 / members) if members else None,
                "average": fmt(avg(uv), 2),
                "best": fmt(max(uv) if first.higher_better else min(uv), first.decimals),
            }
        )
    return {
        "scoring": first.pk,
        "count": len(shooters),
        "members": len(shooters) - guests,
        "guests": guests,
        "registered": len(starters),
        "average": fmt(avg(vals), 2),
        "max": fmt(max(vals) if vals else None, first.decimals),
        "min": fmt(min(vals) if vals else None, first.decimals),
        "full": sum(1 for v in vals if first.max_value is not None and v == first.max_value),
        "per_unit": per_unit,
    }
