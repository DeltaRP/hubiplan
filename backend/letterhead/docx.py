"""Word-Briefvorlage (.dotx/.docx) nach DIN 5008 aus den Daten einer Einheit.

Die Datei wird ohne Zusatzbibliothek als OOXML-Paket zusammengesetzt. Alle
Positionen (Anschriftfeld, Informationsblock, Falzmarken) sind fest in mm
angegeben; Kopf und Logo stehen in positionierten Rahmen, damit sie den Text
nicht verschieben. Die Datei enthält keine Makros, keine Verknüpfungen nach außen
und keine HUBIplan-Kennungen.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.pdfbase.pdfmetrics import stringWidth

from organizations.theme import SURFACE, contrast

from .data import LetterData

# Maße
PAGE_W, PAGE_H = 11906, 16838  # A4 in twips
TWIPS_PER_MM = 1440 / 25.4
EMU_PER_MM = 36000

MARGIN_LEFT = 25
MARGIN_RIGHT = 20
MARGIN_TOP = 25
MARGIN_BOTTOM = 25

# DIN 5008: Anschriftfeld (oben, Höhe Zusatz- und Vermerkzone), Falzmarken
FORMS = {
    "a": {"field_top": 27, "note_zone": 12.7, "info_top": 32, "folds": (87, 192), "logo_h": 15},
    "b": {"field_top": 45, "note_zone": 17.7, "info_top": 50, "folds": (105, 210), "logo_h": 25},
}
HOLE_MARK = 148.5

CT_MAIN = {
    "dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
}
MIME = {
    "dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ROOT_ATTRS = f'xmlns:w="{NS_W}" xmlns:r="{NS_R}" xmlns:wp="{NS_WP}" xmlns:a="{NS_A}"'

_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
GREY = "595959"


def mm(value: float) -> int:
    return round(value * TWIPS_PER_MM)


def esc(text: str) -> str:
    return escape(_INVALID.sub("", str(text or "")), {'"': "&quot;"})


def hexcolor(value: str) -> str:
    return (value or "#000000").lstrip("#").upper()


# --- Bausteine ---


def rpr(
    *,
    bold: bool = False,
    size: float | None = None,
    color: str | None = None,
    style: str | None = None,
    underline: bool = False,
) -> str:
    parts = []
    if style:
        parts.append(f'<w:rStyle w:val="{style}"/>')
    if bold:
        parts.append("<w:b/><w:bCs/>")
    if color:
        parts.append(f'<w:color w:val="{color}"/>')
    if size:
        half = round(size * 2)
        parts.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>')
    if underline:
        parts.append('<w:u w:val="single"/>')
    return f"<w:rPr>{''.join(parts)}</w:rPr>" if parts else ""


INFO_W = 70  # mm: Breite des Informationsblocks in der Word-Vorlage
SERIF = {"Cambria", "Georgia", "Times New Roman"}
# Diese Angaben stehen im Informationsblock immer in einer Zeile (Ralf: E-Mail nicht umbrechen)
NO_WRAP = {"E-Mail", "Web"}
INFO_SIZE = 9.0  # pt
INFO_MIN_SIZE = 6.0  # pt


def single_line_size(
    text: str, font: str, width_mm: float, size: float = INFO_SIZE, minimum: float = INFO_MIN_SIZE
) -> float:
    """Größte Schrift (in 0,5-pt-Schritten), mit der der Text in eine Zeile passt.

    Gemessen mit Helvetica bzw. Times, die Arial bzw. Times New Roman entsprechen;
    5 % Reserve, weil Word mit der echten Schrift etwas anders misst."""
    face = "Times-Roman" if font in SERIF else "Helvetica"
    limit = width_mm / 25.4 * 72 * 0.95
    while size > minimum and stringWidth(text, face, size) > limit:
        size -= 0.5
    return size


def run(text: str, **fmt) -> str:
    props = rpr(**fmt)
    lines = str(text or "").split("\n")
    inner = "<w:br/>".join(f'<w:t xml:space="preserve">{esc(line)}</w:t>' for line in lines)
    return f"<w:r>{props}{inner}</w:r>"


def tab_run(**fmt) -> str:
    return f"<w:r>{rpr(**fmt)}<w:tab/></w:r>"


def ppr(
    *,
    style: str | None = None,
    keep_next: bool = False,
    frame: str = "",
    border_top: str | None = None,
    border_bottom: str | None = None,
    tabs: list[int] | None = None,
    before: int | None = None,
    after: int | None = None,
    exact: int | None = None,
    jc: str | None = None,
    hanging: int | None = None,
    run_props: str = "",
) -> str:
    parts = []
    if style:
        parts.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        parts.append("<w:keepNext/>")
    if frame:
        parts.append(frame)
    if border_top or border_bottom:
        borders = ""
        if border_top:
            borders += f'<w:top w:val="single" w:sz="6" w:space="1" w:color="{border_top}"/>'
        if border_bottom:
            borders += f'<w:bottom w:val="single" w:sz="6" w:space="1" w:color="{border_bottom}"/>'
        parts.append(f"<w:pBdr>{borders}</w:pBdr>")
    if tabs:
        parts.append(
            "<w:tabs>" + "".join(f'<w:tab w:val="left" w:pos="{t}"/>' for t in tabs) + "</w:tabs>"
        )
    spacing = []
    if before is not None:
        spacing.append(f'w:before="{before}"')
    if after is not None:
        spacing.append(f'w:after="{after}"')
    if exact is not None:
        spacing.append(f'w:line="{exact}" w:lineRule="exact"')
    if spacing:
        parts.append(f"<w:spacing {' '.join(spacing)}/>")
    if hanging:
        parts.append(f'<w:ind w:left="{hanging}" w:hanging="{hanging}"/>')
    if jc:
        parts.append(f'<w:jc w:val="{jc}"/>')
    if run_props:
        parts.append(run_props)
    return f"<w:pPr>{''.join(parts)}</w:pPr>" if parts else ""


def para(content: str = "", **props) -> str:
    return f"<w:p>{ppr(**props)}{content}</w:p>"


def spacer(height_mm: float) -> str:
    """Leerer Absatz mit genau dieser Höhe."""
    h = max(mm(height_mm), 20)
    return para(exact=h, before=0, after=0, run_props='<w:rPr><w:sz w:val="2"/></w:rPr>')


def frame(x: float, y: float, w: float, h: float | None = None, exact: bool = False) -> str:
    """Positionierter Rahmen (Angaben in mm ab Blattkante)."""
    height = ""
    if h is not None:
        height = f' w:h="{mm(h)}" w:hRule="{"exact" if exact else "atLeast"}"'
    return (
        f'<w:framePr w:w="{mm(w)}"{height} w:hSpace="0" w:wrap="around" '
        f'w:vAnchor="page" w:hAnchor="page" w:x="{mm(x)}" w:y="{mm(y)}"/>'
    )


def sdt_text(alias: str, tag: str, placeholder: str, *, multiline: bool = False, **fmt) -> str:
    """Inhaltssteuerelement (Text) innerhalb eines Absatzes."""
    ml = ' w:multiLine="1"' if multiline else ""
    return (
        f'<w:sdt><w:sdtPr><w:alias w:val="{esc(alias)}"/><w:tag w:val="{tag}"/>'
        f"<w:showingPlcHdr/><w:text{ml}/></w:sdtPr><w:sdtContent>"
        f"{run(placeholder, style='Platzhaltertext', **fmt)}</w:sdtContent></w:sdt>"
    )


def sdt_date(placeholder: str = "Datum wählen") -> str:
    return (
        '<w:sdt><w:sdtPr><w:alias w:val="Datum"/><w:tag w:val="datum"/><w:showingPlcHdr/>'
        '<w:date><w:dateFormat w:val="dd.MM.yyyy"/><w:lid w:val="de-DE"/>'
        '<w:storeMappedDataAs w:val="dateTime"/><w:calendar w:val="gregorian"/></w:date>'
        f"</w:sdtPr><w:sdtContent>{run(placeholder, style='Platzhaltertext')}</w:sdtContent>"
        "</w:sdt>"
    )


def field(instr: str, shown: str, **fmt) -> str:
    return f'<w:fldSimple w:instr=" {instr} ">{run(shown, **fmt)}</w:fldSimple>'


# --- Bilder ---


@dataclass
class Picture:
    name: str
    data: bytes
    width_px: int
    height_px: int

    def fit(self, max_w_mm: float, max_h_mm: float) -> tuple[float, float]:
        ratio = min(max_w_mm / self.width_px, max_h_mm / self.height_px)
        return self.width_px * ratio, self.height_px * ratio


MAX_PICTURE_PIXELS = 40_000_000


def load_picture(source, name: str, max_px: int = 800) -> Picture | None:
    """Bild (Pfad oder Bytes) als PNG; None, wenn es kein lesbares Bild ist."""
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(source if isinstance(source, str) else io.BytesIO(source))
        # Riesige Bilder gar nicht erst entpacken (Audit 29.10. R-V01)
        if image.width * image.height > MAX_PICTURE_PIXELS:
            return None
        image.load()
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        return None
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    image.thumbnail((max_px, max_px))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return Picture(name, out.getvalue(), image.width, image.height)


class Package:
    """Sammelt Teile, Beziehungen und Bilder des Pakets."""

    def __init__(self) -> None:
        self.rels: dict[str, list[tuple[str, str, str]]] = {}
        self.media: dict[str, bytes] = {}
        self._doc_pr = 0

    def image_rel(self, part: str, picture: Picture) -> str:
        target = f"media/{picture.name}.png"
        self.media[f"word/{target}"] = picture.data
        rels = self.rels.setdefault(part, [])
        for rid, _type, tgt in rels:
            if tgt == target:
                return rid
        rid = f"rIdImg{len(rels) + 1}"
        rels.append((rid, f"{REL_BASE}/image", target))
        return rid

    def next_id(self) -> int:
        self._doc_pr += 1
        return self._doc_pr

    def inline_image(self, part: str, picture: Picture, w_mm: float, h_mm: float) -> str:
        rid = self.image_rel(part, picture)
        cx, cy = round(w_mm * EMU_PER_MM), round(h_mm * EMU_PER_MM)
        pid = self.next_id()
        return (
            "<w:r><w:drawing>"
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="{esc(picture.name)}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="{NS_PIC}">'
            f'<pic:pic xmlns:pic="{NS_PIC}"><pic:nvPicPr><pic:cNvPr id="{pid}" '
            f'name="{esc(picture.name)}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            "</pic:blipFill>"
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )


# --- Teile des Briefs ---


def emphasis_color(data: LetterData) -> str:
    """Akzentfarbe für Hervorhebungen, wenn sie auf Weiß lesbar ist, sonst die Primärfarbe."""
    return data.accent if contrast(data.accent, SURFACE) >= 3.0 else data.primary


def first_header(data: LetterData, pkg: Package, logo: Picture | None) -> str:
    form = FORMS[data.form]
    primary = hexcolor(data.primary)
    accent = hexcolor(data.accent)
    text_w = 210 - MARGIN_LEFT - MARGIN_RIGHT
    top = 10 if data.form == "b" else 7
    blocks = []
    name_x, name_w = MARGIN_LEFT, text_w
    if logo is not None:
        lw, lh = logo.fit(55, form["logo_h"])
        left = data.settings.logo_position == "left"
        lx = MARGIN_LEFT if left else 210 - MARGIN_RIGHT - lw
        image = pkg.inline_image("word/header1.xml", logo, lw, lh)
        blocks.append(para(image, frame=frame(lx, top, lw, lh, exact=True), jc="left"))
        name_w = text_w - lw - 6
        if left:
            name_x = MARGIN_LEFT + lw + 6
    name_frame = frame(name_x, top + 1, name_w)
    jc = "left"
    blocks.append(
        para(
            run(data.name, bold=True, size=16 if len(data.name) < 45 else 13, color=primary),
            frame=name_frame,
            jc=jc,
            after=40,
        )
    )
    sub = " · ".join(p for p in (data.tagline, data.sub_line) if p)
    if sub:
        blocks.append(para(run(sub, size=9, color=GREY), frame=name_frame, jc=jc, after=0))
    # feine Linie in der Akzentfarbe unter dem Kopf
    blocks.append(para("", frame=name_frame, border_bottom=accent, after=0, exact=60))
    # Falz- und Lochmarken am linken Rand
    for y in (*form["folds"], HOLE_MARK):
        blocks.append(
            para(
                "",
                frame=frame(4, y, 6 if y != HOLE_MARK else 8, 0.6, exact=True),
                border_top="A6A6A6",
                exact=20,
                run_props='<w:rPr><w:sz w:val="2"/></w:rPr>',
            )
        )
    blocks.append(para())
    return f"<w:hdr {ROOT_ATTRS}>{''.join(blocks)}</w:hdr>"


def follow_header(data: LetterData, pkg: Package, logo: Picture | None) -> str:
    primary = hexcolor(data.primary)
    text_w = mm(210 - MARGIN_LEFT - MARGIN_RIGHT)
    left_w = round(text_w * 0.7)
    content = ""
    if logo is not None:
        lw, lh = logo.fit(25, 9)
        content += pkg.inline_image("word/header2.xml", logo, lw, lh) + run("  ")
    content += run(data.name, bold=True, size=9, color=primary)
    if data.sub_line:
        content += run(f" · {data.sub_line}", size=9, color=GREY)
    page = (
        run("Seite ", size=8, color=GREY)
        + field("PAGE", "2", size=8, color=GREY)
        + run(" von ", size=8, color=GREY)
        + field("NUMPAGES", "2", size=8, color=GREY)
    )
    table = (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{text_w}" w:type="dxa"/>'
        "<w:tblBorders>"
        f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="{hexcolor(data.accent)}"/>'
        "</w:tblBorders>"
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar>'
        '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
        'w:noHBand="1" w:noVBand="1"/>'
        f'</w:tblPr><w:tblGrid><w:gridCol w:w="{left_w}"/><w:gridCol w:w="{text_w - left_w}"/>'
        "</w:tblGrid><w:tr>"
        f'<w:tc><w:tcPr><w:tcW w:w="{left_w}" w:type="dxa"/><w:vAlign w:val="bottom"/></w:tcPr>'
        f"{para(content, after=60)}</w:tc>"
        f'<w:tc><w:tcPr><w:tcW w:w="{text_w - left_w}" w:type="dxa"/>'
        f'<w:vAlign w:val="bottom"/></w:tcPr>{para(page, jc="right", after=60)}</w:tc>'
        "</w:tr></w:tbl>"
    )
    return f"<w:hdr {ROOT_ATTRS}>{table}{para()}</w:hdr>"


def footer_columns(data: LetterData) -> list[tuple[str, list[str]]]:
    """Spalten der Fußzeile, möglichst kurz (der Name steht schon in der Anschrift)."""
    columns: list[tuple[str, list[str]]] = []
    if data.address:
        columns.append(("Anschrift", list(data.address)))
    short = {"Telefon": "Tel.", "E-Mail": "", "Web": ""}
    contact = [
        f"{short.get(label, label)} {value}".strip() if label in short else f"{label}: {value}"
        for label, value in data.contact
    ]
    contact += [handle if "/" in handle else f"{kind}: {handle}" for kind, handle in data.social]
    if contact:
        columns.append(("Kontakt", contact))
    if data.bank:
        b = data.bank
        holder = b["holder"] if b["holder"] and b["holder"] != data.name else ""
        lines = [holder] if holder else []
        if b["bank"]:
            lines.append(b["bank"])
        lines.append(f"IBAN {b['iban']}")
        if b["bic"]:
            lines.append(f"BIC {b['bic']}")
        columns.append(("Bankverbindung", lines))
    board = [f"{p['name']} ({p['role']})" if p["role"] else p["name"] for p in data.board]
    if board:
        columns.append(("Vorstand", board + data.register))
    elif data.register:
        columns.append(("Register", list(data.register)))
    return columns


FOOTER_SIZE = 7  # pt
FOOTER_LINE_MM = 3.1


def footer_rows(data: LetterData) -> int:
    """Zeilen der höchsten Fußzeilenspalte nach Umbruch (mit Überschrift)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    columns = footer_columns(data)
    if not columns:
        return 0
    width = ((210 - MARGIN_LEFT - MARGIN_RIGHT) / len(columns) - 2) / 25.4 * 72
    rows = 0
    for _, lines in columns:
        count = 1
        for line in lines:
            used, n = 0.0, 1
            for word in line.split():
                w = stringWidth(word + " ", "Helvetica", FOOTER_SIZE)
                if used and used + w > width:
                    n += 1
                    used = 0.0
                while w > width:  # überlange Wörter bricht Word zeichenweise um
                    n += 1
                    w -= width
                used += w
            count += n
        rows = max(rows, count)
    return rows


