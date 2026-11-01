"""Ranglisten ohne Datenbank: Werte und Regeln hinein, Plätze heraus.

- Gleiche Werte bekommen zunächst denselben Platz („1, 2, 2, 4“).
- Berührt ein Gleichstand einen Preisplatz, entscheidet ein Stechen. Die Stechen einer
  Wertung werden der Reihe nach angewandt: ein Stechen gilt für eine Gruppe, wenn alle
  aus der Gruppe darin stehen. Fehlt ein Stechen oder ein Wert darin, bleibt der Platz
  geteilt und die Gruppe steht unter ``open`` (Stechen nötig bzw. läuft).
- Außerhalb der Preisplätze bleibt Gleichstand ohne Stechen (gleicher Platz).
- Wertung der Untereinheiten: Wert aus den Einzelwerten ihrer Starter (Summe der besten
  k, Summe aller, Durchschnitt). Bei „beste k“ wird eine Untereinheit mit weniger als k
  Startern nicht gewertet (Ralf, 2026-11-01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


@dataclass
class Entry:
    key: str
    value: Decimal | None
    out_of_competition: bool = False


@dataclass
class Placed:
    key: str
    value: Decimal
    place: int
    # Werte aus den Stechen, die für diesen Eintrag entschieden haben (Nr. → Wert)
    shootoff_values: dict[int, Decimal] = field(default_factory=dict)
    tie: bool = False


@dataclass
class OpenTie:
    keys: list[str]
    place: int
    # Nr. eines angelegten Stechens, in dem noch Werte fehlen (None: Stechen nötig)
    shootoff: int | None = None


@dataclass
class Result:
    placed: list[Placed]
    open: list[OpenTie]
    unranked: list[str]  # außer Konkurrenz oder ohne Wert


def rank(
    entries: list[Entry],
    *,
    higher_better: bool = True,
    prize_places: int = 0,
    shootoffs: list[tuple[int, dict[str, Decimal | None]]] | None = None,
) -> Result:
    """``shootoffs``: Liste von (Nr., {key: Wert oder None}) in Reihenfolge der Nr."""
    shootoffs = shootoffs or []
    valid = [e for e in entries if e.value is not None and not e.out_of_competition]
    unranked = [e.key for e in entries if e.value is None or e.out_of_competition]

    def better_first(items, key):
        return sorted(items, key=key, reverse=higher_better)

    ordered = better_first(valid, lambda e: e.value)
    placed: list[Placed] = []
    open_ties: list[OpenTie] = []

    def resolve(group: list[Entry], start: int, level: int, so_values: dict[str, dict]) -> None:
        if len(group) == 1:
            e = group[0]
            placed.append(Placed(e.key, e.value, start, so_values.get(e.key, {})))
            return
        if start > prize_places:
            for e in group:
                placed.append(Placed(e.key, e.value, start, so_values.get(e.key, {}), tie=True))
            return
        keys = {e.key for e in group}
        for idx in range(level, len(shootoffs)):
            number, values = shootoffs[idx]
            if not keys <= set(values):
                continue
            if any(values[k] is None for k in keys):
                open_ties.append(OpenTie(sorted(keys), start, number))
                break
            for k in keys:
                so_values.setdefault(k, {})[number] = values[k]
            # Untergruppen nach dem Stechwert
            sub = better_first(group, lambda e, v=values: v[e.key])
            pos = 0
            while pos < len(sub):
                val = values[sub[pos].key]
                same = [e for e in sub[pos:] if values[e.key] == val]
                resolve(same, start + pos, idx + 1, so_values)
                pos += len(same)
            return
        else:
            open_ties.append(OpenTie(sorted(keys), start, None))
        for e in group:
            placed.append(Placed(e.key, e.value, start, so_values.get(e.key, {}), tie=True))

    pos = 0
    so_values: dict[str, dict] = {}
    while pos < len(ordered):
        val = ordered[pos].value
        group = [e for e in ordered[pos:] if e.value == val]
        resolve(group, pos + 1, 0, so_values)
        pos += len(group)
    placed.sort(key=lambda p: (p.place, p.key))
    return Result(placed, open_ties, unranked)


@dataclass
class TeamValue:
    value: Decimal | None
    count: int
    counted: list[str]  # keys der Starter, die in den Wert eingehen
    reason: str = ""  # warum nicht gewertet


def team_value(
    members: list[Entry], *, mode: str, size: int | None, higher_better: bool = True
) -> TeamValue:
    """Wert einer Untereinheit aus den Werten ihrer Starter."""
    valid = [e for e in members if e.value is not None and not e.out_of_competition]
    valid.sort(key=lambda e: e.value, reverse=higher_better)
    count = len(valid)
    if count == 0:
        return TeamValue(None, 0, [], "keine Schützen")
    if mode == "beste":
        k = size or 0
        if k <= 0:
            return TeamValue(None, count, [], "Anzahl der besten fehlt")
        if count < k:
            return TeamValue(None, count, [], f"nur {count} von {k} Schützen")
        best = valid[:k]
        return TeamValue(sum((e.value for e in best), Decimal(0)), count, [e.key for e in best])
    total = sum((e.value for e in valid), Decimal(0))
    if mode == "durchschnitt":
        avg = (total / count).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return TeamValue(avg, count, [e.key for e in valid])
    return TeamValue(total, count, [e.key for e in valid])
