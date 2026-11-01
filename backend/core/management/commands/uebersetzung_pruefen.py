"""Englischen Katalog aktualisieren und auf fehlende Übersetzungen prüfen.

    python manage.py uebersetzung_pruefen            Bericht (bis zur Abnahme nur Warnung)
    python manage.py uebersetzung_pruefen --streng   Fehler, wenn Übersetzungen fehlen
    python manage.py uebersetzung_pruefen --liste    fehlende Texte ausgeben

Holt neue Texte aus dem Code in ``locale/en/LC_MESSAGES/django.po`` (makemessages, braucht
GNU gettext) und zählt leere oder unsichere (``fuzzy``) Einträge.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

IGNORE = ["tests/*", "*/migrations/*", "staticfiles/*", "media/*", "private/*", "locale/*"]


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(line: str) -> str:
    text = line.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), text)


def entries(path: Path) -> list[dict]:
    """Einträge einer .po-Datei: msgctxt, msgid, msgid_plural, msgstr (Liste), fuzzy."""
    result: list[dict] = []
    current: dict | None = None
    field: str | None = None
    flags: set[str] = set()

    def finish():
        if current is not None and "msgid" in current:
            result.append(current)

    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#,"):
            flags |= {f.strip() for f in line[2:].split(",")}
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgctxt ") or (
            line.startswith("msgid ") and current and field != "msgctxt"
        ):
            finish()
            current, field = {"msgstr": [], "fuzzy": "fuzzy" in flags}, None
            flags = set()
        if current is None:
            current = {"msgstr": [], "fuzzy": "fuzzy" in flags}
            flags = set()
        keyword, _, rest = line.partition(" ")
        if keyword in ("msgctxt", "msgid", "msgid_plural"):
            field = keyword
            current[field] = _unquote(rest)
        elif keyword.startswith("msgstr"):
            field = "msgstr"
            current["msgstr"].append(_unquote(rest))
        elif line.startswith('"') and field:
            if field == "msgstr":
                current["msgstr"][-1] += _unquote(line)
            else:
                current[field] += _unquote(line)
    finish()
    return [e for e in result if e["msgid"]]  # ohne Kopf


def missing(path: Path) -> list[dict]:
    return [e for e in entries(path) if e["fuzzy"] or not all(e["msgstr"]) or not e["msgstr"]]


class Command(BaseCommand):
    help = "Englischen Katalog aktualisieren und auf fehlende Übersetzungen prüfen."

    def add_arguments(self, parser):
        parser.add_argument("--streng", action="store_true", help="Fehler bei Lücken")
        parser.add_argument("--liste", action="store_true", help="fehlende Texte ausgeben")

    def handle(self, *args, **options):
        call_command(
            "makemessages",
            locale=["en"],
            no_location=True,
            no_obsolete=True,
            ignore_patterns=IGNORE,
            verbosity=0,
        )
        path = Path(settings.LOCALE_PATHS[0]) / "en" / "LC_MESSAGES" / "django.po"
        # Zeitstempel weglassen, sonst ändert jeder Lauf die Datei
        text = path.read_text("utf-8")
        path.write_text(re.sub(r'"POT-Creation-Date: [^"]*"\n', "", text), "utf-8")
        all_entries = entries(path)
        gaps = missing(path)
        self.stdout.write(
            f"Übersetzung Backend: {len(all_entries)} Texte, "
            f"{len(all_entries) - len(gaps)} englisch, {len(gaps)} fehlen"
        )
        if options["liste"]:
            for e in gaps:
                ctx = f"[{e['msgctxt']}] " if e.get("msgctxt") else ""
                self.stdout.write(f"  fehlt: {ctx}{e['msgid']!r}")
        if options["streng"] and gaps:
            raise CommandError(f"{len(gaps)} Übersetzungen fehlen.")
