"""Unterschriften auf dem Bildschirm (Quittungen): prüfen, vereinheitlichen, zeichnen.

Browser und App schicken die Linienzüge der Unterschrift::

    {"width": 600, "height": 220, "strokes": [[[x, y], [x, y], …], …]}

Gespeichert wird nur die Form, auf eine Breite von 1000 umgerechnet und ganzzahlig::

    {"w": 1000, "h": 367, "s": [[x1, y1, x2, y2, …], …]}

Zeit, Druck und Geschwindigkeit werden weder angenommen noch gespeichert. Damit ist die
Unterschrift ein gewöhnliches Bild wie auf Papier und keine biometrische Messung.
"""

from __future__ import annotations

import math

from django.core.exceptions import ValidationError
from reportlab.graphics.shapes import Drawing, PolyLine
from reportlab.lib import colors

WIDTH = 1000
MAX_STROKES = 300
MAX_POINTS = 20000
# Mindestlänge der Linien (in Einheiten bei Breite 1000), damit ein Antippen nicht zählt
MIN_LENGTH = 120

EMPTY = "Bitte unterschreiben."


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("Die Unterschrift ist ungültig.")
    if not math.isfinite(value):
        raise ValidationError("Die Unterschrift ist ungültig.")
    return float(value)


def normalize(data) -> dict:
    """Eingabe prüfen und in die gespeicherte Form bringen (ValidationError sonst)."""
    if not isinstance(data, dict):
        raise ValidationError("Die Unterschrift ist ungültig.")
    width = _number(data.get("width"))
    height = _number(data.get("height"))
    if not (10 <= width <= 10000 and 10 <= height <= 10000):
        raise ValidationError("Die Unterschrift ist ungültig.")
    strokes = data.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        raise ValidationError(EMPTY)
    if len(strokes) > MAX_STROKES:
        raise ValidationError("Die Unterschrift hat zu viele Striche.")
    scale = WIDTH / width
    box_h = round(height * scale)
    result: list[list[int]] = []
    total = 0
    length = 0.0
    for stroke in strokes:
        if not isinstance(stroke, list):
            raise ValidationError("Die Unterschrift ist ungültig.")
        flat: list[int] = []
        last = None
        for point in stroke:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValidationError("Die Unterschrift ist ungültig.")
            x = min(max(_number(point[0]), 0.0), width) * scale
            y = min(max(_number(point[1]), 0.0), height) * scale
            xi, yi = round(x), round(y)
            if last is not None:
                if (xi, yi) == last:
                    continue
                length += math.dist(last, (xi, yi))
            flat += [xi, yi]
            last = (xi, yi)
            total += 1
            if total > MAX_POINTS:
                raise ValidationError("Die Unterschrift hat zu viele Punkte.")
        if flat:
            result.append(flat)
    if length < MIN_LENGTH:
        raise ValidationError(EMPTY)
    return {"w": WIDTH, "h": box_h, "s": result}


def is_valid(stored) -> bool:
    """Gespeicherte Form plausibel (z. B. aus einer hinterlegten Unterschrift)."""
    return (
        isinstance(stored, dict)
        and isinstance(stored.get("s"), list)
        and bool(stored["s"])
        and all(isinstance(s, list) and len(s) % 2 == 0 for s in stored["s"])
    )


INK = colors.HexColor("#1a2a6c")


def drawing(stored: dict, box_w: float, box_h: float, color=INK):
    """Unterschrift als Vektorgrafik, auf den Bereich mit Tinte zugeschnitten und in das
    Kästchen eingepasst (Seitenverhältnis bleibt)."""
    d = Drawing(box_w, box_h)
    strokes = [s for s in stored.get("s", []) if len(s) >= 2]
    if not strokes:
        return d
    xs = [v for s in strokes for v in s[0::2]]
    ys = [v for s in strokes for v in s[1::2]]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    ink_w = max(max_x - min_x, 1)
    ink_h = max(max_y - min_y, 1)
    pad = 2
    scale = min((box_w - 2 * pad) / ink_w, (box_h - 2 * pad) / ink_h)
    off_x = pad + (box_w - 2 * pad - ink_w * scale) / 2
    off_y = pad + (box_h - 2 * pad - ink_h * scale) / 2
    width = max(0.8, min(1.6, 3 * scale))
    for s in strokes:
        points: list[float] = []
        for i in range(0, len(s), 2):
            points.append(off_x + (s[i] - min_x) * scale)
            # Bildschirm: y nach unten, PDF: y nach oben
            points.append(off_y + (max_y - s[i + 1]) * scale)
        if len(points) == 2:
            points += [points[0] + 0.3, points[1]]
        d.add(
            PolyLine(
                points,
                strokeColor=color,
                strokeWidth=width,
                strokeLineCap=1,
                strokeLineJoin=1,
            )
        )
    return d
