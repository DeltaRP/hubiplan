"""Scheibenkatalog und Wertung aus einem Trefferpunkt.

Eine Ringscheibe ist durch wenige Maße bestimmt: Durchmesser des höchsten Rings,
Ringbreite, niedrigster Ring, Innenzehner und Kaliber. Daraus folgt für einen Treffer
mit Abstand *d* (Scheibenmitte bis Lochmitte, in mm):

- Grenze des höchsten Rings *g* = Radius höchster Ring + Kaliber/2 (der Lochrand berührt
  die Ringlinie, dann zählt der höhere Ring),
- Wert = höchster Ring + (*g* − *d*) / Ringbreite,
- Zehntel: auf eine Stelle abschneiden, höchstens höchster Ring + 0,9,
- Ring: Wert abschneiden, höchstens höchster Ring; unter dem niedrigsten Ring: 0,
- Teiler: *d* in 1/100 mm, mal Teilerfaktor.

Maße und Herleitung: konzepte/schiessscheiben-recherche.md (Abschnitte 1.1–1.3). Angaben
mit „prüfen“ dort sind vor amtlicher Nutzung gegen die aktuelle Sportordnung zu lesen;
HUBIplan wertet ohnehin nur vereinsintern.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CUSTOM = "eigen"

# Innenzehner: „berühren“ (Lochrand berührt den Innenzehnerring, LP/KK) oder „wegschießen“
# (der Punkt in der Mitte ist ganz weggeschossen, LG)
INNER_TOUCH = "beruehren"
INNER_COVER = "wegschiessen"


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    group: str
    top_diameter: float  # Durchmesser des höchsten Rings in mm
    ring_width: float  # Ringbreite in mm (halber Abstand der Durchmesser)
    caliber: float  # Kaliber für die Wertung in mm
    top: int = 10  # höchster Ring
    lowest: int = 1  # niedrigster Ring auf der Scheibe
    inner_diameter: float | None = None  # Innenzehner (mm), leer: gibt es nicht
    inner_mode: str = INNER_TOUCH
    black_diameter: float | None = None  # Spiegel (schwarz), nur zum Zeichnen
    spots: int = 1  # Spiegel je Karte
    teiler_factor: float = 1.0
    note: str = ""

    def ring_diameter(self, ring: int) -> float:
        """Durchmesser der Außenlinie eines Rings."""
        return self.top_diameter + 2 * self.ring_width * (self.top - ring)

    @property
    def outer_diameter(self) -> float:
        return self.ring_diameter(self.lowest)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["rings"] = [
            {"ring": r, "diameter": round(self.ring_diameter(r), 3)}
            for r in range(self.lowest, self.top + 1)
        ]
        data["max_decimal"] = str(max_decimal(self))
        return data


CATALOG: tuple[Target, ...] = (
    Target(
        "lg10_dsb",
        "Luftgewehr 10 m (DSB/ISSF)",
        "Luftgewehr",
        top_diameter=0.5,
        ring_width=2.5,
        caliber=4.5,
        inner_diameter=0.5,
        inner_mode=INNER_COVER,
        black_diameter=30.5,
        note="Zehn ist der weiße Punkt; Innenzehner, wenn er ganz weggeschossen ist.",
    ),
    Target(
        "lg10_kyf",
        "Luftgewehr 10 m Kyffhäuser",
        "Luftgewehr",
        top_diameter=2.0,
        ring_width=4.5,
        caliber=4.5,
        black_diameter=29.0,
        note="Alte Kyffhäuser-Scheibe: Zehn 2 mm, Ringe 4,5 mm breit.",
    ),
    Target(
        "lg10_kyf5",
        "Luftgewehr 10 m Kyffhäuser, 5 Spiegel",
        "Luftgewehr",
        top_diameter=2.0,
        ring_width=4.5,
        caliber=4.5,
        lowest=6,
        black_diameter=29.0,
        spots=5,
        note="Fünf Scheibenbilder je Karte, nur Ringe 6 bis 10.",
    ),
    Target(
        "lg10_ufolep",
        "Luftgewehr 10 m UFOLEP (7 Ringe)",
        "Luftgewehr",
        top_diameter=2.0,
        ring_width=4.5,
        caliber=4.5,
        lowest=4,
        note="Maße wie Kyffhäuser, Ringe 4 bis 10 (prüfen).",
    ),
    Target(
        "ls10",
        "Laufende Scheibe 10 m",
        "Luftgewehr",
        top_diameter=5.5,
        ring_width=2.5,
        caliber=4.5,
        inner_diameter=0.5,
        inner_mode=INNER_COVER,
        black_diameter=30.5,
        note="Innenzehner (Punkt 0,5 mm) prüfen.",
    ),
    Target(
        "lp10",
        "Luftpistole 10 m (DSB/ISSF)",
        "Luftpistole",
        top_diameter=11.5,
        ring_width=8.0,
        caliber=4.5,
        inner_diameter=5.0,
        black_diameter=59.5,
        note="Auch Kyffhäuser LP 10 m.",
    ),
    Target(
        "kk50",
        "Kleinkaliber 50 m (DSB/ISSF)",
        "Kleinkaliber",
        top_diameter=10.4,
        ring_width=8.0,
        caliber=5.6,
        inner_diameter=5.0,
        black_diameter=112.4,
        note="Auch Kyffhäuser KK 50 m.",
    ),
    Target(
        "kk100",
        "Kleinkaliber 100 m",
        "Kleinkaliber",
        top_diameter=50.0,
        ring_width=25.0,
        caliber=5.6,
    ),
    Target(
        "p25",
        "Pistole 25 m Präzision / 50 m",
        "Pistole",
        top_diameter=50.0,
        ring_width=25.0,
        caliber=5.6,
        inner_diameter=25.0,
        black_diameter=200.0,
        note="Kaliber je nach Waffe; 5,6 mm voreingestellt (prüfen).",
    ),
)

BY_KEY = {t.key: t for t in CATALOG}

# Grenzen für eine eigene Scheibe
CUSTOM_FIELDS = {
    "top_diameter": (0.0, 500.0),
    "ring_width": (0.1, 100.0),
    "caliber": (1.0, 20.0),
    "inner_diameter": (0.0, 500.0),
    "black_diameter": (0.0, 2000.0),
    "teiler_factor": (0.01, 100.0),
}
FIELD_LABELS = {
    "top_diameter": "Durchmesser höchster Ring",
    "ring_width": "Ringbreite",
    "caliber": "Kaliber",
    "inner_diameter": "Innenzehner",
    "inner_mode": "Innenzehner",
    "black_diameter": "Spiegel",
    "teiler_factor": "Teilerfaktor",
    "top": "Höchster Ring",
    "lowest": "Niedrigster Ring",
    "spots": "Scheibenbilder je Karte",
}


class TargetError(ValueError):
    """Ungültige Angaben zu einer eigenen Scheibe (Text für die Oberfläche)."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


