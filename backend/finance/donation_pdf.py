"""Zuwendungsbestätigung als PDF im Briefbogen der Einheit.

Wortlaut nach den amtlichen Mustern (BMF-Schreiben vom 7. November 2013, BStBl I S. 1333,
mit späteren Änderungen) für Körperschaften im Sinne von § 5 Abs. 1 Nr. 9 KStG:
Geldzuwendung/Mitgliedsbeitrag, Sachzuwendung, Sammelbestätigung mit Anlage.
"""

from __future__ import annotations

import datetime
import io
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from letterhead.data import letter_data
from letterhead.pdf import LetterDocument, text_styles

from .models import Donation, DonationSettings, DonationStatement
from .words import euro_words

RECIPIENT = (
    "an eine der in § 5 Abs. 1 Nr. 9 des Körperschaftsteuergesetzes bezeichneten "
    "Körperschaften, Personenvereinigungen oder Vermögensmassen"
)

LIABILITY = (
    "Wer vorsätzlich oder grob fahrlässig eine unrichtige Zuwendungsbestätigung erstellt oder "
    "veranlasst, dass Zuwendungen nicht zu den in der Zuwendungsbestätigung angegebenen "
    "steuerbegünstigten Zwecken verwendet werden, haftet für die entgangene Steuer "
    "(§ 10b Absatz 4 EStG, § 9 Absatz 3 KStG, § 9 Nummer 5 GewStG)."
)
VALIDITY = (
    "Diese Bestätigung wird nicht als Nachweis für die steuerliche Berücksichtigung der "
    "Zuwendung anerkannt, wenn das Datum des Freistellungsbescheides länger als 5 Jahre bzw. "
    "das Datum der Feststellung der Einhaltung der satzungsmäßigen Voraussetzungen nach "
    "§ 60a Abs. 1 AO länger als 3 Jahre seit Ausstellung des Bescheides zurückliegt "
    "(§ 63 Abs. 5 AO)."
)


class CheckBox(Flowable):
    """Kästchen zum Ankreuzen (Helvetica kennt ☐/☒ nicht)."""

    size = 3.2 * mm

    def __init__(self, on: bool):
        super().__init__()
        self.on = on
        self.width = self.height = self.size

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.rect(0, 0, self.size, self.size, stroke=1, fill=0)
        if self.on:
            c.line(0.6, 0.6, self.size - 0.6, self.size - 0.6)
            c.line(0.6, self.size - 0.6, self.size - 0.6, 0.6)