def bottom_margin(data: LetterData) -> float:
    """Unterer Rand in mm, so dass die Fußzeile der ersten Seite immer aufs Blatt passt."""
    return max(MARGIN_BOTTOM, 8 + footer_rows(data) * FOOTER_LINE_MM + 6)


def first_footer(data: LetterData) -> str:
    columns = footer_columns(data)
    if not columns:
        return f"<w:ftr {ROOT_ATTRS}>{para()}</w:ftr>"
    primary = hexcolor(data.primary)
    text_w = mm(210 - MARGIN_LEFT - MARGIN_RIGHT)
    width = text_w // len(columns)
    cells = ""
    for heading, lines in columns:
        content = para(run(heading, bold=True, size=7, color=primary), style="Fusszeile")
        content += "".join(para(run(line, size=7), style="Fusszeile") for line in lines)
        cells += f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>{content}</w:tc>'
    table = (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{width * len(columns)}" w:type="dxa"/>'
        "<w:tblBorders>"
        f'<w:top w:val="single" w:sz="6" w:space="0" w:color="{hexcolor(data.accent)}"/>'
        "</w:tblBorders>"
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:top w:w="57" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:right w:w="113" w:type="dxa"/></w:tblCellMar>'
        '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
        'w:noHBand="1" w:noVBand="1"/>'
        "</w:tblPr><w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{width}"/>' for _ in columns)
        + f"</w:tblGrid><w:tr>{cells}</w:tr></w:tbl>"
    )
    return f"<w:ftr {ROOT_ATTRS}>{table}{para(style='Fusszeile')}</w:ftr>"


