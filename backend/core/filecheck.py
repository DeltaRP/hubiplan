"""Gemeinsame Prüfung hochgeladener und importierter Dateien.

Die Dateiart wird immer aus dem Inhalt bestimmt, nie aus Dateiname oder einer
mitgelieferten Angabe. Logos werden dekodiert und als PNG neu geschrieben, damit
unter ``/media`` nur echte Bilder liegen.
"""

from __future__ import annotations

import io

from django.core.exceptions import ValidationError
from PIL import Image, ImageChops, ImageDraw, ImageFilter, UnidentifiedImageError

MAX_LOGO_PIXELS = 25_000_000
LOGO_MAX_SIDE = 1024
LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}

# Dateianfang → Dateiart
MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# Diese Dateiarten darf der Browser direkt anzeigen; alles andere nur als Download.
INLINE_SAFE = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
}


def sniff(content: bytes) -> str | None:
    """Dateiart am Inhalt erkennen (PDF, JPEG, PNG, GIF, WebP, HEIC)."""
    head = content[:32]
    for magic, ctype in MAGIC:
        if head.startswith(magic):
            return ctype
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heif"):
        return "image/heic"
    return None


def clean_logo(content: bytes, *, remove_background: bool = False) -> bytes:
    """Prüft ein Logo und schreibt es als PNG neu (ohne Metadaten, max. 1024 px).

    Mit ``remove_background`` wird ein weißer Hintergrund durchsichtig.
    """
    # Pillows eigene Grenze (MAX_IMAGE_PIXELS) bleibt für alle Bilder im Prozess
    # wirksam; die Logo-Grenze darunter ist strenger (Audit 29.10. R-V01).
    try:
        probe = Image.open(io.BytesIO(content))
        if probe.format not in LOGO_FORMATS:
            raise ValidationError("Bitte PNG, JPG oder WebP hochladen.")
        if probe.width * probe.height > MAX_LOGO_PIXELS:
            raise ValidationError("Das Logo hat zu viele Pixel.")
        probe.verify()
        img = Image.open(io.BytesIO(content))
        img.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError("Die Datei ist kein gültiges Bild.") from exc
    img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P", "PA") else img.convert("RGB")
    img.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE), Image.Resampling.LANCZOS)
    if remove_background:
        img = remove_white_background(img)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# Ab diesem Abstand zu reinem Weiß gilt ein Pixel nicht mehr als Hintergrund
# (fängt JPEG-Rauschen ab). Im Saum werden Pixel bis EDGE_TOL nach Helligkeit
# teilweise durchsichtig, damit kein weißer Rand bleibt.
WHITE_TOL = 24
EDGE_TOL = 90


def remove_white_background(img: Image.Image) -> Image.Image:
    """Macht weißen Hintergrund durchsichtig, der vom Bildrand aus erreichbar ist.

    Weiße Flächen innerhalb des Wappens bleiben. Ist der Rand schon durchsichtig,
    bleibt das Bild unverändert. Nur Pillow, kein Fremddienst.
    """
    img = img.convert("RGBA")
    w, h = img.size
    alpha = img.getchannel("A")
    edge = [alpha.getpixel((x, y)) for x in range(w) for y in (0, h - 1)]
    edge += [alpha.getpixel((x, y)) for y in range(h) for x in (0, w - 1)]
    if min(edge) < 250:
        return img
    r, g, b, _ = img.split()
    light = ImageChops.darker(ImageChops.darker(r, g), b)  # kleinster Farbkanal
    white = light.point(lambda v: 255 if v >= 255 - WHITE_TOL else 0)
    # Mit weißem Rahmen füllen, damit alle Randstücke zusammenhängen
    padded = Image.new("L", (w + 2, h + 2), 255)
    padded.paste(white, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    bg = padded.crop((1, 1, w + 1, h + 1)).point(lambda v: 255 if v == 128 else 0)
    if not bg.getbbox():
        return img
    fringe = ImageChops.subtract(bg.filter(ImageFilter.MaxFilter(5)), bg)
    soft = light.point(lambda v: max(0, min(255, round((255 - v) * 255 / EDGE_TOL))))
    new_alpha = ImageChops.multiply(alpha, ImageChops.invert(bg))
    new_alpha = Image.composite(ImageChops.darker(new_alpha, soft), new_alpha, fringe)
    img.putalpha(new_alpha)
    return img


def inline_type(content_type: str | None) -> str | None:
    """Gespeicherte Dateiart, falls sie im Browser angezeigt werden darf."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    return ctype if ctype in INLINE_SAFE else None


class SafeFileMiddleware:
    """Ausgelieferte Dateien nie als aktive Seite auf der Anwendungsadresse.

    Dateiarten außerhalb von ``INLINE_SAFE`` kommen nur als Download; alles außer
    PDF bekommt zusätzlich eine CSP ohne Skripte (``sandbox``). PDF bleibt ohne
    ``sandbox``, weil Browser PDFs sonst nicht anzeigen.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import FileResponse

        response = self.get_response(request)
        if not isinstance(response, FileResponse):
            return response
        ctype = inline_type(response.get("Content-Type"))
        disposition = response.get("Content-Disposition", "")
        if ctype is None and not disposition.lower().startswith("attachment"):
            response["Content-Disposition"] = "attachment" + disposition[len("inline") :]
            if not disposition:
                response["Content-Disposition"] = "attachment"
        if ctype != "application/pdf":
            response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response
