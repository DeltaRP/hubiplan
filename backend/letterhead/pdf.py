"""Briefbogen für PDF-Briefe (Rechnungen, Mahnungen, Serienbriefe).

Zeichnet Kopf, Falz- und Lochmarken, Rücksendeangabe und Fußzeile mit denselben
Maßen wie die Word-Vorlage (``docx.FORMS``), damit Rechnung, Serienbrief und
Word-Brief einer Einheit gleich aussehen. Mehrere Briefe (auch verschiedener
Einheiten) passen in ein PDF: jeder Brief beginnt mit ``LetterDocument.start``.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    ActionFlowable,
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
)

from .data import LetterData
from .docx import (
    FORMS,
    HOLE_MARK,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    NO_WRAP,
    SERIF,
    footer_columns,
    footer_rows,
    load_picture,
)

GREY = colors.HexColor("#595959")
LIGHT = colors.HexColor("#808080")
FOOTER_LINE = 3.1  # mm je Zeile in der Fußzeile
FOOTER_BOTTOM = 10  # mm vom unteren Rand
LATER_TOP = 22  # mm: Textbeginn auf Folgeseiten
LATER_BOTTOM = 18  # mm: Textende auf Folgeseiten
TEXT_W = 210 - MARGIN_LEFT - MARGIN_RIGHT
INFO_X = 125  # mm vom linken Rand
INFO_LABEL_W = 24  # mm


def fonts(name: str) -> tuple[str, str]:
    """Standardschrift im PDF: serifenlose Schriften als Helvetica, sonst Times."""
    if name in SERIF:
        return "Times-Roman", "Times-Bold"
    return "Helvetica", "Helvetica-Bold"


def fit(c: rl_canvas.Canvas, text: str, font: str, size: float, width: float) -> float:
    while size > 5 and c.stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def _split_long(c: rl_canvas.Canvas, word: str, font: str, size: float, width: float) -> list[str]:
    """Zu lange Wörter (z. B. E-Mail-Adressen) zeichenweise umbrechen."""
    parts, current = [], ""
    for char in word:
        if current and c.stringWidth(current + char, font, size) > width:
            parts.append(current)
            current = ""
        current += char
    return [*parts, current] if current else parts


def wrap(c: rl_canvas.Canvas, text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, current = [], [], ""
    for word in text.split():
        words += _split_long(c, word, font, size, width)
    for word in words:
        test = f"{current} {word}".strip()
        if c.stringWidth(test, font, size) <= width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _y(c: rl_canvas.Canvas, top_mm: float) -> float:
    return c._pagesize[1] - top_mm * mm


# --- Teile der ersten Seite ---------------------------------------------------


def draw_head(c: rl_canvas.Canvas, data: LetterData) -> None:
    """Briefkopf: Logo, Name, Zusatzzeile und Linie in der Akzentfarbe."""
    regular, bold = fonts(data.font)
    form = FORMS[data.form]
    top = 10 if data.form == "b" else 7
    name_x, name_w = MARGIN_LEFT, TEXT_W
    logo = load_picture(data.logo, "logo") if data.logo else None
    if logo is not None:
        lw, lhgt = logo.fit(55, form["logo_h"])
        left = data.settings.logo_position == "left"
        lx = MARGIN_LEFT if left else 210 - MARGIN_RIGHT - lw
        c.drawImage(
            ImageReader(io.BytesIO(logo.data)),
            lx * mm,
            _y(c, top + lhgt),
            lw * mm,
            lhgt * mm,
            mask="auto",
        )
        name_w = TEXT_W - lw - 6
        if left:
            name_x = MARGIN_LEFT + lw + 6
    size = fit(c, data.name, bold, 16 if len(data.name) < 45 else 13, name_w * mm)
    c.setFillColor(colors.HexColor(data.primary))
    c.setFont(bold, size)
    c.drawString(name_x * mm, _y(c, top + 1) - size, data.name)
    line_y = _y(c, top + 1) - size - 2 * mm
    sub = " · ".join(p for p in (data.tagline, data.sub_line) if p)
    if sub:
        c.setFillColor(GREY)
        c.setFont(regular, 9)
        c.drawString(name_x * mm, _y(c, top + 1) - size - 11, sub)
        line_y -= 11
    c.setStrokeColor(colors.HexColor(data.accent))
    c.setLineWidth(0.75)
    c.line(name_x * mm, line_y, (name_x + name_w) * mm, line_y)


def draw_marks(c: rl_canvas.Canvas, data: LetterData) -> None:
    """Falz- und Lochmarken am linken Rand."""
    c.setStrokeColor(colors.HexColor("#A6A6A6"))
    c.setLineWidth(0.5)
    for mark in (*FORMS[data.form]["folds"], HOLE_MARK):
        c.line(4 * mm, _y(c, mark), (10 if mark != HOLE_MARK else 12) * mm, _y(c, mark))


def draw_return_line(c: rl_canvas.Canvas, data: LetterData) -> None:
    regular, _ = fonts(data.font)
    c.setFillColor(GREY)
    size = fit(c, data.return_line, regular, 6.5, 85 * mm)
    c.setFont(regular, size)
    c.drawString(20 * mm, _y(c, FORMS[data.form]["field_top"] + 3), data.return_line)


def footer_height(data: LetterData) -> float:
    """Höhe der Fußzeile der ersten Seite in mm (0 ohne Fußzeile)."""
    rows = footer_rows(data)
    return FOOTER_BOTTOM + rows * FOOTER_LINE + 2 if rows else 0


def draw_footer(c: rl_canvas.Canvas, data: LetterData) -> None:
    columns = footer_columns(data)
    if not columns:
        return
    regular, bold = fonts(data.font)
    col_w = TEXT_W / len(columns)
    base = 297 - footer_height(data) + 2
    c.setStrokeColor(colors.HexColor(data.accent))
    c.setLineWidth(0.75)
    c.line(MARGIN_LEFT * mm, _y(c, base - 2), (210 - MARGIN_RIGHT) * mm, _y(c, base - 2))
    for i, (heading, lines) in enumerate(columns):
        x = (MARGIN_LEFT + i * col_w) * mm
        c.setFillColor(colors.HexColor(data.primary))
        c.setFont(bold, 7)
        c.drawString(x, _y(c, base + 1), heading)
        c.setFillColor(colors.black)
        c.setFont(regular, 7)
        row = base + 1 + FOOTER_LINE
        for line in lines:
            for part in wrap(c, line, regular, 7, (col_w - 2) * mm):
                c.drawString(x, _y(c, row), part)
                row += FOOTER_LINE


def draw_info(c: rl_canvas.Canvas, data: LetterData, rows, top: float) -> float:
    """Informationsblock rechts neben dem Anschriftfeld; gibt das untere Ende in mm zurück."""
    regular, _ = fonts(data.font)
    row_y = top
    for row in rows:
        label, value = row[0], row[1]
        placeholder = len(row) > 2 and row[2]
        c.setFillColor(GREY)
        c.setFont(regular, 8)
        c.drawString(INFO_X * mm, _y(c, row_y), label)
        c.setFillColor(LIGHT if placeholder else colors.black)
        width = (210 - MARGIN_RIGHT - INFO_X - INFO_LABEL_W) * mm
        size = 9.0
        if label in NO_WRAP:
            # E-Mail und Web nicht umbrechen, sondern die Schrift verkleinern
            while size > 6 and c.stringWidth(value, regular, size) > width:
                size -= 0.5
        c.setFont(regular, size)
        parts = wrap(c, value, regular, size, width)
        for i, part in enumerate(parts or [""]):
            c.drawString((INFO_X + INFO_LABEL_W) * mm, _y(c, row_y + i * 3.8), part)
        row_y += 3.8 * max(len(parts), 1)
    return row_y


def draw_later_head(c: rl_canvas.Canvas, data: LetterData, page: int) -> None:
    """Kleiner Kopf auf Folgeseiten: Name links, Seitenzahl rechts."""
    regular, bold = fonts(data.font)
    c.setFillColor(colors.HexColor(data.primary))
    c.setFont(bold, 9)
    c.drawString(MARGIN_LEFT * mm, _y(c, 12), data.name)
    c.setFillColor(GREY)
    c.setFont(regular, 8)
    c.drawRightString((210 - MARGIN_RIGHT) * mm, _y(c, 12), f"Seite {page}")
    c.setStrokeColor(colors.HexColor(data.accent))
    c.setLineWidth(0.5)
    c.line(MARGIN_LEFT * mm, _y(c, 14), (210 - MARGIN_RIGHT) * mm, _y(c, 14))


# --- Briefe als Flowables -----------------------------------------------------


class AddressBlock(Flowable):
    """Anschriftfeld mit Empfänger und Informationsblock (erste Seite eines Briefs).

    Steht als erstes Element im Rahmen der ersten Seite, der genau an der
    Oberkante des Anschriftfelds beginnt.
    """

    def __init__(self, data: LetterData, recipient: list[str], info: list[tuple]):
        super().__init__()
        self.data = data
        self.recipient = [line for line in recipient if line.strip()]
        self.info = info

    def _bottom(self) -> float:
        form = FORMS[self.data.form]
        field_end = form["field_top"] + 45
        rows = sum(1 + len(str(v)) // 34 for _, v, *_ in self.info)
        info_end = form["info_top"] + 3 + rows * 3.8
        return max(field_end, info_end) + 8.5

    def wrap(self, avail_w, avail_h):
        self.height = (self._bottom() - FORMS[self.data.form]["field_top"]) * mm
        return avail_w, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        # In Seitenkoordinaten zeichnen, unabhängig von der Lage im Rahmen
        x0, y0 = c.absolutePosition(0, 0)
        c.translate(-x0, -y0)
        self._draw_absolute(c)
        c.restoreState()

    def _draw_absolute(self, c) -> None:
        data = self.data
        form = FORMS[data.form]
        regular, _ = fonts(data.font)
        draw_return_line(c, data)
        c.setFillColor(colors.black)
        c.setFont(regular, 11)
        first = form["field_top"] + form["note_zone"] + 4
        for i, line in enumerate(self.recipient[:6]):
            c.drawString(20 * mm, _y(c, first + i * 4.6), line[:60])
        draw_info(c, data, self.info, form["info_top"] + 3)


class _SetLetter(ActionFlowable):
    def __init__(self, data: LetterData):
        super().__init__()
        self.data = data

    def apply(self, doc):
        doc.next_letter = self.data


class LetterDocument(BaseDocTemplate):
    """PDF aus einem oder mehreren Briefen im Briefbogen ihrer Einheit."""

    def __init__(self, buf, letters: list[LetterData], **kw):
        self.letters = letters
        self.letter = letters[0] if letters else None
        self.next_letter = self.letter
        self.letter_page = 0
        bottom = max([footer_height(d) for d in letters] + [LATER_BOTTOM]) + 4
        top = min(FORMS[d.form]["field_top"] for d in letters) if letters else 45
        super().__init__(
            buf,
            pagesize=A4,
            leftMargin=MARGIN_LEFT * mm,
            rightMargin=MARGIN_RIGHT * mm,
            topMargin=LATER_TOP * mm,
            bottomMargin=LATER_BOTTOM * mm,
            **kw,
        )
        width = TEXT_W * mm
        first = Frame(
            MARGIN_LEFT * mm,
            bottom * mm,
            width,
            (297 - top - bottom) * mm,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="first",
        )
        later = Frame(
            MARGIN_LEFT * mm,
            LATER_BOTTOM * mm,
            width,
            (297 - LATER_TOP - LATER_BOTTOM) * mm,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="later",
        )
        self.addPageTemplates(
            [
                PageTemplate("first", [first], onPage=self._first, autoNextPageTemplate="later"),
                PageTemplate("later", [later], onPage=self._later),
            ]
        )

    def _first(self, c, doc):
        self.letter = self.next_letter
        self.letter_page = 1
        if self.letter is None:
            return
        c.saveState()
        draw_head(c, self.letter)
        draw_marks(c, self.letter)
        draw_footer(c, self.letter)
        c.restoreState()

    def _later(self, c, doc):
        self.letter_page += 1
        if self.letter is None:
            return
        c.saveState()
        draw_later_head(c, self.letter, self.letter_page)
        c.restoreState()

    @staticmethod
    def start(data: LetterData, recipient: list[str], info: list[tuple], first: bool) -> list:
        """Beginn eines Briefs: neue erste Seite mit Briefkopf, Anschrift und Infoblock."""
        parts: list = []
        if not first:
            parts += [_SetLetter(data), NextPageTemplate("first"), PageBreak()]
        parts.append(AddressBlock(data, recipient, info))
        return parts


def text_styles(data: LetterData | None):
    """Absatzformate in der Schrift des Briefbogens."""
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    regular, bold = fonts(data.font if data else "Arial")
    base = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=base["Normal"], fontName=regular, fontSize=10, leading=13)
    return {
        "normal": normal,
        "body": ParagraphStyle("b", parent=normal, fontSize=11, leading=15, spaceAfter=6),
        "small": ParagraphStyle("s", parent=normal, fontSize=8, leading=10),
        "title": ParagraphStyle(
            "t", parent=normal, fontName=bold, fontSize=12, leading=16, spaceAfter=4
        ),
        "right": ParagraphStyle("r", parent=normal, alignment=TA_RIGHT),
        "right_small": ParagraphStyle("rs", parent=normal, fontSize=8, alignment=TA_RIGHT),
    }


def esc(text: str) -> str:
    return escape(text or "")