def _number(data: dict, field: str, *, required: bool) -> float | None:
    raw = data.get(field)
    if raw in (None, ""):
        if required:
            raise TargetError(field, "Bitte angeben.")
        return None
    try:
        value = float(str(raw).replace(",", "."))
    except ValueError as exc:
        raise TargetError(field, "Bitte eine Zahl eingeben.") from exc
    low, high = CUSTOM_FIELDS[field]
    if not math.isfinite(value) or value < low or value > high:
        raise TargetError(field, f"Bitte einen Wert zwischen {low:g} und {high:g} eingeben.")
    return value


def _int(data: dict, field: str, default: int, low: int, high: int) -> int:
    raw = data.get(field)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise TargetError(field, "Bitte eine ganze Zahl eingeben.") from exc
    if value < low or value > high:
        raise TargetError(field, f"Bitte eine Zahl von {low} bis {high} eingeben.")
    return value


def clean_custom(data) -> dict:
    """Eigene Scheibe prüfen und bereinigt zurückgeben (für ``Scoring.custom_target``)."""
    if not isinstance(data, dict):
        raise TargetError("custom_target", "Ungültige Angaben zur Scheibe.")
    out: dict = {
        "name": str(data.get("name") or "").strip()[:100] or "Eigene Scheibe",
        "top_diameter": _number(data, "top_diameter", required=True),
        "ring_width": _number(data, "ring_width", required=True),
        "caliber": _number(data, "caliber", required=True),
        "top": _int(data, "top", 10, 1, 20),
    }
    out["lowest"] = _int(data, "lowest", 1, 0, out["top"])
    if out["lowest"] == 0:
        out["lowest"] = 1
    inner = _number(data, "inner_diameter", required=False)
    out["inner_diameter"] = inner or None
    mode = data.get("inner_mode") or INNER_TOUCH
    if mode not in (INNER_TOUCH, INNER_COVER):
        raise TargetError("inner_mode", "Ungültige Angabe zum Innenzehner.")
    out["inner_mode"] = mode
    out["black_diameter"] = _number(data, "black_diameter", required=False) or None
    out["spots"] = _int(data, "spots", 1, 1, 20)
    out["teiler_factor"] = _number(data, "teiler_factor", required=False) or 1.0
    return out


