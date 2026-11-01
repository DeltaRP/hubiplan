"""Ausgaben einer Fassung: Brief auf dem Briefbogen (PDF) und Tabelle (Excel, CSV).

Beides entsteht aus dem festgehaltenen Stand (``EntryVersion.data``), damit ein Beleg
später genau so aussieht wie beim Abgeben."""

from __future__ import annotations

import csv
import io
import re
from xml.sax.saxutils import escape

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, ListFlowable, ListItem, Paragraph, Spacer, Table

from exchange.export import safe_cell

from .models import Call, EntryVersion


def _date(d) -> str:
    return f"{d:%d.%m.%Y}" if d else ""


def subject(version: EntryVersion) -> str:
    title = version.entry.call.title
    if version.kind == EntryVersion.Kind.CHANGE:
        return f"Änderung der Meldung zu {title}"
    if version.kind == EntryVersion.Kind.WITHDRAWAL:
        return f"Rückzug der Meldung zu {title}"
    return f"Meldung zu {title}"


def intro(version: EntryVersion) -> str:
    call: Call = version.entry.call
    what = call.title
    when = f" am {_date(call.date)}" if call.date else ""
    where = f" in {call.location}" if call.location else ""
    if version.kind == EntryVersion.Kind.CHANGE:
        return f"zu unserer Meldung für {what}{when}{where} teilen wir folgende Änderungen mit:"
    if version.kind == EntryVersion.Kind.WITHDRAWAL:
        return f"hiermit ziehen wir unsere Meldung für {what}{when}{where} zurück."
    return f"hiermit melden wir für {what}{when}{where}:"


def filename(version: EntryVersion, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "-", subject(version)).strip("-")[:80]
    return f"{base}-Fassung-{version.number}.{ext}"


def _person_label(p: dict) -> str:
    text = p["name"]
    if p.get("club"):
        text += f" ({p['club']})"
    extra = [x for x in (p.get("position"), "Ersatz" if p.get("substitute") else "") if x]
    if extra:
        text += " – " + ", ".join(extra)
    return text


def _persons_table(persons: list[dict], fields: list[dict], st, primary) -> Table:
    head = ["Nr.", "Name"] + [f["label"] for f in fields]
    rows = [[Paragraph(f"<b>{escape(h)}</b>", st["normal"]) for h in head]]
    for n, p in enumerate(persons, 1):
        rows.append(
            [Paragraph(str(n), st["normal"]), Paragraph(escape(_person_label(p)), st["normal"])]
            + [
                Paragraph(escape(p.get("details", {}).get(f["key"], "")), st["normal"])
                for f in fields
            ]
        )
    total = 170 * mm
    first = 10 * mm
    if fields:
        name_w = max(60 * mm, total - first - 30 * mm * len(fields))
        rest = (total - first - name_w) / len(fields)
        widths = [first, name_w] + [rest] * len(fields)
    else:
        widths = [first, total - first]
    return Table(
        rows,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
        style=[
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, primary),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ],
    )


def _value_text(value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def body_flowables(data: dict, st, primary) -> list:
    """Bausteine der Meldung als Absätze und Tabellen."""
    story: list = []
    fields = data.get("fields", [])
    for b in data.get("blocks", []):
        if "teams" in b:
            if not b["teams"]:
                continue
            story.append(Paragraph(f"<b>{escape(b['label'])}</b>", st["body"]))
            for t in b["teams"]:
                story.append(
                    KeepTogether(
                        [
                            Paragraph(escape(t["name"]), st["title"]),
                            _persons_table(t["persons"], fields, st, primary),
                            Spacer(1, 3 * mm),
                        ]
                    )
                )
        elif "persons" in b:
            if not b["persons"]:
                continue
            story.append(Paragraph(f"<b>{escape(b['label'])}</b>", st["body"]))
            story.append(_persons_table(b["persons"], fields, st, primary))
            story.append(Spacer(1, 3 * mm))
        else:
            story.append(
                Paragraph(
                    f"<b>{escape(b['label'])}:</b> {escape(_value_text(b.get('value')))}",
                    st["body"],
                )
            )
    if data.get("fee"):
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"Meldegebühr: {escape(data['fee'])}", st["body"]))
    return story