def empty_footer() -> str:
    return f"<w:ftr {ROOT_ATTRS}>{para()}</w:ftr>"


def info_block(data: LetterData) -> str:
    """Informationsblock rechts neben dem Anschriftfeld."""
    tab = [mm(24)]
    label = {"size": 8, "color": GREY}

    def line(name: str, value: str) -> str:
        return para(
            run(f"{name}", **label) + tab_run() + value, style="Infoblock", tabs=tab, hanging=tab[0]
        )

    def value_size(name: str, value: str) -> float:
        if name not in NO_WRAP:
            return INFO_SIZE
        return single_line_size(value, data.font, INFO_W - 24)

    rows = []
    sender = data.sender
    if sender is not None:
        rows.append(line("Ansprechpartner", run(sender.name, size=9)))
        if sender.function:
            rows.append(line("Funktion", run(sender.function, size=9)))
        for name, value in sender.lines:
            rows.append(line(name, run(value, size=value_size(name, value))))
        if sender.reply_address:
            rows.append(line("Antwort an", run("\n".join(sender.reply_address), size=9)))
    else:
        rows.append(line("Ansprechpartner", sdt_text("Name", "name", "Name", size=9)))
        rows.append(line("Funktion", sdt_text("Funktion", "funktion", "Funktion", size=9)))
        for name, value in data.contact:
            if name != "Web":
                rows.append(line(name, run(value, size=value_size(name, value))))
    rows.append(para(style="Infoblock"))
    rows.append(line("Datum", sdt_date()))
    form = FORMS[data.form]
    first = para(style="Infoblock", exact=mm(form["info_top"] - form["field_top"]))
    return first + "".join(rows)


