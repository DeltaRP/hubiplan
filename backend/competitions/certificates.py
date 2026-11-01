"""Urkunden und Startkarten (Wettbewerbe Schritt 6, Konzept Abschnitt 11).

- Urkunden je Platzierten mit Vorlage (``CertificateTemplate``): Text mit Platzhaltern,
  Hintergrundbild, Wappen, Unterschriftszeilen; auf Wunsch die hinterlegte Unterschrift
  dessen, der die Urkunden erzeugt (nur seine eigene). Seriendruck für alle Platzierten.
- Startkarten: vier Karten je A4-Seite (Name, Untereinheit, Startnummer, je Einzelwertung
  Kästchen für die Schüsse) oder Aufkleber 70 × 37 mm (3 × 8 je Seite) für vorgedruckte
  Karten.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from reportlab.graphics import renderPDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from organizations.theme import effective_theme

from . import services
from .models import (
    DEFAULT_CERTIFICATE_TEXT,
    AwardGrant,
    CertificateTemplate,
    Competition,
    Scoring,
    Starter,
)

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
PLACEHOLDERS = {
    "name": "Name des Schützen, der Untereinheit oder Mannschaft",
    "einheit": "Untereinheit (bei Einzelwertung), sonst leer",
    "platz": "Platz (Zahl)",
    "wertung": "Name der Wertung",
    "wert": "Ergebnis, z. B. 28",
    "mit_wert": "„ mit 28“ (leer ohne Ergebnis)",
    "wettbewerb": "Titel des Wettbewerbs",
    "datum": "Datum des Wettbewerbs",
    "jahr": "Jahr",
    "ort": "Ort des Wettbewerbs",
    "verein": "Name des Vereins",
    "titel": "vergebener Titel, z. B. „Vereinsmeister 2027“",
    "preis": "Preis bzw. Pfand (Vogelschießen)",
}


@dataclass
class Recipient:
    values: dict

    @property
    def key(self) -> tuple:
        return (self.values.get("wertung", ""), self.values.get("platz") or 0)


def _base_values(comp: Competition) -> dict:
    return {
        "wettbewerb": comp.title,
        "datum": f"{comp.date:%d.%m.%Y}",
        "jahr": str(comp.date.year),
        "ort": comp.location,
        "verein": comp.organization.name,
    }


def recipients(
    comp: Competition, *, up_to: int = 3, scoring: int | None = None, starter: int | None = None
) -> list[Recipient]:
    """Alle Platzierten bis Platz ``up_to`` (je Wertung), beim Vogelschießen alle, die ein
    Pfand errungen haben. ``starter``: nur Urkunden dieses Starters."""
    base = _base_values(comp)
    titles: dict[tuple, str] = {}
    for g in AwardGrant.objects.filter(competition=comp).exclude(title=""):
        titles.setdefault((g.scoring_name, g.place, g.starter_id, g.unit_id), g.full_title)

    def title_for(sc_name, place, starter_id, unit_id):
        return titles.get((sc_name, place, starter_id, unit_id), "")

    out: list[Recipient] = []
    if comp.form == Competition.Form.BIRD:
        for p in comp.prizes.select_related("winner__unit").order_by("sort_order", "pk"):
            if not p.fallen or (starter and p.winner_id != starter):
                continue
            name = p.winner.name if p.winner_id else p.winner_name
            unit = p.winner.unit.name if p.winner_id and p.winner.unit_id else ""
            out.append(
                Recipient(
                    {
                        **base,
                        "name": name,
                        "einheit": unit,
                        "preis": p.name,
                        "wertung": p.name,
                        "platz": "",
                        "wert": "",
                        "mit_wert": "",
                        "titel": p.award or "",
                    }
                )
            )
        return out
    data = services.standings(comp)
    for s in data.get("scorings", []):
        if scoring and s["scoring"] != scoring:
            continue
        team = s["kind"] in (Scoring.Kind.UNIT, Scoring.Kind.TEAM)
        for r in s["rows"]:
            place = r.get("place")
            if place is None or place > up_to or r.get("out_of_competition"):
                continue
            if starter and r.get("starter") != starter:
                continue
            value = r.get("value_text", "")
            out.append(
                Recipient(
                    {
                        **base,
                        "name": r.get("name", ""),
                        "einheit": "" if team else r.get("unit_name", ""),
                        "platz": str(place),
                        "wertung": s["name"],
                        "wert": value,
                        "mit_wert": f" mit {value}" if value else "",
                        "titel": title_for(
                            s["name"],
                            place,
                            None if team else r.get("starter"),
                            r.get("unit") if team else None,
                        ),
                        "preis": "",
                    }
                )
            )
    return out


def render_lines(text: str, values: dict) -> list[tuple[str, bool]]:
    """Text mit Platzhaltern → Zeilen (Text, hervorgehoben). Zeilen, in denen Platzhalter
    stehen, die alle leer sind, fallen weg; unbekannte Platzhalter bleiben stehen."""
    out = []
    for raw in (text or "").splitlines():
        big = raw.startswith("# ")
        line = raw[2:] if big else raw
        names = PLACEHOLDER.findall(line)
        known = [n for n in names if n in values]
        if known and not any(str(values.get(n) or "").strip() for n in known):
            continue
        filled = PLACEHOLDER.sub(
            lambda m: str(values.get(m.group(1), m.group(0)) or ""), line
        ).strip()
        if filled or not names:
            out.append((filled, big))
    while out and not out[-1][0]:
        out.pop()
    return out


def _image(file_field) -> ImageReader | None:
    if not file_field:
        return None
    try:
        with file_field.open("rb") as fh:
            return ImageReader(io.BytesIO(fh.read()))
    except (OSError, ValueError):
        return None


def _logo(org) -> ImageReader | None:
    from letterhead.data import logo_path

    path = logo_path(org)
    if not path:
        return None
    try:
        return ImageReader(path)
    except (OSError, ValueError):
        return None


def _fit(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> float:
    while size > 8 and c.stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def certificates_pdf(
    comp: Competition,
    template: CertificateTemplate | None,
    items: list[Recipient],
    *,
    signature: dict | None = None,
) -> bytes:
    """Eine Seite je Urkunde."""
    from finance import signature as sig

    org = comp.organization
    text = template.text if template else DEFAULT_CERTIFICATE_TEXT
    heading = template.heading if template else "Urkunde"
    size = landscape(A4) if template and template.landscape else A4
    width, height = size
    primary = colors.HexColor(effective_theme(org.ancestors())["primary"])
    background = _image(template.background) if template else None
    logo = _logo(org) if (template is None or template.show_logo) else None
    signers = [s for s in (template.signers if template else []) or [] if isinstance(s, dict)][:2]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    c.setTitle(f"Urkunden {comp.title}")
    c.setAuthor(org.name)
    margin = 20 * mm
    usable = width - 2 * margin
    for item in items:
        if background is not None:
            c.drawImage(background, 0, 0, width, height, preserveAspectRatio=False, mask="auto")
        y = height - margin
        if logo is not None:
            lw = 32 * mm
            c.drawImage(
                logo, (width - lw) / 2, y - lw, lw, lw, preserveAspectRatio=True, mask="auto"
            )
            y -= lw + 8 * mm
        else:
            y -= 12 * mm
        if heading:
            c.setFillColor(primary)
            fs = _fit(c, heading, "Helvetica-Bold", 40, usable)
            c.setFont("Helvetica-Bold", fs)
            c.drawCentredString(width / 2, y - fs, heading)
            y -= fs + 14 * mm
        c.setFillColor(colors.black)
        lines = render_lines(text, item.values)
        for line, big in lines:
            font = "Helvetica-Bold" if big else "Helvetica"
            fs = _fit(c, line, font, 26 if big else 14, usable)
            c.setFont(font, fs)
            c.drawCentredString(width / 2, y - fs, line)
            y -= fs * (1.6 if big else 1.5)
        # Ort, Datum und Unterschriften unten
        bottom = margin + 12 * mm
        place = (template.place_line if template else "") or comp.location
        c.setFont("Helvetica", 10)
        when = f"{comp.date:%d.%m.%Y}"
        c.drawString(margin, bottom + 30 * mm, f"{place}, {when}" if place else when)
        slot_w = 65 * mm
        for i, s in enumerate(signers):
            # eine Unterschrift rechts, zwei links und rechts
            right = len(signers) == 1 or i == 1
            x = width - margin - slot_w if right else margin
            if i == 0 and signature:
                d = sig.drawing(signature, slot_w, 18 * mm)
                renderPDF.draw(d, c, x, bottom + 2 * mm)
            c.setStrokeColor(colors.grey)
            c.line(x, bottom, x + slot_w, bottom)
            c.setFont("Helvetica", 10)
            c.drawCentredString(x + slot_w / 2, bottom - 5 * mm, str(s.get("name", ""))[:80])
            c.setFont("Helvetica", 8)
            c.drawCentredString(x + slot_w / 2, bottom - 9 * mm, str(s.get("function", ""))[:80])
        c.showPage()
    if not items:
        c.setFont("Helvetica", 12)
        c.drawString(margin, height - margin, "Keine Platzierten für Urkunden.")
        c.showPage()
    c.save()
    return buf.getvalue()


# --- Startkarten ---


def _starters(comp: Competition, order: str) -> list[Starter]:
    qs = list(
        Starter.objects.filter(competition=comp)
        .exclude(presence="zurueckgezogen")
        .select_related("unit")
    )

    def number_key(s):
        n = s.number or ""
        return (0, int(n)) if n.isdigit() else (1, n or "~")

    if order == "einheit":
        qs.sort(key=lambda s: ((s.unit.name if s.unit_id else "~"), s.name))
    elif order == "startnummer":
        qs.sort(key=lambda s: (number_key(s), s.name))
    else:
        qs.sort(key=lambda s: s.name)
    return qs


def start_cards_pdf(comp: Competition, *, order: str = "name", labels: bool = False) -> bytes:
    """Startkarten (4 je A4) oder Aufkleber (3 × 8 je A4, 70 × 37 mm)."""
    org = comp.organization
    starters = _starters(comp, order)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Startkarten {comp.title}")
    c.setAuthor(org.name)
    width, height = A4
    if labels:
        cols, rows = 3, 8
        cw, ch = 70 * mm, 37 * mm
        top = (height - rows * ch) / 2
        per_page = cols * rows
        for i, s in enumerate(starters):
            if i and i % per_page == 0:
                c.showPage()
            n = i % per_page
            x = (n % cols) * cw
            y = height - top - (n // cols + 1) * ch
            pad = 4 * mm
            c.setFont("Helvetica", 7)
            c.drawString(x + pad, y + ch - pad - 6, comp.title[:48])
            c.setFont(
                "Helvetica-Bold", _fit(c, s.name, "Helvetica-Bold", 13, cw - 2 * pad - 14 * mm)
            )
            c.drawString(x + pad, y + ch / 2 - 2, s.name)
            c.setFont("Helvetica", 8)
            info = s.unit.name if s.unit_id else (s.club or "")
            c.drawString(x + pad, y + pad + 2, info[:40])
            if s.number:
                c.setFont("Helvetica-Bold", 16)
                c.drawRightString(x + cw - pad, y + ch / 2 - 4, s.number)
        c.showPage()
        c.save()
        return buf.getvalue()
    individual = list(
        comp.scorings.filter(kind=Scoring.Kind.INDIVIDUAL).order_by("sort_order", "pk")
    )
    primary = colors.HexColor(effective_theme(org.ancestors())["primary"])
    cw, ch = width / 2, height / 2
    pad = 8 * mm
    for i, s in enumerate(starters):
        if i and i % 4 == 0:
            c.showPage()
        n = i % 4
        x = (n % 2) * cw
        y = height - (n // 2 + 1) * ch
        # Schnittlinien
        c.setStrokeColor(colors.lightgrey)
        c.setDash(2, 2)
        c.rect(x, y, cw, ch)
        c.setDash()
        top = y + ch - pad
        c.setFillColor(primary)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + pad, top - 9, org.name[:60])
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawString(x + pad, top - 21, f"{comp.title[:50]} · {comp.date:%d.%m.%Y}")
        c.setFont("Helvetica-Bold", _fit(c, s.name, "Helvetica-Bold", 18, cw - 2 * pad - 25 * mm))
        c.drawString(x + pad, top - 46, s.name)
        c.setFont("Helvetica", 10)
        c.drawString(x + pad, top - 60, (s.unit.name if s.unit_id else s.club or "")[:50])
        # Startnummer im Kasten rechts oben
        box = 22 * mm
        c.rect(x + cw - pad - box, top - box, box, box)
        c.setFont("Helvetica", 6)
        c.drawString(x + cw - pad - box + 2, top - 7, "Startnummer")
        if s.number:
            c.setFont("Helvetica-Bold", 20)
            c.drawCentredString(x + cw - pad - box / 2, top - box + 6 * mm, s.number)
        # Je Einzelwertung Kästchen für die Schüsse und die Summe
        yy = top - 80
        for sc in individual[:3]:
            shots = min(sc.shots or 5, 10)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x + pad, yy, sc.name[:40])
            yy -= 4 * mm
            bw = min(11 * mm, (cw - 2 * pad - 18 * mm) / shots)
            c.setFont("Helvetica", 6)
            for k in range(shots):
                bx = x + pad + k * bw
                c.rect(bx, yy - 9 * mm, bw, 9 * mm)
                c.drawString(bx + 1, yy - 2.2 * mm, str(k + 1))
            sx = x + pad + shots * bw + 3 * mm
            c.setLineWidth(1.2)
            c.rect(sx, yy - 9 * mm, 15 * mm, 9 * mm)
            c.setLineWidth(1)
            c.drawString(sx + 1, yy - 2.2 * mm, "Summe")
            yy -= 15 * mm
        c.setFont("Helvetica", 7)
        c.line(x + pad, y + pad + 4 * mm, x + pad + 50 * mm, y + pad + 4 * mm)
        c.drawString(x + pad, y + pad, "Aufsicht")
    if not starters:
        c.setFont("Helvetica", 12)
        c.drawString(20 * mm, height - 20 * mm, "Noch keine Starter.")
    c.showPage()
    c.save()
    return buf.getvalue()
