"""Bildverarbeitung und Regeln für Mitgliederfotos."""

from __future__ import annotations

import io
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

from .photo_models import MemberPhoto

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000  # Schutz vor „Bildbomben“
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
FULL_SIZE = 1200
THUMB_SIZE = 160


@dataclass
class Processed:
    full: bytes
    thumb: bytes
    width: int
    height: int


def _encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # Neu kodiert ohne EXIF/GPS oder andere Metadaten
    img.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    return buf.getvalue()


# Erlaubte Seitenverhältnisse (Breite/Höhe): Passbild 3:4 und quadratisch
ALLOWED_RATIOS = (3 / 4, 1.0)
RATIO_TOLERANCE = 0.02


def enforce_aspect(img: Image.Image) -> Image.Image:
    """Bilder mit anderem Seitenverhältnis mittig auf Passbild 3:4 zuschneiden.

    Der Editor im Browser liefert bereits 3:4 oder 1:1; das gilt so auch für
    Uploads, die ihn umgehen (z. B. direkt über die API).
    """
    ratio = img.width / img.height
    if any(abs(ratio - r) / r <= RATIO_TOLERANCE for r in ALLOWED_RATIOS):
        return img
    target = 3 / 4
    if ratio > target:  # zu breit: links und rechts kürzen
        width = round(img.height * target)
        left = (img.width - width) // 2
        return img.crop((left, 0, left + width, img.height))
    height = round(img.width / target)  # zu hoch: oben und unten kürzen
    top = (img.height - height) // 2
    return img.crop((0, top, img.width, top + height))


def process(upload) -> Processed:
    """Prüft das Bild, wendet die EXIF-Ausrichtung an, entfernt Metadaten, skaliert."""
    if upload.size > MAX_BYTES:
        raise ValidationError({"file": "Das Bild darf höchstens 10 MB groß sein."})
    try:
        upload.seek(0)
        probe = Image.open(upload)
        fmt = probe.format
        if fmt not in ALLOWED_FORMATS:
            raise ValidationError({"file": "Bitte ein JPEG-, PNG- oder WebP-Bild hochladen."})
        if probe.width * probe.height > MAX_PIXELS:
            raise ValidationError({"file": "Das Bild hat zu viele Pixel."})
        probe.verify()
        upload.seek(0)
        img = Image.open(upload)
        img.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError({"file": "Die Datei ist kein gültiges Bild."}) from exc
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")
    img = enforce_aspect(img)
    full = img.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE), Image.Resampling.LANCZOS)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    return Processed(_encode(full), _encode(thumb), full.width, full.height)


def clean_photo(content: bytes, size: int = FULL_SIZE) -> bytes:
    """Bild aus einer Importdatei prüfen und neu kodieren (wie beim Hochladen)."""
    from django.core.exceptions import ValidationError as DjangoValidationError

    invalid = "Ein Mitgliederfoto in der Datei ist kein gültiges Bild."
    try:
        probe = Image.open(io.BytesIO(content))
        if probe.format not in ALLOWED_FORMATS or probe.width * probe.height > MAX_PIXELS:
            raise DjangoValidationError(invalid)
        probe.verify()
        img = Image.open(io.BytesIO(content))
        img.load()
    except DjangoValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DjangoValidationError(
            "Ein Mitgliederfoto in der Datei ist kein gültiges Bild."
        ) from exc
    img = img.convert("RGB")
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    return _encode(img)


@transaction.atomic
def rotate(photo: MemberPhoto, degrees: int) -> None:
    """Gespeichertes Foto um 90°-Schritte drehen (positiv = gegen den Uhrzeigersinn)."""
    with photo.image.open("rb") as f:
        img = Image.open(f)
        img.load()
    img = img.rotate(degrees, expand=True)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    storage = photo.image.storage
    old_names = [photo.image.name, photo.thumbnail.name]
    photo.image.save("foto.jpg", ContentFile(_encode(img)), save=False)
    photo.thumbnail.save("vorschau.jpg", ContentFile(_encode(thumb)), save=False)
    photo.width, photo.height = img.width, img.height
    photo.save()

    # Alte Dateien erst nach dem Commit löschen; bei Fehler bleibt das alte Foto
    def _remove_old():
        for name in old_names:
            storage.delete(name)

    transaction.on_commit(_remove_old)


@transaction.atomic
def store(membership, processed: Processed, status: str, source: str, user=None) -> MemberPhoto:
    """Speichert ein Foto; ein vorhandenes mit gleichem Status wird ersetzt."""
    existing = MemberPhoto.objects.filter(membership=membership, status=status).first()
    if existing:
        existing.delete_files()
        existing.delete()
    photo = MemberPhoto(
        organization_id=membership.organization_id,
        membership=membership,
        status=status,
        source=source,
        width=processed.width,
        height=processed.height,
        uploaded_by=user if user and user.is_authenticated else None,
    )
    photo.image.save("foto.jpg", ContentFile(processed.full), save=False)
    photo.thumbnail.save("vorschau.jpg", ContentFile(processed.thumb), save=False)
    photo.save()
    return photo


@transaction.atomic
def approve(membership) -> MemberPhoto:
    pending = MemberPhoto.objects.filter(membership=membership, status="pending").first()
    if pending is None:
        raise ValidationError("Es wartet kein Foto auf Freigabe.")
    current = MemberPhoto.objects.filter(membership=membership, status="approved").first()
    if current:
        current.delete_files()
        current.delete()
    pending.status = MemberPhoto.Status.APPROVED
    pending.save()
    return pending


def remove(membership, status: str = "approved") -> bool:
    photo = MemberPhoto.objects.filter(membership=membership, status=status).first()
    if photo is None:
        return False
    photo.delete_files()
    photo.delete()
    return True


def remove_all(membership) -> None:
    """Für die Löschfrist: alle Fotos und Links einer Mitgliedschaft entfernen."""
    for photo in MemberPhoto.objects.filter(membership=membership):
        photo.delete_files()
        photo.delete()
    membership.photo_links.all().delete()
