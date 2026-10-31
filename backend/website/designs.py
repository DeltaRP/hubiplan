"""Standarddesigns der Vereinswebseite und Zuordnung der Einheitsfarben zu Rollen.

Ein Design legt Aufbau (Kopf, Menü, Fuß, Startseite) fest; die Webseite zeichnet es.
HUBIplan bestimmt nur, welche Farbe aus der Palette der Einheit welche Rolle bekommt
(Konzept konzepte/webseiten-designs.md, Ralf 2026-10-31).
"""

from __future__ import annotations

from organizations.theme import DARK_TEXT, LIGHT_TEXT, text_color_on

DEFAULT_DESIGN = "classic"

# Rollen, in denen ein Design Farben einsetzt
ROLES = {
    "header": "Kopf",
    "nav": "Menü (Leiste oder Markierung)",
    "line": "Zierlinien",
    "footer": "Fuß",
    "band": "Farbband",
    "band2": "zweites Farbband",
    "date": "Datumsfeld bei Terminen",
}

# Feste Werte neben den Palettenplätzen
NEUTRAL = {"dark": DARK_TEXT, "light": LIGHT_TEXT}

# Je Design: Name, Beschreibung und Vorgaben je Rolle. Eine Vorgabe ist eine Liste
# von Palettenplätzen (0 = Hauptfarbe, 1 = Zweitfarbe, 2 … = weitere Farben) oder ein
# fester Wert; der erste vorhandene Platz gilt.
DESIGNS: dict[str, dict] = {
    "classic": {
        "label": "Klassisch",
        "hint": "Farbiger Kopf mit Wappen links und Menü rechts, Karten auf hellem Grund.",
        "roles": {
            "header": [0],
            "nav": [1],
            "line": [1],
            "footer": "dark",
            "date": [0],
        },
    },
    "festive": {
        "label": "Festlich",
        "hint": "Wappen groß und mittig, Menüleiste mit Zierlinien, Überschriften mit Serifen.",
        "roles": {
            "header": [0],
            "nav": [1],
            "line": [1],
            "footer": [0],
            "date": [2, 0],
        },
    },
    "sidebar": {
        "label": "Seitenleiste",
        "hint": "Menü senkrecht in einer Leiste links, auf dem Handy schmaler Kopf.",
        "roles": {
            "header": [0],
            "nav": [1],
            "line": [1],
            "footer": "light",
            "date": [0],
        },
    },
    "stage": {
        "label": "Bühne",
        "hint": "Heller Kopf, großes Titelbild mit dem Namen, Startseite in farbigen Bändern.",
        "roles": {
            "header": "light",
            "nav": [0],
            "line": [1],
            "footer": [0],
            "band": [0],
            "band2": [2, 0],
            "date": [1],
        },
    },
    "newspaper": {
        "label": "Zeitung",
        "hint": "Kontaktleiste oben, Menü als Reiter, Startseite in zwei Spalten.",
        "roles": {
            "header": [0],
            "nav": [1],
            "line": [2, 0],
            "footer": "dark",
            "date": [0],
        },
    },
}


def _pick(spec, palette: list[dict]) -> str:
    if isinstance(spec, str):
        return NEUTRAL.get(spec, NEUTRAL["dark"])
    for index in spec:
        if 0 <= index < len(palette):
            return palette[index]["color"]
    return palette[0]["color"]


def valid_choice(value) -> bool:
    """Gespeicherte Wahl je Rolle: Palettenplatz 0–5 oder „dark“/„light“."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 5
    return value in NEUTRAL


def normalize_color_roles(value) -> dict:
    """{design: {rolle: wahl}} → nur bekannte Designs, Rollen und Werte."""
    result: dict[str, dict] = {}
    if not isinstance(value, dict):
        return result
    for key, roles in value.items():
        if key not in DESIGNS or not isinstance(roles, dict):
            continue
        used = DESIGNS[key]["roles"]
        clean = {r: v for r, v in roles.items() if r in used and valid_choice(v)}
        if clean:
            result[key] = clean
    return result


def resolve(design: str, palette: list[dict], color_roles: dict | None = None) -> dict:
    """Farben je Rolle für ein Design: {rolle: {color, on_color}}."""
    spec = DESIGNS.get(design, DESIGNS[DEFAULT_DESIGN])["roles"]
    chosen = normalize_color_roles(color_roles or {}).get(design, {})
    result = {}
    for role, default in spec.items():
        choice = chosen.get(role)
        if isinstance(choice, int):
            color = _pick([choice], palette) if choice < len(palette) else _pick(default, palette)
        elif isinstance(choice, str):
            color = NEUTRAL[choice]
        else:
            color = _pick(default, palette)
        result[role] = {"color": color, "on_color": text_color_on(color)}
    return result


def catalog() -> list[dict]:
    """Für die Oberfläche: Designs mit Rollen und Vorgaben."""
    return [
        {
            "key": key,
            "label": d["label"],
            "hint": d["hint"],
            "roles": [
                {
                    "key": role,
                    "label": ROLES[role],
                    "default": spec if isinstance(spec, str) else spec[0],
                }
                for role, spec in d["roles"].items()
            ],
        }
        for key, d in DESIGNS.items()
    ]
