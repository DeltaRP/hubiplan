"""Vorschau der ersten Seite einer Briefvorlage als PDF.

Sie zeigt dieselben Angaben an denselben Stellen wie die Word-Datei (gleiche
Maße aus ``docx.FORMS``), damit niemand für jeden Versuch Word öffnen muss.
Schriften werden angenähert: serifenlose Schriften als Helvetica, Serifenschriften
als Times.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .data import LetterData
from .docx import FORMS, MARGIN_LEFT, load_picture
from .pdf import (
    GREY,
    LIGHT,
    draw_footer,
    draw_head,
    draw_info,
    draw_marks,
    draw_return_line,
    fonts,
)


def render(data: LetterData) -> bytes:
    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Vorschau Briefvorlage {data.unit.name}")
    regular, bold = fonts(data.font)
    form = FORMS[data.form]
    lh = data.settings

    def y(top_mm: float) -> float:
        return height - top_mm * mm

    draw_head(c, data)
    draw_marks(c, data)
    draw_return_line(c, data)
    field_top = form["field_top"]
    c.setFillColor(LIGHT)
    c.setFont(regular, 11)
    first = field_top + form["note_zone"] + 4
    c.drawString(20 * mm, y(first), "Empfänger: Name,")
    c.drawString(20 * mm, y(first + 5), "Straße und Hausnummer, PLZ Ort")

    # Informationsblock
    rows: list[tuple[str, str, bool]] = []
    sender = data.sender
    if sender is not None:
        rows.append(("Ansprechpartner", sender.name, False))
        if sender.function:
            rows.append(("Funktion", sender.function, False))
        rows += [(label, value, False) for label, value in sender.lines]
        if sender.reply_address:
            rows += [
                ("Antwort an" if i == 0 else "", line, False)
                for i, line in enumerate(sender.reply_address)
            ]
    else:
        rows += [("Ansprechpartner", "Name", True), ("Funktion", "Funktion", True)]
        rows += [(label, value, False) for label, value in data.contact if label != "Web"]
    rows.append(("", "", False))
    rows.append(("Datum", "Datum wählen", True))
    draw_info(c, data, rows, form["info_top"] + 3)

    # Betreff, Anrede, Text, Gruß
    pos = field_top + 45 + 8.5 + 4
    c.setFillColor(LIGHT)
    c.setFont(bold, 11)
    c.drawString(MARGIN_LEFT * mm, y(pos), "Betreff")
    pos += 12.5
    c.setFillColor(colors.black)
    c.setFont(regular, 11)
    c.drawString(MARGIN_LEFT * mm, y(pos), lh.salutation)
    pos += 8
    c.setStrokeColor(colors.HexColor("#E0E0E0"))
    c.setLineWidth(2)
    for i in range(4):
        end = 175 if i < 3 else 120
        c.line(MARGIN_LEFT * mm, y(pos + i * 5.5), (MARGIN_LEFT + end - 15) * mm, y(pos + i * 5.5))
    pos += 30
    c.setFillColor(colors.black)
    c.drawString(MARGIN_LEFT * mm, y(pos), lh.closing)
    pos += 4
    signature = None
    if sender is not None and sender.signature:
        signature = load_picture(sender.signature, "unterschrift")
    if signature is not None:
        sw, sh = signature.fit(60, 15)
        c.drawImage(
            ImageReader(io.BytesIO(signature.data)),
            MARGIN_LEFT * mm,
            y(pos + sh),
            sw * mm,
            sh * mm,
            mask="auto",
        )
    pos += 19
    if sender is not None:
        c.drawString(MARGIN_LEFT * mm, y(pos), sender.name)
        if sender.function:
            c.setFillColor(GREY)
            c.setFont(regular, 9)
            c.drawString(MARGIN_LEFT * mm, y(pos + 4.5), sender.function)
    else:
        c.setFillColor(LIGHT)
        c.drawString(MARGIN_LEFT * mm, y(pos), "Name")
        c.setFont(regular, 9)
        c.drawString(MARGIN_LEFT * mm, y(pos + 4.5), "Funktion")

    draw_footer(c, data)
    c.showPage()
    c.save()
    return buf.getvalue()
