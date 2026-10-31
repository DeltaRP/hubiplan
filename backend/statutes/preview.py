"""Vorschaubild der ersten Seite einer Satzung (für die Webseite).

Gerendert mit PDFium (pypdfium2) und im Cache gehalten: Eine Fassung ändert
sich nach dem Hochladen nicht, neue Fassungen bekommen einen neuen Schlüssel.
"""

from __future__ import annotations

import io
import logging

from django.core.cache import cache

from .models import StatuteVersion

log = logging.getLogger(__name__)

WIDTH = 480  # Pixel; reicht für eine Kachel auch auf hochauflösenden Bildschirmen
# Obergrenze der Höhe: Ein extrem schmales, hohes Seitenformat darf nicht riesige Bilder
# erzeugen (Gesamtaudit 30.10., B-V02). A4 hochkant braucht 679 Pixel.
MAX_HEIGHT = 1200
MAX_BYTES = 20 * 1024 * 1024


def first_page_png(version: StatuteVersion) -> bytes | None:
    """PNG der ersten Seite oder None, wenn die Datei sich nicht lesen lässt."""
    key = f"statute-preview:{version.pk}:{version.size}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    # Nur ein Prozess rendert dieselbe Fassung gleichzeitig; die anderen zeigen solange
    # keine Vorschau, statt dieselbe Arbeit noch einmal zu machen.
    if not cache.add(f"{key}:rendering", 1, 60):
        return None
    png = b""
    try:
        import pypdfium2 as pdfium

        with version.file.open("rb") as f:
            data = f.read(MAX_BYTES + 1)
        if len(data) <= MAX_BYTES:
            pdf = pdfium.PdfDocument(data)
            try:
                page = pdf[0]
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("Seite ohne Größe")
                scale = min(WIDTH / width, MAX_HEIGHT / height)
                image = page.render(scale=scale).to_pil()
                out = io.BytesIO()
                image.convert("RGB").save(out, "PNG", optimize=True)
                png = out.getvalue()
            finally:
                pdf.close()
    except Exception:  # noqa: BLE001 - kaputte PDF: einfach ohne Vorschau
        log.warning("Satzungsvorschau für Fassung %s nicht möglich", version.pk, exc_info=True)
    # Leeres Ergebnis kurz merken, damit eine kaputte Datei nicht ständig gerendert wird
    cache.set(key, png, None if png else 3600)
    cache.delete(f"{key}:rendering")
    return png or None
