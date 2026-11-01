"""Vorschaubild der Homepage einer Untereinheit (Ralf 31.10.).

HUBIplan holt das Bild **einmal**, wenn die Homepage eingetragen oder geändert wird:
die Startseite der Homepage, darin ``og:image`` (ersatzweise ``twitter:image``), dann
das Bild selbst. Gespeichert wird es wie ein Logo, neu geschrieben als JPEG. Ein im
Formular hochgeladenes eigenes Bild hat Vorrang und wird nie überschrieben.

Abgerufen wird nur über ``core.safehttp`` (nur https, keine internen Adressen, feste
Adresse gegen DNS-Rebinding). Weiterleitungen folgen wir selbst, höchstens vier, jede
wieder über ``safehttp``.
"""

from __future__ import annotations

import io
import logging
import urllib.parse
from html.parser import HTMLParser

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext
from PIL import Image, UnidentifiedImageError

from core import safehttp

log = logging.getLogger(__name__)

MAX_PAGE = 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
MAX_REDIRECTS = 4
TIMEOUT = 8
PREVIEW_MAX_SIDE = 1200
MAX_PIXELS = 40_000_000
FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
HEADERS = {"User-Agent": "HUBIplan-Vorschau/1.0", "Accept": "text/html,image/*;q=0.9"}

# Reihenfolge: das erste vorhandene gewinnt
META_KEYS = ("og:image:secure_url", "og:image", "og:image:url", "twitter:image")


class _MetaImage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        if key in META_KEYS and a.get("content") and key not in self.found:
            self.found[key] = a["content"].strip()


def find_image_url(html: str, base_url: str) -> str | None:
    """Adresse des Vorschaubilds aus der Seite (absolut, nur https)."""
    parser = _MetaImage()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 – kaputtes HTML: dann eben kein Bild
        return None
    for key in META_KEYS:
        if key in parser.found:
            url = urllib.parse.urljoin(base_url, parser.found[key])
            return _https(url)
    return None


def _https(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "http":
        parts = parts._replace(scheme="https")
    if parts.scheme != "https" or not parts.hostname:
        return None
    return urllib.parse.urlunsplit(parts)


def _get(url: str, max_body: int) -> tuple[str, safehttp.Response]:
    """GET mit eigener Weiterleitung; liefert die letzte Adresse und die Antwort."""
    for _ in range(MAX_REDIRECTS + 1):
        resp = safehttp.request("GET", url, headers=HEADERS, timeout=TIMEOUT, max_body=max_body)
        if resp.status in (301, 302, 303, 307, 308):
            location = {k.lower(): v for k, v in resp.headers.items()}.get("location")
            nxt = _https(urllib.parse.urljoin(url, location or ""))
            if not nxt:
                raise safehttp.SafeHTTPError(gettext("Weiterleitung ohne gültiges Ziel."))
            url = nxt
            continue
        if resp.status != 200:
            raise safehttp.SafeHTTPError(f"HTTP {resp.status}")
        if len(resp.body) > max_body:
            raise safehttp.SafeHTTPError(gettext("Antwort zu groß."))
        return url, resp
    raise safehttp.SafeHTTPError(gettext("Zu viele Weiterleitungen."))


def clean_preview(content: bytes) -> bytes:
    """Prüft das Bild und schreibt es als JPEG neu (ohne Metadaten, max. 1200 px)."""
    try:
        probe = Image.open(io.BytesIO(content))
        if probe.format not in FORMATS:
            raise ValidationError(gettext("Bitte PNG, JPG oder WebP hochladen."))
        if probe.width * probe.height > MAX_PIXELS:
            raise ValidationError(gettext("Das Bild hat zu viele Pixel."))
        probe.verify()
        img = Image.open(io.BytesIO(content))
        img.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(gettext("Die Datei ist kein gültiges Bild.")) from exc
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, (255, 255, 255))
        img.paste(rgba, mask=rgba.getchannel("A"))
    else:
        img = img.convert("RGB")
    img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


class NoPreview(Exception):
    """Kein Bild; die Meldung sagt der Oberfläche, warum."""


def fetch_preview(homepage: str) -> bytes:
    """Vorschaubild der Homepage als JPEG; sonst ``NoPreview`` mit Grund."""
    start = _https(homepage)
    if not start:
        raise NoPreview("Die Adresse der Homepage ist ungültig.")
    try:
        page_url, page = _get(start, MAX_PAGE)
    except safehttp.SafeHTTPError as exc:
        raise NoPreview(f"Die Homepage ist nicht erreichbar ({exc}).") from exc
    ctype = {k.lower(): v for k, v in page.headers.items()}.get("content-type", "")
    if "html" not in ctype.lower():
        raise NoPreview("Die Homepage liefert keine Webseite.")
    image_url = find_image_url(page.body.decode("utf-8", "replace"), page_url)
    if not image_url:
        raise NoPreview("Die Homepage bietet kein Vorschaubild an (og:image fehlt).")
    try:
        _, image = _get(image_url, MAX_IMAGE)
        return clean_preview(image.body)
    except (safehttp.SafeHTTPError, ValidationError) as exc:
        raise NoPreview("Das Vorschaubild der Homepage ließ sich nicht laden.") from exc


def refresh(unit) -> str:
    """Holt das Bild für die eingetragene Homepage, außer bei eigenem Bild.

    Merkt sich in ``website_image_for``, wofür versucht wurde, damit nur einmal je
    Adresse abgerufen wird. Liefert ``""`` bei Erfolg, sonst den Grund.
    """
    if unit.website_image_custom:
        return ""
    data, reason = None, ""
    website = unit.website
    if website:
        try:
            data = fetch_preview(website)
        except NoPreview as exc:
            reason = str(exc)
            log.info("Vorschaubild für %s nicht geholt: %s", website, reason)
    # Der Abruf dauert: Danach frisch und gesperrt lesen. Hat inzwischen jemand ein eigenes
    # Bild hochgeladen oder die Adresse geändert, gilt das Ergebnis nicht mehr
    # (Gesamtaudit 01.11., GA-F10).
    from django.db import transaction

    from core.files import delete_on_commit

    with transaction.atomic():
        current = type(unit).objects.select_for_update().filter(pk=unit.pk).first()
        if current is None or current.website_image_custom or current.website != website:
            return reason
        delete_on_commit(current.website_image)
        if data:
            current.website_image.save("vorschau.jpg", ContentFile(data), save=False)
        else:
            current.website_image = None
        current.website_image_for = website
        current.save(update_fields=["website_image", "website_image_for"])
    unit.website_image = current.website_image
    unit.website_image_for = website
    return reason


def needs_refresh(unit) -> bool:
    return not unit.website_image_custom and unit.website_image_for != unit.website


def schedule(unit) -> None:
    """Nach dem Speichern im Hintergrund holen (der Abruf kann einige Sekunden dauern)."""
    from django.db import transaction

    from .tasks import fetch_homepage_preview

    if needs_refresh(unit):
        pk = unit.pk
        transaction.on_commit(lambda: fetch_homepage_preview.delay(pk))
