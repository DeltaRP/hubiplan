"""Übliche Mehrzahl deutscher Bezeichnungen für Würden und Ehrungen.

Nur eine Vorgabe: wo sie nicht passt, trägt die Einheit die Mehrzahl selbst ein.
"""

from __future__ import annotations

# Endungen, die „-en“ bekommen (Prinz → Prinzen, Ehrenpräsident → Ehrenpräsidenten)
EN = ("prinz", "graf", "fürst", "regent", "präsident", "oberst", "kamerad")


def guess_plural(name: str) -> str:
    """König → Könige, Prinz → Prinzen, Kaiser bleibt, Ehrenmitglied → Ehrenmitglieder."""
    name = name.strip()
    low = name.lower()
    if not name:
        return name
    if low.endswith("hauptmann"):
        return name[: -len("hauptmann")] + "hauptleute"
    if low.endswith("glied"):
        return name + "er"
    if low.endswith("nder"):  # Ehrenvorsitzender → Ehrenvorsitzende
        return name[:-1]
    if low.endswith(("er", "el", "en")):
        return name
    if low.endswith("in"):
        return name + "nen"
    if low.endswith(EN):
        return name + "en"
    if low.endswith("e"):
        return name + "n"
    return name + "e"
