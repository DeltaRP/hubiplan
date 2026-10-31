"""Kassenbericht als PDF für Kassenprüfer und Jahreshauptversammlung."""

from __future__ import annotations

import io
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table

from organizations.theme import effective_theme

from .models import YearClosing
from .services import _overview


def _euro(value) -> str:
    text = f"{Decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _styles():
    base = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=base["Normal"], fontSize=9, leading=12)
    return {
        "normal": normal,
        "small": ParagraphStyle("s", parent=normal, fontSize=8, leading=10, textColor=colors.grey),
        "title": ParagraphStyle("t", parent=normal, fontSize=15, leading=19, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=normal, fontSize=11, leading=14, spaceBefore=8),
        "right": ParagraphStyle("r", parent=normal, alignment=TA_RIGHT),
        "right_bold": ParagraphStyle(
            "rb", parent=normal, alignment=TA_RIGHT, fontName="Helvetica-Bold"
        ),
    }


def _table(rows, widths, primary, total_row=True):
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, primary),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
    if total_row:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, primary))
    return Table(rows, colWidths=widths, repeatRows=1, style=style, hAlign="LEFT")


def render(org, year: int) -> bytes:
    data = _overview(org, year)
    st = _styles()
    primary = colors.HexColor(effective_theme(org.ancestors())["primary"])
    closing = YearClosing.objects.filter(organization=org, year=year).first()
    story: list = [
        Paragraph(f"<b>Kassenbericht {escape(data['label'])}</b>", st["title"]),
        Paragraph(
            f"{escape(org.name)} · Geschäftsjahr {data['start_date']:%d.%m.%Y} bis "
            f"{data['end_date']:%d.%m.%Y}",
            st["normal"],
        ),
        Paragraph(
            (
                f"Abgeschlossen am {timezone.localtime(closing.closed_at):%d.%m.%Y}"
                if closing
                else f"Vorläufiger Stand vom {timezone.localdate():%d.%m.%Y} (nicht abgeschlossen)"
            )
            + f" · {data['booking_count']} Buchungen",
            st["small"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("<b>Bestände je Konto</b>", st["h2"]),
    ]
    r = st["right"]
    rows = [
        [
            Paragraph(f"<b>{h}</b>", st["normal"] if i == 0 else r)
            for i, h in enumerate(["Konto", "Anfang", "Einnahmen", "Ausgaben", "Umbuchung", "Ende"])
        ]
    ]
    for a in data["accounts"]:
        transfer = Decimal(a["transfer_in"]) - Decimal(a["transfer_out"])
        rows.append(
            [
                Paragraph(escape(a["name"]), st["normal"]),
                Paragraph(_euro(a["start"]), r),
                Paragraph(_euro(a["income"]), r),
                Paragraph(_euro(a["expense"]), r),
                Paragraph(_euro(transfer), r),
                Paragraph(_euro(a["end"]), r),
            ]
        )
    t = data["totals"]
    rb = st["right_bold"]
    rows.append(
        [
            Paragraph("<b>Summe</b>", st["normal"]),
            Paragraph(_euro(t["start"]), rb),
            Paragraph(_euro(t["income"]), rb),
            Paragraph(_euro(t["expense"]), rb),
            Paragraph(_euro(0), rb),
            Paragraph(_euro(t["end"]), rb),
        ]
    )
    story.append(_table(rows, [50 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm, 26 * mm], primary))

    story.append(Paragraph("<b>Einnahmen und Ausgaben nach Kategorie</b>", st["h2"]))
    rows = [
        [
            Paragraph("<b>Kategorie</b>", st["normal"]),
            Paragraph("<b>Einnahmen</b>", r),
            Paragraph("<b>Ausgaben</b>", r),
            Paragraph("<b>Saldo</b>", r),
        ]
    ]
    for c in data["categories"]:
        rows.append(
            [
                Paragraph(escape(c["name"]), st["normal"]),
                Paragraph(_euro(c["income"]), r),
                Paragraph(_euro(c["expense"]), r),
                Paragraph(_euro(Decimal(c["income"]) - Decimal(c["expense"])), r),
            ]
        )
    rows.append(
        [
            Paragraph("<b>Ergebnis</b>", st["normal"]),
            Paragraph(_euro(t["income"]), rb),
            Paragraph(_euro(t["expense"]), rb),
            Paragraph(_euro(t["result"]), rb),
        ]
    )
    story.append(_table(rows, [80 * mm, 30 * mm, 30 * mm, 32 * mm], primary))

    if data["tax_areas_enabled"] and data["tax_areas"]:
        story.append(Paragraph("<b>Nach steuerlichem Bereich</b>", st["h2"]))
        rows = [
            [
                Paragraph("<b>Bereich</b>", st["normal"]),
                Paragraph("<b>Einnahmen</b>", r),
                Paragraph("<b>Ausgaben</b>", r),
                Paragraph("<b>Saldo</b>", r),
            ]
        ]
        for a in data["tax_areas"]:
            rows.append(
                [
                    Paragraph(escape(a["label"]), st["normal"]),
                    Paragraph(_euro(a["income"]), r),
                    Paragraph(_euro(a["expense"]), r),
                    Paragraph(_euro(Decimal(a["income"]) - Decimal(a["expense"])), r),
                ]
            )
        story.append(_table(rows, [80 * mm, 30 * mm, 30 * mm, 32 * mm], primary, total_row=False))

    signatures = Table(
        [
            ["", "", ""],
            ["Kassierer/in", "Kassenprüfer/in", "Kassenprüfer/in"],
        ],
        colWidths=[56 * mm, 56 * mm, 56 * mm],
        rowHeights=[16 * mm, None],
        style=[
            ("LINEABOVE", (0, 1), (0, 1), 0.5, colors.black),
            ("LINEABOVE", (1, 1), (1, 1), 0.5, colors.black),
            ("LINEABOVE", (2, 1), (2, 1), 0.5, colors.black),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ],
        hAlign="LEFT",
    )
    story.append(Spacer(1, 10 * mm))
    story.append(
        KeepTogether(
            [
                Paragraph(
                    "Die Kasse wurde geprüft. Bestände und Buchungen stimmen mit den Belegen "
                    "überein.",
                    st["normal"],
                ),
                Paragraph("Ort, Datum: ______________________________", st["normal"]),
                signatures,
            ]
        )
    )

    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(20 * mm, 10 * mm, f"{org.name} · Kassenbericht {data['label']}")
        canvas.drawRightString(190 * mm, 10 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Kassenbericht {data['label']}",
        author=org.name,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