def _checked(on: bool, text: str, style) -> Table:
    """Zeile mit Kästchen und Text wie im amtlichen Muster."""
    table = Table([[CheckBox(on), Paragraph(text, style)]], colWidths=[6 * mm, None])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (0, 0), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def euro(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _date(value) -> str:
    if isinstance(value, str):
        value = datetime.date.fromisoformat(value)
    return f"{value:%d.%m.%Y}"


def filename(statement: DonationStatement) -> str:
    return f"Zuwendungsbestaetigung-{statement.number}.pdf"


def _title(statement: DonationStatement, cfg: DonationSettings) -> str:
    if statement.goods:
        return "Bestätigung über Sachzuwendungen"
    fees = cfg.fees_allowed or any(i["kind"] == Donation.Kind.FEE for i in statement.items)
    what = "Geldzuwendungen/Mitgliedsbeiträge" if fees else "Geldzuwendungen"
    if statement.kind == DonationStatement.Kind.COLLECTIVE:
        return f"Sammelbestätigung über {what}"
    return f"Bestätigung über {what if not fees else 'Geldzuwendungen/Mitgliedsbeitrag'}"


def _notice_text(cfg: DonationSettings) -> str:
    purposes = escape(cfg.purposes.strip())
    office = escape(cfg.tax_office.strip())
    number = escape(cfg.tax_number.strip())
    date = _date(cfg.notice_date) if cfg.notice_date else "…"
    if cfg.notice == DonationSettings.Notice.EXEMPTION:
        return (
            f"Wir sind wegen Förderung <b>{purposes}</b> nach dem Freistellungsbescheid "
            f"bzw. nach der Anlage zum Körperschaftsteuerbescheid des Finanzamtes {office}, "
            f"StNr. {number}, vom {date} für den letzten Veranlagungszeitraum "
            f"{escape(cfg.assessment_period.strip())} nach § 5 Abs. 1 Nr. 9 des "
            "Körperschaftsteuergesetzes von der Körperschaftsteuer und nach § 3 Nr. 6 des "
            "Gewerbesteuergesetzes von der Gewerbesteuer befreit."
        )
    return (
        f"Die Einhaltung der satzungsmäßigen Voraussetzungen nach den §§ 51, 59, 60 und "
        f"61 AO wurde vom Finanzamt {office}, StNr. {number}, mit Bescheid vom {date} nach "
        f"§ 60a AO gesondert festgestellt. Wir fördern nach unserer Satzung <b>{purposes}</b>."
    )


def _grid(rows: list[tuple[str, str]], st, primary) -> Table:
    table = Table(
        [[Paragraph(k, st["small"]), Paragraph(v, st["normal"])] for k, v in rows],
        colWidths=[48 * mm, None],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, primary),
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, primary),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#c0c0c0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def story(statement: DonationStatement, cfg: DonationSettings) -> tuple[list, object]:
    org = statement.organization
    data = letter_data(org)
    st = text_styles(data)
    body = ParagraphStyle("zb", parent=st["normal"], fontSize=9.5, leading=12.5, spaceAfter=5)
    primary = colors.HexColor(data.primary)
    meta = [("Nummer", statement.number), ("Datum", _date(statement.issued_on))]
    recipient = (statement.donor_name + "\n" + statement.donor_address).splitlines()
    parts: list = LetterDocument.start(data, recipient, meta, True)
    parts.append(Paragraph(escape(_title(statement, cfg)), st["title"]))
    parts.append(
        Paragraph(f"im Sinne des § 10b des Einkommensteuergesetzes {RECIPIENT}", st["small"])
    )
    if statement.cancelled_at:
        parts.append(
            Paragraph(
                f"<b>STORNIERT</b> am {statement.cancelled_at:%d.%m.%Y}. "
                f"Grund: {escape(statement.cancel_reason)}",
                ParagraphStyle("storno", parent=body, textColor=colors.HexColor("#b00020")),
            )
        )
    parts.append(Spacer(1, 3 * mm))
    donor = escape(statement.donor_name)
    if statement.donor_address.strip():
        donor += ", " + escape(", ".join(statement.donor_address.splitlines()))
    collective = statement.kind == DonationStatement.Kind.COLLECTIVE
    item = statement.items[0]
    rows = [("Name und Anschrift des Zuwendenden", donor)]
    if statement.goods:
        rows += [
            ("Wert der Zuwendung – in Ziffern –", f"<b>{euro(statement.total)}</b>"),
            ("– in Buchstaben –", escape(euro_words(statement.total))),
            ("Tag der Zuwendung", _date(item["date"])),
        ]
    elif collective:
        rows += [
            ("Gesamtbetrag der Zuwendung – in Ziffern –", f"<b>{euro(statement.total)}</b>"),
            ("– in Buchstaben –", escape(euro_words(statement.total))),
            (
                "Zeitraum der Sammelbestätigung",
                f"{_date(statement.period_from)} bis {_date(statement.period_to)}",
            ),
        ]
    else:
        rows += [
            ("Betrag der Zuwendung – in Ziffern –", f"<b>{euro(statement.total)}</b>"),
            ("– in Buchstaben –", escape(euro_words(statement.total))),
            ("Tag der Zuwendung", _date(item["date"])),
        ]
    parts.append(_grid(rows, st, primary))
    parts.append(Spacer(1, 3 * mm))
    if statement.goods:
        parts.append(
            Paragraph(
                "<b>Genaue Bezeichnung der Sachzuwendung mit Alter, Zustand, Kaufpreis usw.:</b> "
                + escape(item.get("goods_description", "")),
                body,
            )
        )
        origin = item.get("goods_origin", "")
        parts += [
            _checked(
                origin == Donation.Origin.BUSINESS,
                "Die Sachzuwendung stammt nach den Angaben des Zuwendenden aus dem "
                "Betriebsvermögen. Die Zuwendung wurde nach dem Wert der Entnahme (ggf. mit dem "
                "niedrigeren gemeinen Wert) und nach der Umsatzsteuer, die auf die Entnahme "
                "entfällt, bewertet.",
                body,
            ),
            _checked(
                origin == Donation.Origin.PRIVATE,
                "Die Sachzuwendung stammt nach den Angaben des Zuwendenden aus dem Privatvermögen.",
                body,
            ),
            _checked(
                origin == Donation.Origin.UNKNOWN,
                "Der Zuwendende hat trotz Aufforderung keine Angaben zur Herkunft der "
                "Sachzuwendung gemacht.",
                body,
            ),
            _checked(
                bool(item.get("goods_documents")),
                "Geeignete Unterlagen, die zur Wertermittlung gedient haben, z. B. Rechnung, "
                "Gutachten, liegen vor.",
                body,
            ),
        ]
    elif collective:
        parts.append(
            Paragraph(
                "Ob es sich um den Verzicht auf Erstattung von Aufwendungen handelt, ist der "
                "Anlage zur Sammelbestätigung zu entnehmen.",
                body,
            )
        )
    else:
        waiver = bool(item.get("waiver"))
        line = Table(
            [
                [
                    Paragraph(
                        "Es handelt sich um den Verzicht auf Erstattung von Aufwendungen:", body
                    ),
                    Paragraph("Ja", body),
                    CheckBox(waiver),
                    Paragraph("Nein", body),
                    CheckBox(not waiver),
                ]
            ],
            colWidths=[110 * mm, 8 * mm, 10 * mm, 11 * mm, 8 * mm],
            hAlign="LEFT",
        )
        line.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (2, 0), (2, 0), 2),
                    ("TOPPADDING", (4, 0), (4, 0), 2),
                ]
            )
        )
        parts.append(line)
    parts.append(Spacer(1, 2 * mm))
    parts.append(_checked(True, _notice_text(cfg), body))
    parts.append(
        Paragraph(
            "Es wird bestätigt, dass die Zuwendung nur zur Förderung "
            f"<b>{escape(cfg.purposes.strip())}</b> verwendet wird.",
            body,
        )
    )
    has_fee = any(i["kind"] == Donation.Kind.FEE for i in statement.items)
    if not statement.goods and (cfg.fees_allowed or has_fee):
        parts.append(
            Paragraph(
                "Nur für steuerbegünstigte Einrichtungen, bei denen die Mitgliedsbeiträge "
                "steuerlich nicht abgezogen werden dürfen:",
                body,
            )
        )
        parts.append(
            _checked(
                not has_fee,
                "Es wird bestätigt, dass es sich nicht um einen Mitgliedsbeitrag handelt, dessen "
                "Abzug nach § 10b Abs. 1 des Einkommensteuergesetzes ausgeschlossen ist.",
                body,
            )
        )
    if collective:
        parts.append(
            Paragraph(
                "Es wird bestätigt, dass über die in der Gesamtsumme enthaltenen Zuwendungen "
                "keine weiteren Bestätigungen, weder formelle Zuwendungsbestätigungen noch "
                "Beitragsquittungen oder ähnliches ausgestellt wurden und werden.",
                body,
            )
        )
    place = cfg.place.strip() or (org.city or "")
    signer = escape(statement.signer_name.strip())
    sign_label = "Unterschrift des Zuwendungsempfängers" + (f" ({signer})" if signer else "")
    parts.append(Spacer(1, 6 * mm))
    parts.append(
        KeepTogether(
            [
                Paragraph(f"{escape(place)}, {_date(statement.issued_on)}", body),
                Spacer(1, 9 * mm),
                Table(
                    [
                        [""],
                        [Paragraph(sign_label, st["small"])],
                    ],
                    colWidths=[80 * mm],
                    style=TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.6, colors.black)]),
                    hAlign="LEFT",
                ),
            ]
        )
    )
    parts.append(Spacer(1, 5 * mm))
    parts.append(
        KeepTogether(
            [
                Paragraph("<b>Hinweis:</b> " + LIABILITY, st["small"]),
                Spacer(1, 1 * mm),
                Paragraph(VALIDITY, st["small"]),
            ]
        )
    )
    if collective:
        parts.append(PageBreak())
        parts.append(Paragraph(f"Anlage zur Sammelbestätigung {statement.number}", st["title"]))
        head = [
            "Datum der Zuwendung",
            "Art der Zuwendung",
            "Verzicht auf Erstattung von Aufwendungen (ja/nein)",
            "Betrag",
        ]
        rows = [[Paragraph(h, st["small"]) for h in head]]
        for i in statement.items:
            rows.append(
                [
                    Paragraph(_date(i["date"]), st["normal"]),
                    Paragraph(
                        "Mitgliedsbeitrag" if i["kind"] == Donation.Kind.FEE else "Geldzuwendung",
                        st["normal"],
                    ),
                    Paragraph("ja" if i.get("waiver") else "nein", st["normal"]),
                    Paragraph(euro(Decimal(i["amount"])), st["right"]),
                ]
            )
        rows.append(
            [
                Paragraph("<b>Gesamtsumme</b>", st["normal"]),
                "",
                "",
                Paragraph(f"<b>{euro(statement.total)}</b>", st["right"]),
            ]
        )
        table = Table(rows, colWidths=[32 * mm, 40 * mm, None, 30 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, 0), 0.8, primary),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.8, primary),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        parts.append(table)
    return parts, data


def render(statement: DonationStatement, cfg: DonationSettings) -> bytes:
    buf = io.BytesIO()
    parts, data = story(statement, cfg)
    LetterDocument(
        buf,
        [data],
        title=f"Zuwendungsbestätigung {statement.number}",
        author=statement.organization.name,
    ).build(parts)
    return buf.getvalue()