def return_size(text: str) -> float:
    """Schriftgröße, mit der die Rücksendeangabe einzeilig bleibt (höchstens 6,5 pt)."""
    return max(5.0, min(6.5, round(6.5 * 80 / max(len(text), 1), 1)))


def address_block(data: LetterData) -> str:
    form = FORMS[data.form]
    return_line = para(
        run(data.return_line, size=return_size(data.return_line), color=GREY, underline=True),
        exact=mm(3.5),
        after=0,
    )
    gap = spacer(form["note_zone"] - 3.5)
    recipient = para(
        sdt_text(
            "Empfänger",
            "empfaenger",
            "Empfänger: Name, Straße und Hausnummer, PLZ Ort",
            multiline=True,
        ),
        style="Anschrift",
    )
    return return_line + gap + recipient


def head_table(data: LetterData) -> str:
    widths = [mm(85), mm(20), mm(INFO_W)]
    total = sum(widths)
    cells = [address_block(data), para(), info_block(data)]
    tcs = "".join(
        f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>{content}</w:tc>'
        for w, content in zip(widths, cells, strict=True)
    )
    return (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{total}" w:type="dxa"/>'
        f'<w:tblInd w:w="{mm(20 - MARGIN_LEFT)}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar>'
        '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
        'w:noHBand="1" w:noVBand="1"/>'
        "</w:tblPr><w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
        + f'</w:tblGrid><w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="{mm(45)}" '
        f'w:hRule="exact"/></w:trPr>{tcs}</w:tr></w:tbl>'
    )


