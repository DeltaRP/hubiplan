"""Messlatte für die Erkennung (Schießscheiben Schritt 3).

Freigabe-Kennzahlen aus der Recherche (Abschnitt 5a): Anteil richtig erkannter Schusszahl,
Anteil richtiger ganzer Ringe, und wie oft die Erkennung zu Recht „bitte prüfen“ meldet.
Am wichtigsten ist ``unbemerkt_falsch``: falsche Wertung ohne Prüfhinweis, denn die würde
ein Mensch am Stand am ehesten übersehen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .. import targets


@dataclass
class Detection:
    """Ergebnis einer Erkennung: Treffer in mm (Scheibenmitte, y nach oben)."""

    hits: list[tuple[float, float]]
    needs_review: bool = False
    note: str = ""
    # Karten mit mehreren Spiegeln: Spiegel je Treffer (ab 1); Treffer um dessen Mitte
    spots: list[int] = field(default_factory=list)
    # entzerrte Spiegelausschnitte (JPEG), nur auf Wunsch (Sammeln mit Einwilligung)
    crops: list[bytes] = field(default_factory=list)


@dataclass
class Outcome:
    count_ok: bool
    rings_ok: bool
    total_ok: bool
    needs_review: bool
    max_error_mm: float | None  # größter Fehler im Abstand zur Mitte (mm)

    @property
    def wrong(self) -> bool:
        return not (self.count_ok and self.rings_ok)


def compare(target_key: str, truth: list[tuple[float, float]], det: Detection) -> Outcome:
    t = targets.BY_KEY[target_key]
    want = sorted(targets.score(t, x, y).ring for x, y in truth)
    got = sorted(targets.score(t, x, y).ring for x, y in det.hits)
    # Lagefehler im Abstand zur Mitte (die Drehung des Fotos ist für die Wertung egal):
    # Abstände der Größe nach paarweise vergleichen
    dt = sorted((x * x + y * y) ** 0.5 for x, y in truth)
    dg = sorted((x * x + y * y) ** 0.5 for x, y in det.hits)
    pairs = list(zip(dt, dg, strict=False))
    worst = max((abs(a - b) for a, b in pairs), default=None)
    return Outcome(
        count_ok=len(det.hits) == len(truth),
        rings_ok=want == got,
        total_ok=sum(want) == sum(got),
        needs_review=det.needs_review,
        max_error_mm=None if worst is None else round(worst, 3),
    )


def summarize(outcomes: Iterable[Outcome]) -> dict:
    items = list(outcomes)
    n = len(items)
    if not n:
        return {"anzahl": 0}

    def share(pred) -> float:
        return round(100 * sum(1 for o in items if pred(o)) / n, 1)

    review = [o for o in items if o.needs_review]
    errors = [o.max_error_mm for o in items if o.max_error_mm is not None]
    return {
        "anzahl": n,
        "schusszahl_richtig": share(lambda o: o.count_ok),
        "ringe_richtig": share(lambda o: o.rings_ok),
        "summe_richtig": share(lambda o: o.total_ok),
        "bitte_pruefen": share(lambda o: o.needs_review),
        "pruefen_zu_recht": (
            round(100 * sum(1 for o in review if o.wrong) / len(review), 1) if review else None
        ),
        "unbemerkt_falsch": share(lambda o: o.wrong and not o.needs_review),
        "lagefehler_mm_max": max(errors) if errors else None,
        "lagefehler_mm_mittel": round(sum(errors) / len(errors), 3) if errors else None,
    }


Detector = Callable[[bytes, str, int | None], Detection]


def run(samples: Iterable[tuple[bytes, dict]], detector: Detector) -> dict:
    """Erkennung über Prüfbilder laufen lassen; ``samples``: (JPEG, Lösung wie Sample.truth)."""
    outcomes = []
    for image, truth in samples:
        det = detector(image, truth["target"], len(truth["hits"]))
        outcomes.append(compare(truth["target"], [tuple(h) for h in truth["hits"]], det))
    return summarize(outcomes)