def letter_pdf(version: EntryVersion) -> bytes:
    from letterhead.data import Sender, letter_data
    from letterhead.pdf import LetterDocument, text_styles

    entry = version.entry
    call = entry.call
    sender = None
    if version.signed_by:
        sender = Sender(name=version.signed_by, function=version.signed_function)
    data = letter_data(entry.organization, sender=sender)
    st = text_styles(data)
    primary = colors.HexColor(data.primary)
    sent = timezone.localtime(version.created_at).date()
    info = [
        *((label, value) for label, value in data.contact if label in ("Telefon", "E-Mail")),
        ("Datum", _date(sent)),
    ]
    recipient = [call.organizer, *[x for x in call.organizer_address.splitlines() if x.strip()]]
    story: list = LetterDocument.start(data, recipient, info, True)
    story.append(Paragraph(escape(subject(version)), st["title"]))
    story.append(Spacer(1, 2 * mm))
    if call.salutation:
        story.append(Paragraph(escape(call.salutation), st["body"]))
    story.append(Paragraph(escape(intro(version)), st["body"]))
    payload = version.data or {}
    if version.kind == EntryVersion.Kind.CHANGE:
        story.append(
            ListFlowable(
                [ListItem(Paragraph(escape(c), st["body"])) for c in version.changes],
                bulletType="bullet",
                start="•",
                leftIndent=12,
            )
        )
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("Die vollständige Meldung nach der Änderung:", st["body"]))
        story += body_flowables(payload, st, primary)
    elif version.kind == EntryVersion.Kind.WITHDRAWAL:
        if version.reason:
            story.append(Paragraph(f"Grund: {escape(version.reason)}", st["body"]))
    else:
        story += body_flowables(payload, st, primary)
    story.append(Spacer(1, 4 * mm))
    closing = [Paragraph("Mit freundlichen Grüßen", st["body"]), Spacer(1, 14 * mm)]
    if version.signed_by:
        closing.append(Paragraph(escape(version.signed_by), st["normal"]))
    if version.signed_function:
        closing.append(Paragraph(escape(version.signed_function), st["normal"]))
    closing.append(Paragraph(escape(entry.organization.name), st["normal"]))
    story.append(KeepTogether(closing))
    buf = io.BytesIO()
    LetterDocument(buf, [data], title=subject(version), author=data.name).build(story)
    return buf.getvalue()


def table_rows(version: EntryVersion) -> list[list]:
    data = version.data or {}
    fields = data.get("fields", [])
    head = ["Baustein", "Mannschaft", "Nr.", "Name", "Verein", "Aufgabe", "Ersatz"] + [
        f["label"] for f in fields
    ]
    rows: list[list] = [head]

    def person_row(block, team, n, p):
        return [
            block,
            team,
            n,
            p["name"],
            p.get("club", ""),
            p.get("position", ""),
            "ja" if p.get("substitute") else "",
        ] + [p.get("details", {}).get(f["key"], "") for f in fields]

    for b in data.get("blocks", []):
        if "teams" in b:
            for t in b["teams"]:
                for n, p in enumerate(t["persons"], 1):
                    rows.append(person_row(b["label"], t["name"], n, p))
        elif "persons" in b:
            for n, p in enumerate(b["persons"], 1):
                rows.append(person_row(b["label"], "", n, p))
        else:
            rows.append([b["label"], "", "", _value_text(b.get("value"))] + [""] * (len(head) - 4))
    return rows


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "-", text).strip("-")[:80]


def table_xlsx(version: EntryVersion) -> bytes:
    return rows_xlsx(table_rows(version))


def table_csv(version: EntryVersion) -> bytes:
    return rows_csv(table_rows(version))


def rows_xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Meldung"
    for row in rows:
        ws.append([safe_cell(v) for v in row])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i, col in enumerate(ws.columns, 1):
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 6), 50)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def rows_csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    # BOM, damit Excel die Umlaute erkennt
    return ("﻿" + buf.getvalue()).encode("utf-8")