def body(data: LetterData, pkg: Package, signature: Picture | None) -> str:
    form = FORMS[data.form]
    lh = data.settings
    parts = [spacer(form["field_top"] - MARGIN_TOP), head_table(data)]
    parts.append(para(sdt_text("Betreff", "betreff", "Betreff"), style="Betreff", before=mm(8.5)))
    parts.append(para(run(lh.salutation), style="Brieftext", before=mm(8.5)))
    parts.append(para(style="Brieftext"))
    parts.append(para(run(lh.closing), style="Brieftext", keep_next=True, before=mm(4)))
    sender = data.sender
    if signature is not None:
        w, h = signature.fit(60, 15)
        parts.append(
            para(pkg.inline_image("word/document.xml", signature, w, h), keep_next=True, after=0)
        )
    else:
        parts.append(spacer(15).replace("<w:pPr>", "<w:pPr><w:keepNext/>", 1))
    if sender is not None:
        parts.append(para(run(sender.name), keep_next=True, after=0))
        if sender.function:
            parts.append(para(run(sender.function, size=9, color=GREY), after=0))
    else:
        parts.append(para(sdt_text("Name", "unterschrift", "Name"), keep_next=True, after=0))
        parts.append(para(sdt_text("Funktion", "funktion2", "Funktion", size=9), after=0))
    sect = (
        "<w:sectPr>"
        '<w:headerReference w:type="first" r:id="rIdHdrFirst"/>'
        '<w:headerReference w:type="default" r:id="rIdHdr"/>'
        '<w:footerReference w:type="first" r:id="rIdFtrFirst"/>'
        '<w:footerReference w:type="default" r:id="rIdFtr"/>'
        f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
        f'<w:pgMar w:top="{mm(MARGIN_TOP)}" w:right="{mm(MARGIN_RIGHT)}" '
        f'w:bottom="{mm(bottom_margin(data))}" w:left="{mm(MARGIN_LEFT)}" w:header="{mm(10)}" '
        f'w:footer="{mm(8)}" w:gutter="0"/>'
        '<w:cols w:space="708"/><w:titlePg/>'
        "</w:sectPr>"
    )
    return f"<w:document {ROOT_ATTRS}><w:body>{''.join(parts)}{sect}</w:body></w:document>"


