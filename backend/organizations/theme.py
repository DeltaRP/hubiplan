"""Farben, Kontrastprüfung (WCAG 2.x) und Vererbung des Erscheinungsbilds."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# Standard der Plattform, falls nirgends etwas gesetzt ist (Hubi-Grün, Hubi-Gold)
DEFAULT_PRIMARY = "#0e7c66"
DEFAULT_ACCENT = "#f2b33d"

DARK_TEXT = "#1d2421"
LIGHT_TEXT = "#ffffff"
SURFACE = "#ffffff"

# Mindestkontraste: Text auf Farbflächen (normaler Text) und Primärfarbe als
# Linkfarbe/Rahmen auf weißem Hintergrund (Bedienelemente)
MIN_TEXT_CONTRAST = 4.5
MIN_UI_CONTRAST = 3.0


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_color_on(background: str) -> str:
    """Besser lesbare Schriftfarbe (hell oder dunkel) auf einer Farbfläche."""
    if contrast(background, LIGHT_TEXT) >= contrast(background, DARK_TEXT):
        return LIGHT_TEXT
    return DARK_TEXT


def validate_hex_color(value: str) -> None:
    if not HEX_COLOR.match(value or ""):
        raise ValidationError(gettext("Bitte eine Farbe im Format #RRGGBB angeben."))


def check_primary(color: str) -> list[str]:
    problems = []
    if contrast(color, text_color_on(color)) < MIN_TEXT_CONTRAST:
        problems.append("Text auf der Primärfarbe wäre schlecht lesbar.")
    if contrast(color, SURFACE) < MIN_UI_CONTRAST:
        problems.append("Die Primärfarbe ist auf weißem Hintergrund zu hell (Rahmen und Symbole).")
    return problems


def check_accent(color: str) -> list[str]:
    if contrast(color, text_color_on(color)) < MIN_TEXT_CONTRAST:
        return ["Text auf der Akzentfarbe wäre schlecht lesbar."]
    return []


# Weitere Farben neben Haupt- und Zweitfarbe (Palette höchstens sechs Farben)
MAX_EXTRA_COLORS = 4
MAX_COLOR_NAME = 30


def clean_extra_colors(value) -> list[dict]:
    """Weitere Farben prüfen: Liste von {color, name}, Text darauf muss lesbar sein."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError(gettext("Weitere Farben bitte als Liste angeben."))
    if len(value) > MAX_EXTRA_COLORS:
        raise ValidationError(
            gettext("Höchstens {MAX_EXTRA_COLORS} weitere Farben (zusammen sechs).").format(
                MAX_EXTRA_COLORS=MAX_EXTRA_COLORS
            )
        )
    result = []
    for i, item in enumerate(value, start=3):
        if not isinstance(item, dict):
            raise ValidationError(gettext("Weitere Farben bitte als Liste angeben."))
        color = str(item.get("color") or "").lower()
        validate_hex_color(color)
        if contrast(color, text_color_on(color)) < MIN_TEXT_CONTRAST:
            raise ValidationError(
                gettext("Text auf der {i}. Farbe wäre schlecht lesbar.").format(i=i)
            )
        name = str(item.get("name") or "").strip()
        if len(name) > MAX_COLOR_NAME:
            raise ValidationError(
                gettext("Farbnamen bitte höchstens {MAX_COLOR_NAME} Zeichen.").format(
                    MAX_COLOR_NAME=MAX_COLOR_NAME
                )
            )
        result.append({"color": color, "name": name})
    return result


def _entry(color: str, name: str) -> dict:
    return {"color": color, "on_color": text_color_on(color), "name": name or ""}


def effective_theme(chain: list) -> dict:
    """Erscheinungsbild aus einer Kette vom Speziellsten zum Allgemeinsten.

    Jedes Glied hat ``primary_color``, ``accent_color`` und ``logo``; das erste
    gesetzte gewinnt (Abteilung ← Verein ← Dachverband ← Plattform).
    """

    def first(attr: str):
        for item in chain:
            value = getattr(item, attr, None)
            if value:
                return value, item
        return None, None

    primary, primary_src = first("primary_color")
    accent, _ = first("accent_color")
    logo, logo_src = first("logo")
    primary = primary or DEFAULT_PRIMARY
    accent = accent or DEFAULT_ACCENT
    # Palette erbt als Ganzes mit der Hauptfarbe (Ralf 2026-10-31): Namen und weitere
    # Farben kommen von der Ebene, die die Hauptfarbe festlegt
    palette = [
        _entry(primary, getattr(primary_src, "primary_color_name", "")),
        _entry(accent, getattr(primary_src, "accent_color_name", "")),
    ]
    for item in getattr(primary_src, "extra_colors", None) or []:
        color = item.get("color") if isinstance(item, dict) else None
        if color and HEX_COLOR.match(color):
            palette.append(_entry(color.lower(), item.get("name", "")))
    return {
        "primary": primary,
        "on_primary": text_color_on(primary),
        "accent": accent,
        "on_accent": text_color_on(accent),
        "logo_url": logo.url if logo else None,
        "palette": palette[: 2 + MAX_EXTRA_COLORS],
        "inherited_from": {
            "colors": getattr(primary_src, "name", None),
            "logo": getattr(logo_src, "name", None),
        },
    }
