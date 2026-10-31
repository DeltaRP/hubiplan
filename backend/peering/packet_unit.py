"""Paket „Stammdaten der Einheit“ (P1): beide Richtungen."""

from __future__ import annotations

import base64
import io

from django.core.files.base import ContentFile

from core.files import delete_on_commit

from .packets import BOTH, Packet, file_b64, register

FIELDS = (
    "name",
    "short_name",
    "name_gender",
    "name_genitive",
    "label",
    "label_plural",
    "label_gender",
    "label_genitive",
    "founding_year",
    "street",
    "postal_code",
    "city",
    "country",
    "website",
)
TEXT_LIMITS = {"name": 200, "short_name": 30, "street": 200, "city": 100, "country": 100}
LOGO_LIMIT = 1024 * 1024


def build(coupling, level):
    from organizations.serializers import effective_contact

    org = coupling.local_unit
    data = {f: getattr(org, f) for f in FIELDS}
    contact = effective_contact(org)
    data["contact_email"] = contact.get("email") or ""
    data["contact_phone"] = contact.get("phone") or ""
    data["logo"] = file_b64(org.logo, LOGO_LIMIT)
    return data


def _text(value, limit=200) -> str:
    return str(value or "")[:limit]


def apply(coupling, data):
    """Übernimmt die Stammdaten in den Platzhalter der fernen Einheit."""
    from organizations.models import Organization

    org = coupling.remote_unit
    if not data.get("level"):
        return  # Name bleibt (für die Anzeige der Kopplung nötig), sonst nichts Neues
    org.name = _text(data.get("name"), 200) or org.name
    for field in FIELDS[1:]:
        if field == "founding_year":
            year = data.get(field)
            org.founding_year = year if isinstance(year, int) and 800 <= year <= 2200 else None
            continue
        model_field = Organization._meta.get_field(field)
        value = _text(data.get(field), getattr(model_field, "max_length", None) or 200)
        if getattr(model_field, "choices", None) and value not in {
            c for c, _ in model_field.choices
        }:
            continue
        setattr(org, field, value)
    org.contact_email = _text(data.get("contact_email"), 254)
    org.contact_phone = _text(data.get("contact_phone"), 50)
    if data.get("website") and not str(data["website"]).startswith(("https://", "http://")):
        org.website = ""
    org.save()
    _logo(org, data.get("logo"))


def _logo(org, encoded):
    from PIL import Image, UnidentifiedImageError

    if not encoded:
        if org.logo:
            # Datei erst nach dem Commit löschen, Feld sofort leeren (Audit 31.10. D31-A01)
            delete_on_commit(org.logo)
            org.logo = ""
            org.save(update_fields=["logo"])
        return
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > LOGO_LIMIT:
            return
        with Image.open(io.BytesIO(raw)) as img:
            # Größe aus dem Dateikopf prüfen, bevor die Pixel entpackt werden (INF-S02)
            if img.width * img.height > 16_000_000:
                return
            img.load()
            # Wie beim Upload: immer als PNG neu schreiben (keine fremden Dateiinhalte)
            out = io.BytesIO()
            img.convert("RGBA").save(out, "PNG")
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        return
    delete_on_commit(org.logo)  # erst nach dem Commit (INF-F02)
    org.logo.save(f"verbund-{org.uuid}.png", ContentFile(out.getvalue()), save=True)


register(
    Packet(
        "unit",
        "Stammdaten der Einheit (Name, Bezeichnung, Logo, Anschrift, Kontakt)",
        BOTH,
        personal="nur die Kontaktdaten der Einheit",
        default="on",
        build=build,
        apply=apply,
        under_club=True,
    )
)