# --- feste Teile ---


def styles_xml(data: LetterData) -> str:
    primary = hexcolor(data.primary)
    on_primary = hexcolor(data.on_primary)
    emph = hexcolor(emphasis_color(data))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{NS_W}">
<w:docDefaults>
<w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorHAnsi" w:eastAsiaTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi" w:cstheme="minorBidi"/><w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="de-DE" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Standard"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="character" w:default="1" w:styleId="Absatz-Standardschriftart"><w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="table" w:default="1" w:styleId="NormaleTabelle"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="numbering" w:default="1" w:styleId="KeineListe"><w:name w:val="No List"/><w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Brieftext"><w:name w:val="Brieftext"/><w:basedOn w:val="Standard"/><w:qFormat/><w:pPr><w:spacing w:after="160" w:line="264" w:lineRule="auto"/></w:pPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Betreff"><w:name w:val="Betreff"/><w:basedOn w:val="Standard"/><w:next w:val="Brieftext"/><w:qFormat/><w:pPr><w:keepNext/></w:pPr><w:rPr><w:b/><w:bCs/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Anschrift"><w:name w:val="Anschrift"/><w:basedOn w:val="Standard"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Infoblock"><w:name w:val="Informationsblock"/><w:basedOn w:val="Standard"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Fusszeile"><w:name w:val="Fußzeile klein"/><w:basedOn w:val="Standard"/><w:pPr><w:spacing w:after="0" w:line="216" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="berschrift1"><w:name w:val="heading 1"/><w:basedOn w:val="Standard"/><w:next w:val="Brieftext"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi"/><w:b/><w:bCs/><w:color w:val="{primary}"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="berschrift2"><w:name w:val="heading 2"/><w:basedOn w:val="Standard"/><w:next w:val="Brieftext"/><w:uiPriority w:val="9"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi"/><w:b/><w:bCs/><w:color w:val="{primary}"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Aufzhlungszeichen"><w:name w:val="List Bullet"/><w:basedOn w:val="Brieftext"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr><w:spacing w:after="60"/><w:contextualSpacing/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Kopfzeile"><w:name w:val="header"/><w:basedOn w:val="Standard"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/></w:style>
<w:style w:type="paragraph" w:styleId="Fuzeile"><w:name w:val="footer"/><w:basedOn w:val="Standard"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/></w:style>
<w:style w:type="character" w:customStyle="1" w:styleId="Hervorhebung"><w:name w:val="Hervorhebung Einheit"/><w:basedOn w:val="Absatz-Standardschriftart"/><w:qFormat/><w:rPr><w:b/><w:bCs/><w:color w:val="{emph}"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:basedOn w:val="Absatz-Standardschriftart"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:rPr><w:color w:val="{primary}"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Platzhaltertext"><w:name w:val="Placeholder Text"/><w:basedOn w:val="Absatz-Standardschriftart"/><w:uiPriority w:val="99"/><w:semiHidden/><w:rPr><w:color w:val="808080"/></w:rPr></w:style>
<w:style w:type="table" w:customStyle="1" w:styleId="TabelleEinheit"><w:name w:val="Tabelle Einheit"/><w:basedOn w:val="NormaleTabelle"/><w:uiPriority w:val="40"/><w:qFormat/><w:pPr><w:spacing w:after="0"/></w:pPr><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/></w:tblBorders></w:tblPr><w:tblStylePr w:type="firstRow"><w:rPr><w:b/><w:bCs/><w:color w:val="{on_primary}"/></w:rPr><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="{primary}"/></w:tcPr></w:tblStylePr></w:style>
</w:styles>"""


def numbering_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{NS_W}">
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


def settings_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{NS_W}"><w:zoom w:percent="100"/><w:defaultTabStop w:val="709"/><w:hyphenationZone w:val="425"/><w:characterSpacingControl w:val="doNotCompress"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat><w:themeFontLang w:val="de-DE"/><w:clrSchemeMapping w:bg1="light1" w:t1="dark1" w:bg2="light2" w:t2="dark2" w:accent1="accent1" w:accent2="accent2" w:accent3="accent3" w:accent4="accent4" w:accent5="accent5" w:accent6="accent6" w:hyperlink="hyperlink" w:followedHyperlink="followedHyperlink"/><w:decimalSymbol w:val=","/><w:listSeparator w:val=";"/></w:settings>"""