def get(key: str, custom: dict | None = None) -> Target | None:
    """Scheibe zum Schlüssel; bei „eigen“ aus den Angaben der Wertung."""
    if key == CUSTOM:
        if not custom:
            return None
        try:
            c = clean_custom(custom)
        except TargetError:
            return None
        return Target(key=CUSTOM, group="Eigene", **c)
    return BY_KEY.get(key)


def catalog() -> list[dict]:
    return [t.as_dict() for t in CATALOG]


# --- Wertung ---

TENTH = Decimal("0.1")


@dataclass(frozen=True)
class ShotValue:
    ring: int  # ganze Ringe (0: Fehlschuss bzw. außerhalb der Ringe)
    decimal: Decimal  # Zehntelwert (0,0 außerhalb)
    inner: bool  # Innenzehner
    distance: Decimal  # Abstand Mitte–Lochmitte in mm (3 Stellen)
    teiler: Decimal  # Teiler (1/100 mm mal Faktor, 1 Stelle)

    def as_dict(self) -> dict:
        return {
            "ring": self.ring,
            "decimal": str(self.decimal),
            "inner": self.inner,
            "distance": str(self.distance),
            "teiler": str(self.teiler),
        }


def max_decimal(t: Target) -> Decimal:
    """Höchster Zehntelwert (Mitte getroffen), höchstens höchster Ring + 0,9."""
    return _decimal_value(t, 0.0)


def _decimal_value(t: Target, d: float) -> Decimal:
    edge = t.top_diameter / 2 + t.caliber / 2
    raw = t.top + (edge - d) / t.ring_width
    # kleine Rundungsfehler der Gleitkommazahl nicht abschneiden lassen
    value = Decimal(repr(raw)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    value = value.quantize(TENTH, rounding=ROUND_DOWN)
    return min(value, Decimal(t.top) + Decimal("0.9"))


def score(t: Target, x: float, y: float) -> ShotValue:
    """Wertung eines Treffers bei (x, y) in mm von der Scheibenmitte."""
    d = math.hypot(x, y)
    value = _decimal_value(t, d)
    ring = int(value.to_integral_value(rounding=ROUND_DOWN))
    if ring < t.lowest:
        ring, value = 0, Decimal("0.0")
    ring = min(ring, t.top)
    inner = False
    if t.inner_diameter and ring == t.top:
        r_in, r_cal = t.inner_diameter / 2, t.caliber / 2
        limit = r_cal - r_in if t.inner_mode == INNER_COVER else r_in + r_cal
        inner = d <= limit + 1e-9
    dist = Decimal(repr(d)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    teiler = (Decimal(repr(d * 100 * t.teiler_factor))).quantize(TENTH, rounding=ROUND_HALF_UP)
    return ShotValue(ring, value, inner, dist, teiler)


# --- Wertungsarten ---

METHOD_FREE = "frei"
METHOD_RINGS = "ringe"
METHOD_DECIMAL = "zehntel"
METHOD_TEILER = "teiler"


def shot_measure(method: str, sv: ShotValue) -> Decimal:
    if method == METHOD_DECIMAL:
        return sv.decimal
    if method == METHOD_TEILER:
        return sv.teiler
    return Decimal(sv.ring)


def total(method: str, shots: list[ShotValue], counted: int | None) -> Decimal | None:
    """Wert eines Starters aus seinen Schüssen.

    Ringe und Zehntel: Summe der besten ``counted`` Schüsse (leer: aller). Teiler: der
    beste (kleinste) Teiler; bei ``counted`` > 1 die Summe der besten Teiler."""
    if not shots:
        return None
    values = [shot_measure(method, s) for s in shots]
    lower = method == METHOD_TEILER
    values.sort(reverse=not lower)
    if method == METHOD_TEILER:
        k = counted or 1
    else:
        k = counted or len(values)
    return sum(values[:k], Decimal(0))


def counted_shots(method: str, shots: list[ShotValue], counted: int | None) -> list[ShotValue]:
    """Die Schüsse, die in ``total`` eingehen (gleiche Auswahl, Reihenfolge wie geschossen)."""
    if not shots:
        return []
    lower = method == METHOD_TEILER
    k = (counted or 1) if lower else (counted or len(shots))
    order = sorted(
        range(len(shots)),
        key=lambda i: shot_measure(method, shots[i]),
        reverse=not lower,
    )
    keep = sorted(order[:k])
    return [shots[i] for i in keep]
