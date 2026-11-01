"""Frei definierbare Zusatzfelder je Organisation.

- Ein Verein legt Felder für seine Mitglieder an.
- Ein Dachverband legt Felder für seine Ebene an; ist ein Feld „verbandsweit“,
  gilt es einheitlich in allen seinen Vereinen (z. B. Verbandsehrennadel).
- Wiederholbare Felder haben Unterfelder und mehrere Einträge je Person
  (z. B. Auszeichnung: Bezeichnung, Datum, verleihende Organisation).
"""

from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext

from core.encfields import EncryptedJSONField

TYPES = (
    ("text", "Text"),
    ("number", "Zahl"),
    ("date", "Datum"),
    ("bool", "Ja/Nein"),
    ("choice", "Auswahlliste"),
    ("yearrange", "Startjahr/Endjahr"),
)
TYPE_KEYS = {t for t, _ in TYPES}


def make_key(label: str) -> str:
    return (
        slugify(label.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))[
            :50
        ]
        or "feld"
    )


class FieldDefinition(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="field_definitions"
    )
    label = models.CharField("Bezeichnung", max_length=100)
    key = models.SlugField("Kennung", max_length=50)
    field_type = models.CharField(
        "Typ",
        max_length=10,
        choices=TYPES,
        default="text",
        help_text="Bei wiederholbaren Feldern unbenutzt.",
    )
    choices = models.JSONField("Auswahlwerte", default=list, blank=True)
    repeatable = models.BooleanField("wiederholbar", default=False)
    # Unterfelder wiederholbarer Felder: [{"key", "label", "type", "choices"}]
    subfields = models.JSONField("Unterfelder", default=list, blank=True)
    federation_wide = models.BooleanField(
        "verbandsweit",
        default=False,
        help_text="Nur bei Dachverbänden: gilt einheitlich für alle angeschlossenen Vereine.",
    )
    help_text = models.CharField("Hinweis", max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    is_archived = models.BooleanField("nicht mehr verwendet", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zusatzfeld"
        verbose_name_plural = "Zusatzfelder"
        ordering = ["sort_order", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="zusatzfeld_kennung_je_org"
            )
        ]

    def __str__(self) -> str:
        return self.label

    def clean(self) -> None:
        errors = {}
        if self.federation_wide and self.organization.type != "federation":
            errors["federation_wide"] = (
                "Nur eine übergeordnete Einheit kann verbandsweite Felder anlegen."
            )
        if self.repeatable:
            if not self.subfields:
                errors["subfields"] = "Ein wiederholbares Feld braucht mindestens ein Unterfeld."
            keys = set()
            for sub in self.subfields:
                if sub.get("type") not in TYPE_KEYS:
                    errors["subfields"] = f"Unbekannter Typ: {sub.get('type')}"
                if sub.get("type") == "choice" and not sub.get("choices"):
                    errors["subfields"] = f"„{sub.get('label')}“ braucht Auswahlwerte."
                if sub.get("key") in keys:
                    errors["subfields"] = "Unterfelder brauchen unterschiedliche Bezeichnungen."
                keys.add(sub.get("key"))
        elif self.field_type == "choice" and not self.choices:
            errors["choices"] = "Bitte Auswahlwerte angeben."
        if errors:
            raise ValidationError(errors)


class FieldValue(models.Model):
    """Wert eines Zusatzfelds für eine Person (Organisation = Eigentümer des Felds)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    definition = models.ForeignKey(FieldDefinition, on_delete=models.CASCADE, related_name="values")
    person = models.ForeignKey(
        "members.Person", on_delete=models.CASCADE, related_name="field_values"
    )
    # Verschlüsselt (core/encfields.py)
    value = EncryptedJSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Zusatzfeld-Wert"
        verbose_name_plural = "Zusatzfeld-Werte"
        constraints = [
            models.UniqueConstraint(fields=["definition", "person"], name="zusatzwert_einmal")
        ]

    def __str__(self) -> str:
        return f"{self.definition}: {self.value}"


MAX_TEXT = 1000
MAX_DIGITS = 15


def clean_scalar(field_type: str, value, choices: list | None = None, any_choice: bool = False):
    """Wert prüfen und in JSON-taugliche Form bringen. Leer = None.

    ``any_choice``: bei Auswahlfeldern auch gestrichene Werte annehmen (Datenübernahme:
    gespeicherte Werte bleiben stehen, auch wenn die Auswahl inzwischen kürzer ist)."""
    if value in (None, ""):
        return None
    if field_type == "text":
        text = str(value)
        if len(text) > MAX_TEXT:
            # Nicht still kürzen: der Rest ginge verloren
            raise ValidationError(
                gettext("Höchstens {MAX_TEXT} Zeichen (jetzt {x}).").format(
                    MAX_TEXT=MAX_TEXT, x=len(text)
                )
            )
        return text
    if field_type == "number":
        if isinstance(value, bool):
            raise ValidationError(gettext("Bitte eine Zahl angeben."))
        try:
            number = Decimal(str(value).strip().replace(",", "."))
        except InvalidOperation as exc:
            raise ValidationError(gettext("Bitte eine Zahl angeben.")) from exc
        if not number.is_finite():
            raise ValidationError(gettext("Bitte eine Zahl angeben."))
        number = number.normalize()
        # Als JSON-Zahl gespeichert: mehr als 15 Stellen gingen unbemerkt verloren
        if len(number.as_tuple().digits) > MAX_DIGITS:
            raise ValidationError(
                gettext("Höchstens {MAX_DIGITS} Stellen.").format(MAX_DIGITS=MAX_DIGITS)
            )
        # Auch sehr große oder sehr kleine Zahlen (z. B. 1e-400) passen nicht verlustfrei
        # in eine JSON-Zahl: höchstens 15 Stellen vor und 15 nach dem Komma
        if number and (number.adjusted() >= MAX_DIGITS or number.as_tuple().exponent < -MAX_DIGITS):
            raise ValidationError(
                gettext(
                    "Die Zahl ist zu groß oder zu klein (höchstens {MAX_DIGITS} Stellen vor "
                    "und {MAX_DIGITS2} nach dem Komma)."
                ).format(MAX_DIGITS=MAX_DIGITS, MAX_DIGITS2=MAX_DIGITS)
            )
        if number == number.to_integral_value():
            return int(number)
        return float(number)
    if field_type == "date":
        try:
            return datetime.date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValidationError(gettext("Bitte ein Datum angeben.")) from exc
    if field_type == "yearrange":
        return clean_year_range(value)
    if field_type == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in {"ja", "true", "1", "x"}:
            return True
        if str(value).lower() in {"nein", "false", "0"}:
            return False
        raise ValidationError(gettext("Bitte ja oder nein angeben."))
    if field_type == "choice":
        if any_choice and isinstance(value, str):
            return value
        if value not in (choices or []):
            raise ValidationError(gettext("„{value}“ ist kein erlaubter Wert.").format(value=value))
        return value
    raise ValidationError(gettext("Unbekannter Feldtyp."))


MIN_YEAR = 1000
MAX_YEAR = 2999
YEAR_RANGE = re.compile(r"^\s*(?:seit|ab)?\s*(\d{4})\s*(?:[-/–—]\s*(\d{2}|\d{4})?)?\s*$", re.I)


def clean_year_range(value) -> str:
    """Startjahr mit optionalem Endjahr, gespeichert als „JJJJ“ oder „JJJJ/JJJJ“.

    Angenommen werden z. B. „2010“, „2010/2015“, „2010-2015“, „2010–15“, „2024/25“
    (zweistelliges Endjahr wie im Schützenjahr) und Zahlen aus Excel (2010 oder 2010.0)."""
    if isinstance(value, bool):
        raise ValidationError(gettext("Bitte ein Jahr oder einen Zeitraum wie 2010/2015 angeben."))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    match = YEAR_RANGE.match(str(value))
    if not match:
        raise ValidationError(gettext("Bitte ein Jahr oder einen Zeitraum wie 2010/2015 angeben."))
    start = int(match.group(1))
    end_raw = match.group(2)
    end = None
    if end_raw:
        end = int(end_raw)
        if len(end_raw) == 2:
            # „2024/25“: Endjahr im selben Jahrhundert, sonst im nächsten („1999/00“)
            end += start - start % 100
            if end < start:
                end += 100
    for year in (start, end):
        if year is not None and not MIN_YEAR <= year <= MAX_YEAR:
            raise ValidationError(
                gettext("Jahre bitte zwischen {MIN_YEAR} und {MAX_YEAR}.").format(
                    MIN_YEAR=MIN_YEAR, MAX_YEAR=MAX_YEAR
                )
            )
    if end is not None and end < start:
        raise ValidationError(gettext("Das Endjahr liegt vor dem Startjahr."))
    return f"{start}" if end is None else f"{start}/{end}"


def format_year_range(value) -> str:
    """Anzeige: „2010/2015“, ohne Endjahr „seit 2010“."""
    text = str(value or "")
    if not text:
        return ""
    return text if "/" in text else f"seit {text}"


def clean_value(definition: FieldDefinition, value, any_choice: bool = False):
    if not definition.repeatable:
        return clean_scalar(definition.field_type, value, definition.choices, any_choice)
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError(gettext("Bitte eine Liste von Einträgen angeben."))
    rows = []
    for row in value:
        if not isinstance(row, dict):
            raise ValidationError(gettext("Ungültiger Eintrag."))
        clean_row = {}
        for sub in definition.subfields:
            clean_row[sub["key"]] = clean_scalar(
                sub["type"], row.get(sub["key"]), sub.get("choices"), any_choice
            )
        if any(v not in (None, "") for v in clean_row.values()):
            rows.append(clean_row)
    return rows