def _mix(color: str, other: str, share: float) -> str:
    a = [int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(other.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(x * (1 - share) + y * share):02X}" for x, y in zip(a, b, strict=True))


def theme_xml(data: LetterData) -> str:
    """Word-Design: Farben der Einheit als Akzentfarben, Schrift als Design-Schrift."""
    p, a = data.primary, data.accent
    accents = [
        hexcolor(p),
        hexcolor(a),
        _mix(p, "#000000", 0.35),
        _mix(a, "#000000", 0.35),
        _mix(p, "#FFFFFF", 0.45),
        _mix(a, "#FFFFFF", 0.45),
    ]
    font = esc(data.font)
    accent_xml = "".join(
        f'<a:accent{i + 1}><a:srgbClr val="{c}"/></a:accent{i + 1}>' for i, c in enumerate(accents)
    )

    def font_block(tag: str) -> str:
        return (
            f'<a:{tag}><a:latin typeface="{font}"/><a:ea typeface=""/><a:cs typeface=""/></a:{tag}>'
        )

    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = (
        '<a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/>'
        '</a:solidFill><a:prstDash val="solid"/><a:miter lim="800000"/></a:ln>'
    )
    effect = "<a:effectStyle><a:effectLst/></a:effectStyle>"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="{NS_A}" name="HUBIplan"><a:themeElements><a:clrScheme name="Einheit"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="{_mix(p, "#000000", 0.6)}"/></a:dk2><a:lt2><a:srgbClr val="{_mix(p, "#FFFFFF", 0.9)}"/></a:lt2>{accent_xml}<a:hlink><a:srgbClr val="{hexcolor(p)}"/></a:hlink><a:folHlink><a:srgbClr val="{_mix(p, "#000000", 0.35)}"/></a:folHlink></a:clrScheme><a:fontScheme name="Einheit">{font_block("majorFont")}{font_block("minorFont")}</a:fontScheme><a:fmtScheme name="Einheit"><a:fillStyleLst>{fill * 3}</a:fillStyleLst><a:lnStyleLst>{line * 3}</a:lnStyleLst><a:effectStyleLst>{effect * 3}</a:effectStyleLst><a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>"""


def _rels(entries: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{esc(target)}"/>'
        for rid, rtype, target in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{body}</Relationships>"
    )


def core_xml(title: str, author: str) -> str:
    now = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{esc(title)}</dc:title><dc:creator>{esc(author)}</dc:creator><cp:lastModifiedBy>{esc(author)}</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>"""


def app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>HUBIplan</Application></Properties>"
    )


def custom_xml(stand: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="Stand der Daten">'
        f"<vt:lpwstr>{esc(stand)}</vt:lpwstr></property></Properties>"
    )


def content_types(fmt: str) -> str:
    wp = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    overrides = {
        "/word/document.xml": CT_MAIN[fmt],
        "/word/styles.xml": f"{wp}.styles+xml",
        "/word/settings.xml": f"{wp}.settings+xml",
        "/word/numbering.xml": f"{wp}.numbering+xml",
        "/word/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
        "/word/header1.xml": f"{wp}.header+xml",
        "/word/header2.xml": f"{wp}.header+xml",
        "/word/footer1.xml": f"{wp}.footer+xml",
        "/word/footer2.xml": f"{wp}.footer+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        "/docProps/custom.xml": "application/vnd.openxmlformats-officedocument.custom-properties+xml",
    }
    items = "".join(
        f'<Override PartName="{name}" ContentType="{ctype}"/>' for name, ctype in overrides.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        f"{items}</Types>"
    )


def build(data: LetterData, fmt: str = "dotx") -> bytes:
    """Erzeugt die Vorlage als Bytes (.dotx oder .docx)."""
    if fmt not in CT_MAIN:
        raise ValueError(fmt)
    pkg = Package()
    logo = load_picture(data.logo, "logo") if data.logo else None
    signature = None
    if data.sender is not None and data.sender.signature:
        signature = load_picture(data.sender.signature, "unterschrift")
    parts: dict[str, str] = {
        "word/header1.xml": first_header(data, pkg, logo),
        "word/header2.xml": follow_header(data, pkg, logo),
        "word/footer1.xml": first_footer(data),
        "word/footer2.xml": empty_footer(),
        "word/document.xml": body(data, pkg, signature),
        "word/styles.xml": styles_xml(data),
        "word/numbering.xml": numbering_xml(),
        "word/settings.xml": settings_xml(),
        "word/theme/theme1.xml": theme_xml(data),
    }
    doc_rels = [
        ("rIdStyles", f"{REL_BASE}/styles", "styles.xml"),
        ("rIdSettings", f"{REL_BASE}/settings", "settings.xml"),
        ("rIdNumbering", f"{REL_BASE}/numbering", "numbering.xml"),
        ("rIdTheme", f"{REL_BASE}/theme", "theme/theme1.xml"),
        ("rIdHdrFirst", f"{REL_BASE}/header", "header1.xml"),
        ("rIdHdr", f"{REL_BASE}/header", "header2.xml"),
        ("rIdFtrFirst", f"{REL_BASE}/footer", "footer1.xml"),
        ("rIdFtr", f"{REL_BASE}/footer", "footer2.xml"),
        *pkg.rels.get("word/document.xml", []),
    ]
    author = data.sender.name if data.sender else data.name
    title = f"Briefvorlage {data.unit.name}"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types(fmt))
        z.writestr(
            "_rels/.rels",
            _rels(
                [
                    ("rId1", f"{REL_BASE}/officeDocument", "word/document.xml"),
                    (
                        "rId2",
                        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
                        "docProps/core.xml",
                    ),
                    ("rId3", f"{REL_BASE}/extended-properties", "docProps/app.xml"),
                    ("rId4", f"{REL_BASE}/custom-properties", "docProps/custom.xml"),
                ]
            ),
        )
        z.writestr("docProps/core.xml", core_xml(title, author))
        z.writestr("docProps/app.xml", app_xml())
        z.writestr("docProps/custom.xml", custom_xml(data.stand.strftime("%d.%m.%Y")))
        for name, xml in parts.items():
            if not xml.startswith("<?xml"):
                xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml
            z.writestr(name, xml)
        z.writestr("word/_rels/document.xml.rels", _rels(doc_rels))
        for part in ("word/header1.xml", "word/header2.xml"):
            rels = pkg.rels.get(part)
            if rels:
                z.writestr(f"word/_rels/{part.rsplit('/', 1)[-1]}.rels", _rels(rels))
        for name, payload in pkg.media.items():
            z.writestr(name, payload)
    return out.getvalue()


def filename(data: LetterData, fmt: str) -> str:
    base = re.sub(r"[^\w\- ]+", "", f"Briefvorlage {data.unit.name}").strip()
    return f"{re.sub(r'\s+', '_', base)[:80]}.{fmt}"
