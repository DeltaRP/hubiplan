"""Gleichstandsregeln aus den Treffern eines Starters.

Eine Wertung hält eine Kette von Regeln (``Scoring.tie_breaks``). Bei gleichem Wert
entscheidet die erste Regel, die die Gleichen trennt; bleibt es gleich, die nächste.
Fehlen einem der Gleichen die Treffer, endet die Kette dort, und es bleibt beim
bisherigen Weg: gleicher Platz, auf Preisplätzen Stechen.

Jede Regel liefert einen vergleichbaren Wert, bei dem größer besser ist (Teiler und
Abstand werden dafür negiert). Vorbilder: DSB-Sportordnung 9.4.1 (Serien rückwärts,
Anzahl 10er/9er, Innenzehner, Zehntel), BHDS 8.4 (Ringzahlen, schlechtester Schuss bzw.
Teiler); Recherche Abschnitt 2.3.
"""

from __future__ import annotations

from decimal import Decimal

from .targets import METHOD_DECIMAL, ShotValue, Target

SERIES = "serien"
RING_COUNTS = "ringzahlen"
INNER = "innenzehner"
DECIMAL = "zehntel"
TEILER = "teiler"
WORST = "schlechtester"

CRITERIA: tuple[tuple[str, str], ...] = (
    (SERIES, "Serien von hinten verglichen"),
    (RING_COUNTS, "mehr Zehner, dann Neuner usw."),
    (INNER, "mehr Innenzehner"),
    (DECIMAL, "höhere Summe in Zehnteln"),
    (TEILER, "besserer Teiler"),
    (WORST, "schlechtester Schuss näher an der Mitte"),
)
LABELS = dict(CRITERIA)

# Vorlagen für die Oberfläche
PRESETS = {
    "dsb": [SERIES, RING_COUNTS, INNER, DECIMAL],
    "bhds": [RING_COUNTS, WORST],
}


def clean(raw) -> list[str]:
    """Kette prüfen: bekannte Regeln, jede höchstens einmal, Reihenfolge bleibt."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("Ungültige Gleichstandsregeln.")
    out: list[str] = []
    for item in raw:
        if item not in LABELS:
            raise ValueError(f"Unbekannte Gleichstandsregel „{item}“.")
        if item not in out:
            out.append(item)
    return out


def value(criterion: str, shots: list[ShotValue], target: Target, method: str, series_size: int):
    """Vergleichswert einer Regel für die gewerteten Schüsse (in Schussreihenfolge)."""
    if not shots:
        return None
    if criterion == SERIES:
        size = max(series_size or 10, 1)
        per_shot = [s.decimal if method == METHOD_DECIMAL else Decimal(s.ring) for s in shots]
        series = [sum(per_shot[i : i + size], Decimal(0)) for i in range(0, len(per_shot), size)]
        return tuple(reversed(series))
    if criterion == RING_COUNTS:
        return tuple(
            sum(1 for s in shots if s.ring == r) for r in range(target.top, target.lowest - 1, -1)
        )
    if criterion == INNER:
        return sum(1 for s in shots if s.inner)
    if criterion == DECIMAL:
        return sum((s.decimal for s in shots), Decimal(0))
    if criterion == TEILER:
        return -min(s.teiler for s in shots)
    if criterion == WORST:
        return -max(s.distance for s in shots)
    return None


def vector(
    chain: list[str], shots: list[ShotValue], target: Target, method: str, series_size: int
) -> tuple:
    return tuple(value(c, shots, target, method, series_size) for c in chain)
