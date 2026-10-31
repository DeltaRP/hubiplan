"""Jahresprogramm als PDF zum Verteilen oder Aushängen."""

from __future__ import annotations

import datetime
import io
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from exchange.export import _logo_path
from organizations.theme import effective_theme

from .recurrence import Occurrence
from .services import owner_label

MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def when(occ: Occurrence) -> tuple[str, str]:
    """Datum und Uhrzeit für Listen, z. B. („Sa 13.06.“, „14:00 Uhr“)."""
    start = timezone.localtime(occ.starts_at)
    end = timezone.localtime(occ.ends_at)
    day = f"{WEEKDAYS[start.weekday()]} {start:%d.%m.}"
    if end.date() != start.date():
        day = f"{day} – {WEEKDAYS[end.weekday()]} {end:%d.%m.}"
    if occ.event.all_day:
        return day, ""
    time = f"{start:%H:%M}"
    if end.date() == start.date() and end > start:
        time = f"{time} – {end:%H:%M}"
    return day, f"{time} Uhr"


def render(
    owner_name: str,
    logo_org,
    theme_chain,
    year: int,
    items: list[Occurrence],
    is_own,
) -> bytes:
    """``is_own(event)``: Termin des eigenen Kalenders? Sonst steht der Kalender dabei."""
    buf = io.BytesIO()
    theme = effective_theme(theme_chain)
    primary = colors.HexColor(theme["primary"])
    base = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=base["Normal"], fontSize=9.5, leading=12)
    small = ParagraphStyle("s", parent=normal, fontSize=8, leading=10, textColor=colors.grey)
    title = ParagraphStyle("t", parent=normal, fontSize=18, leading=22)
    month_style = ParagraphStyle(
        "m", parent=normal, fontSize=12, leading=15, textColor=primary, spaceBefore=8
    )
    printed = timezone.localtime().strftime("%d.%m.%Y")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(18 * mm, 10 * mm, f"{owner_name} · Jahresprogramm {year}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Stand {printed} · Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Jahresprogramm {year}",
        author=owner_name,
    )
    story: list = []
    head = [
        Paragraph(f"Jahresprogramm {year}", title),
        Paragraph(escape(owner_name), normal),
    ]
    logo = _logo_path(logo_org)
    if logo:
        try:
            img = Image(logo, width=22 * mm, height=22 * mm, kind="proportional")
            story.append(
                Table(
                    [[head, img]],
                    colWidths=[None, 26 * mm],
                    style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
                )
            )
        except OSError:
            story.extend(head)
    else:
        story.extend(head)
    story.append(Spacer(1, 6 * mm))
    if not items:
        story.append(Paragraph("Für dieses Jahr sind noch keine Termine eingetragen.", normal))
    widths = [32 * mm, 26 * mm, None, 45 * mm]
    for month in range(1, 13):
        rows = [o for o in items if timezone.localtime(o.starts_at).month == month]
        if not rows:
            continue
        data = []
        for occ in rows:
            day, time = when(occ)
            text = f"<b>{escape(occ.event.title)}</b>"
            if not is_own(occ.event):
                text += f"<br/><font size=8 color='#666666'>{escape(owner_label(occ.event))}</font>"
            place = escape(occ.event.location or "")
            data.append(
                [
                    Paragraph(day, normal),
                    Paragraph(time, normal),
                    Paragraph(text, normal),
                    Paragraph(place, normal),
                ]
            )
        table = Table(data, colWidths=widths)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(KeepTogether([Paragraph(MONTHS[month - 1], month_style), table]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Änderungen vorbehalten.", small))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def year_bounds(year: int) -> tuple[datetime.datetime, datetime.datetime]:
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.datetime(year, 1, 1), tz),
        timezone.make_aware(datetime.datetime(year + 1, 1, 1), tz),
    )
