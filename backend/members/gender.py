"""Geschlecht: Eingaben erkennen und Werte aus einem Zusatzfeld „Geschlecht“ übernehmen."""

from __future__ import annotations

import re
from collections import defaultdict

from .models import Gender

# Übliche Schreibweisen aus Excel-Listen und Zusatzfeldern
ALIASES = {
    Gender.MALE: {"männlich", "maennlich", "mannlich", "m", "mann", "herr", "male"},
    Gender.FEMALE: {"weiblich", "w", "f", "frau", "female"},
    Gender.DIVERSE: {"divers", "d", "x", "diverse"},
}
# Verglichen wird ohne Punkte und Leerzeichen („k. a.“, „k.a“, „K.A.“ sind gleich)
EMPTY = {"", "-", "–", "ka", "keineangabe", "unbekannt"}


def parse_gender(value) -> str | None:
    """Erkannter Wert (leer = keine Angabe) oder None, wenn unbekannt."""
    text = re.sub(r"[\s.]", "", str(value or "").lower())
    if text in EMPTY:
        return ""
    for gender, names in ALIASES.items():
        if text in names:
            return str(gender)
    return None


def take_over_field(person_model, definition_model, value_model) -> int:
    """Übernimmt Werte aus Zusatzfeldern mit der Bezeichnung „Geschlecht“.

    Nur Personen ohne eigene Angabe werden gefüllt; das Zusatzfeld bleibt
    unverändert. Widersprüchliche Werte derselben Person werden nicht übernommen.
    Gibt die Zahl der gesetzten Personen zurück. Die Modelle werden
    übergeben, damit auch eine Migration die Funktion nutzen kann.
    """
    definitions = definition_model.objects.filter(
        label__iexact="Geschlecht", repeatable=False
    ).values_list("pk", flat=True)
    # Je Person sammeln: widersprechen sich zwei Felder (z. B. in zwei Vereinen), bleibt
    # die Person leer und wird von Hand geklärt
    found: dict[int, set[str]] = defaultdict(set)
    for person_id, value in value_model.objects.filter(
        definition_id__in=list(definitions), person__gender=""
    ).values_list("person_id", "value"):
        if gender := parse_gender(value):
            found[person_id].add(gender)
    changed = 0
    for person_id, genders in found.items():
        if len(genders) == 1:
            changed += person_model.objects.filter(pk=person_id, gender="").update(
                gender=genders.pop()
            )
    return changed
