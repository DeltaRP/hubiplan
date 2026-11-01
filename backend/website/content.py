"""Regeln für Texte und Bilder der Webseite."""

from __future__ import annotations

import io
import re

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

from .content_models import WebsiteImage, WebsiteRevision, WebsiteText

MAX_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 60_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
FULL_SIZE = 2000
SMALL_SIZE = 800
ORIGINAL_SIZE = 4000
MAX_REVISIONS = 50


def _open(upload) -> Image.Image:
    if upload.size > MAX_BYTES:
        raise ValidationError({"file": "Das Bild darf höchstens 15 MB groß sein."})
    try:
        upload.seek(0)
        probe = Image.open(upload)
        if probe.format not in ALLOWED_FORMATS:
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
    return ImageOps.exif_transpose(img)


def _encode(img: Image.Image, size: int) -> tuple[bytes, str, int, int]:
    """Verkleinert und schreibt neu (ohne EXIF/GPS). Transparenz bleibt als PNG."""
    img = img.copy()
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "png", img.width, img.height
    img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue(), "jpg", img.width, img.height


def process_image(upload) -> tuple[bytes, str, int, int, bytes, str]:
    """Prüft das Bild und liefert groß und klein, neu geschrieben ohne Metadaten."""
    img = _open(upload)
    full, ext, width, height = _encode(img, FULL_SIZE)
    small, ext_small, _, _ = _encode(img, SMALL_SIZE)
    return full, ext, width, height, small, ext_small


def clean_crop(value) -> dict:
    """Ausschnitt aus dem Browser prüfen: Prozentwerte, Drehung in 90°-Schritten."""
    if value in (None, "", {}):
        return {}
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValidationError({"crop": "Ungültiger Ausschnitt."}) from exc
    if not isinstance(value, dict):
        raise ValidationError({"crop": "Ungültiger Ausschnitt."})
    result = {}
    try:
        for key in ("x", "y", "width", "height"):
            number = float(value[key])
            if not 0 <= number <= 100:
                raise ValueError
            result[key] = round(number, 4)
        rotation = int(value.get("rotation") or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError({"crop": "Ungültiger Ausschnitt."}) from exc
    if rotation % 90 or not 0 <= rotation < 360:
        raise ValidationError({"crop": "Ungültige Drehung."})
    if result["width"] <= 0 or result["height"] <= 0:
        raise ValidationError({"crop": "Ungültiger Ausschnitt."})
    result["rotation"] = rotation
    aspect = value.get("aspect")
    if isinstance(aspect, str) and len(aspect) <= 12:
        result["aspect"] = aspect
    return result


def _save_files(image: WebsiteImage, upload, original=None) -> list:
    """Schreibt Bild (und ggf. Original) neu; liefert die alten Dateien zum Aufräumen."""
    old = []
    full, ext, width, height, small, ext_small = process_image(upload)
    for f in (image.file, image.small):
        if f.name:
            old.append(f.name)
    image.width, image.height = width, height
    image.file.save(f"bild.{ext}", ContentFile(full), save=False)
    image.small.save(f"bild-klein.{ext_small}", ContentFile(small), save=False)
    if original is not None:
        orig, ext_orig, _, _ = _encode(_open(original), ORIGINAL_SIZE)
        if image.original.name:
            old.append(image.original.name)
        image.original.save(f"original.{ext_orig}", ContentFile(orig), save=False)
    return old


def _remove_later(storage, names: list) -> None:
    def _remove():
        for name in names:
            storage.delete(name)

    if names:
        transaction.on_commit(_remove)


def store_image(
    website,
    upload,
    caption: str,
    alt_text: str,
    user,
    *,
    decorative: bool = False,
    original=None,
    crop: dict | None = None,
    department=None,
) -> WebsiteImage:
    """Neues Bild. ``upload`` ist der fertige Ausschnitt, ``original`` die ganze Datei
    (ohne: ``upload`` ist zugleich das Original)."""
    image = WebsiteImage(
        organization=website.organization,
        website=website,
        key=WebsiteImage.new_key(),
        caption=caption,
        alt_text=alt_text,
        decorative=decorative,
        department=department,
        crop=crop if original is not None and crop else {},
        uploaded_by=user,
        updated_by=user,
    )
    _save_files(image, upload, original if original is not None else upload)
    image.save()
    return image


def ensure_original(image: WebsiteImage) -> None:
    """Ältere Bilder ohne Original: das bisherige Bild wird zum Original."""
    if image.original.name or not image.file.name:
        return
    with image.file.open("rb") as f:
        data = f.read()
    ext = image.file.name.rsplit(".", 1)[-1]
    image.original.save(f"original.{ext}", ContentFile(data), save=False)
    image.crop = {}


def recrop_image(image: WebsiteImage, upload, crop: dict, user) -> WebsiteImage:
    """Neuer Ausschnitt aus dem Original (im Browser zugeschnitten)."""
    ensure_original(image)
    old = _save_files(image, upload)
    image.crop = crop
    image.version += 1
    image.updated_by = user
    image.save()
    _remove_later(image.file.storage, old)
    return image


def replace_image(image: WebsiteImage, upload, original, crop: dict, user) -> WebsiteImage:
    """Neue Datei für dasselbe Bild: Stellen, Texte und Kennung bleiben."""
    old = _save_files(image, upload, original if original is not None else upload)
    image.crop = crop if original is not None and crop else {}
    image.version += 1
    image.updated_by = user
    image.save()
    _remove_later(image.file.storage, old)
    return image


def copy_image(image: WebsiteImage, upload, crop: dict, user) -> WebsiteImage:
    """Zweites Bild aus demselben Original (z. B. anderes Format), Angaben übernommen."""
    if not image.original.name:
        ensure_original(image)
        image.save(update_fields=["original", "crop"])
    copy = WebsiteImage(
        organization=image.organization,
        website=image.website,
        key=WebsiteImage.new_key(),
        caption=image.caption,
        alt_text=image.alt_text,
        decorative=image.decorative,
        department=image.department,
        crop=crop,
        uploaded_by=user,
        updated_by=user,
    )
    _save_files(copy, upload)
    with image.original.open("rb") as f:
        data = f.read()
    ext = image.original.name.rsplit(".", 1)[-1]
    copy.original.save(f"original.{ext}", ContentFile(data), save=False)
    copy.save()
    return copy


def delete_image(image: WebsiteImage) -> None:
    files = [image.file, image.small, image.original]
    image.delete()

    def _remove():
        for f in files:
            if f.name:
                f.storage.delete(f.name)

    transaction.on_commit(_remove)


def _image_markdown(key: str) -> re.Pattern:
    """Bild im Text: ``![Alt](bild:<key>)``, optional mit Titel."""
    return re.compile(
        r"!\[(?:\\.|[^\]\\])*\]\(bild:" + re.escape(key) + r'(?:\s+"(?:\\.|[^"\\])*")?\)'
    )


def _uses(image: WebsiteImage, t, *, published: bool) -> list[str]:
    """Stellen eines Textes (Entwurf oder veröffentlicht), an denen das Bild steht."""
    marker = f"bild:{image.key}"
    image_id = t.published_image_id if published else t.image_id
    gallery = (t.published_gallery if published else t.gallery) or []
    body = t.published_body if published else t.body
    places = []
    if image_id == image.pk:
        places.append(
            "Bild der Untereinheit"
            if t.kind == WebsiteText.Kind.UNIT
            else "Bild oben auf der Seite"
        )
    if marker in body:
        places.append("im Text")
    if image.pk in gallery:
        places.append("Bilderkarussell")
    return places


def image_usage(image: WebsiteImage, texts=None) -> list[dict]:
    """Wo das Bild noch steht, je Text mit Stellen (Entwurf und/oder veröffentlicht)."""
    result = []
    if texts is None:
        texts = WebsiteText.objects.filter(website=image.website).select_related("department")
    for t in texts:
        draft = _uses(image, t, published=False)
        live = _uses(image, t, published=True) if t.is_published else []
        parts = []
        for place in dict.fromkeys(draft + live):
            if place not in draft:
                parts.append(f"{place} (nur noch in der veröffentlichten Fassung)")
            elif t.is_published and place not in live:
                parts.append(f"{place} (nur im Entwurf)")
            else:
                parts.append(place)
        if parts:
            result.append({"text": t.pk, "label": str(t), "places": parts})
    return result


def image_in_use(image: WebsiteImage) -> list[str]:
    """Wo das Bild noch steht, als Sätze für die Rückfrage beim Löschen."""
    return [f"{u['label']}: {', '.join(u['places'])}" for u in image_usage(image)]


def used_image_ids(website) -> set[int]:
    """Alle Bilder, die in einem Text stehen (Entwurf oder veröffentlicht)."""
    keys = dict(WebsiteImage.objects.filter(website=website).values_list("key", "pk"))
    used: set[int] = set()
    for t in WebsiteText.objects.filter(website=website):
        used.update(pk for pk in (t.image_id, t.published_image_id) if pk)
        used.update(t.gallery or [])
        used.update(t.published_gallery or [])
        for body in (t.body, t.published_body):
            for key in _IMAGE_KEY.findall(body or ""):
                if key in keys:
                    used.add(keys[key])
    return used


_IMAGE_KEY = re.compile(r"\]\(bild:([A-Za-z0-9_\-]{4,40})")
_IMAGE_IN_TEXT = re.compile(
    r'!\[((?:\\.|[^\]\\])*)\]\(bild:([A-Za-z0-9_\-]{4,40})(\s+"(?:\\.|[^"\\])*")?\)'
)


def _escape_alt(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")


def public_body(body: str, website) -> str:
    """Text für die Webseite: Bilder im Text bekommen den aktuellen Alternativtext und
    die Adresse der aktuellen Fassung (``bild:<key>-v<n>``), auch wenn sie im Text
    seit dem Einfügen anders stehen (Ralf 01.11.)."""
    if not body or "bild:" not in body:
        return body or ""
    keys = set(_IMAGE_KEY.findall(body))
    images = {i.key: i for i in WebsiteImage.objects.filter(website=website, key__in=keys)}

    def replace(match):
        image = images.get(match.group(2))
        if image is None:
            return match.group(0)
        if image.decorative:
            alt = ""
        else:
            alt = (
                _escape_alt(image.alt_text or image.caption)
                if (image.alt_text or image.caption)
                else match.group(1)
            )
        return f"![{alt}](bild:{image.public_key}{match.group(3) or ''})"

    return _IMAGE_IN_TEXT.sub(replace, body)


def remove_image_references(image: WebsiteImage, user) -> list[WebsiteText]:
    """Bild aus allen Texten nehmen (Entwurf, veröffentlicht, frühere Fassungen).

    Nur das Bild fällt weg; der übrige Inhalt bleibt, auch auf der Webseite.
    """
    pattern = _image_markdown(image.key)
    changed = []
    for t in WebsiteText.objects.filter(website=image.website):
        before = (
            t.image_id,
            t.published_image_id,
            t.gallery,
            t.published_gallery,
            t.body,
            t.published_body,
        )
        if t.image_id == image.pk:
            t.image = None
        if t.published_image_id == image.pk:
            t.published_image = None
        t.gallery = [pk for pk in (t.gallery or []) if pk != image.pk]
        t.published_gallery = [pk for pk in (t.published_gallery or []) if pk != image.pk]
        t.body = pattern.sub("", t.body)
        t.published_body = pattern.sub("", t.published_body)
        after = (
            t.image_id,
            t.published_image_id,
            t.gallery,
            t.published_gallery,
            t.body,
            t.published_body,
        )
        if before != after:
            t.updated_by = user
            t.save()
            changed.append(t)
    for r in WebsiteRevision.objects.filter(text__website=image.website):
        body = pattern.sub("", r.body)
        gallery = [pk for pk in (r.gallery or []) if pk != image.pk]
        if body != r.body or gallery != (r.gallery or []) or r.image_id == image.pk:
            r.body, r.gallery = body, gallery
            if r.image_id == image.pk:
                r.image = None
            r.save(update_fields=["body", "gallery", "image"])
    return changed


def image_in_revisions(image: WebsiteImage) -> list[str]:
    """Frühere Fassungen, die das Bild noch zeigen (beim Zurückholen fehlte es sonst)."""
    from django.db.models import Q

    marker = f"bild:{image.key}"
    revisions = (
        WebsiteRevision.objects.filter(text__website=image.website)
        .filter(Q(image=image) | Q(body__contains=marker) | Q(gallery__contains=[image.pk]))
        .select_related("text")
        .order_by("-published_at")
    )
    return [f"{r.text} vom {timezone.localtime(r.published_at):%d.%m.%Y}" for r in revisions]


def publish(text: WebsiteText, user) -> WebsiteRevision:
    now = timezone.now()
    text.published_title = text.title
    text.published_body = text.body
    text.published_image = text.image
    text.published_gallery = list(text.gallery or [])
    text.published_gallery_interval = text.gallery_interval
    text.published_gallery_random = text.gallery_random
    text.published_at = now
    text.updated_by = user
    text.save()
    revision = WebsiteRevision.objects.create(
        organization=text.organization,
        text=text,
        title=text.title,
        body=text.body,
        image=text.image,
        gallery=list(text.gallery or []),
        gallery_interval=text.gallery_interval,
        gallery_random=text.gallery_random,
        published_at=now,
        published_by=user,
    )
    old = list(text.revisions.values_list("pk", flat=True)[MAX_REVISIONS:])
    if old:
        WebsiteRevision.objects.filter(pk__in=old).delete()
    return revision


def unpublish(text: WebsiteText, user) -> None:
    text.published_title = ""
    text.published_body = ""
    text.published_image = None
    text.published_gallery = []
    text.published_at = None
    text.updated_by = user
    text.save()


def restore(text: WebsiteText, revision: WebsiteRevision, user) -> None:
    """Fassung in den Entwurf zurückholen (veröffentlicht wird erst danach)."""
    text.title = revision.title
    text.body = revision.body
    text.image = revision.image
    # Bilder, die es nicht mehr gibt, fallen weg
    existing = set(
        WebsiteImage.objects.filter(
            website=text.website, pk__in=revision.gallery or []
        ).values_list("pk", flat=True)
    )
    text.gallery = [pk for pk in (revision.gallery or []) if pk in existing]
    text.gallery_interval = revision.gallery_interval
    text.gallery_random = revision.gallery_random
    text.updated_by = user
    text.save()


def greeting(website) -> WebsiteText:
    text, _ = WebsiteText.objects.get_or_create(
        website=website,
        kind=WebsiteText.Kind.GREETING,
        defaults={"organization": website.organization, "title": "Willkommen"},
    )
    return text


# Links auf eigene Seiten: seite:<ziel> (die Webseite setzt die Adresse ein,
# siehe hubiplan-website seite/markdown.py)
_SECTION_TARGETS = [
    ("posts", "aktuelles", "Aktuelles"),
    ("events", "termine", "Termine"),
    ("board", "vorstand", "Vorstand"),
    ("units", "einheiten", None),
    ("honors", "majestaeten", None),
    ("history", "chronik", "Chronik"),
    ("offices", "aemter", "Ämter"),
    ("statutes", "dokumente", "Dokumente"),
    ("contact", "kontakt", "Kontakt"),
]


def link_targets(website) -> list[dict]:
    """Seiten der eigenen Webseite für den Link-Dialog des Editors."""
    from .public import SiteView

    site = SiteView(website)
    org = website.organization
    targets = [{"href": "seite:start", "label": "Startseite"}]
    for block, target, label in _SECTION_TARGETS:
        if not website.block_on(block):
            continue
        if block == "units":
            label = org.department_label_plural or "Untereinheiten"
        elif block == "honors":
            label = site.honors_label()
        targets.append({"href": f"seite:{target}", "label": label})
    for u in site.units:
        targets.append(
            {"href": f"seite:einheit/{site.unit_slugs[u.pk]}", "label": u.short_name or u.name}
        )
    pages = WebsiteText.objects.filter(website=website, kind=WebsiteText.Kind.PAGE).order_by(
        "menu_position", "title"
    )
    for p in pages:
        if p.slug == "geschichte":
            continue
        label = p.title or p.slug
        if not p.is_published:
            label += " (noch nicht veröffentlicht)"
        targets.append({"href": f"seite:seite/{p.slug}", "label": label})
    targets += [
        {"href": "seite:impressum", "label": "Impressum"},
        {"href": "seite:datenschutz", "label": "Datenschutz"},
    ]
    return targets
