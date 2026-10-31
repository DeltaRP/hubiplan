"""Rechnungen als PDF (DIN A4, Anschriftfeld für Fensterumschläge)."""

from __future__ import annotations

import io
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from letterhead.data import letter_data
from letterhead.pdf import LetterDocument, text_styles

from .models import BillingSettings, Dunning, Invoice, Payment
from .services import included_vat, settings_for, vat_breakdown
from .units import visible_membership


def euro(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def epc_payload(name: str, iban: str, bic: str, amount: Decimal, purpose: str) -> str:
    """Inhalt des EPC-QR-Codes („GiroCode“) für Banking-Apps."""
    return "\n".join(
        [
            "BCD",
            "002",
            "1",
            "SCT",
            bic,
            name[:70],
            iban,
            f"EUR{amount:.2f}",
            "",
            "",
            purpose[:140],
        ]
    )


def qr_drawing(payload: str, size: float = 30 * mm) -> Drawing:
    widget = QrCodeWidget(payload, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(widget)
    return drawing


def _styles():
    base = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=base["Normal"], fontSize=10, leading=13)
    return {
        "normal": normal,
        "small": ParagraphStyle("s", parent=normal, fontSize=8, leading=10),
        "sender": ParagraphStyle("snd", parent=normal, fontSize=7, leading=9),
        "title": ParagraphStyle("t", parent=normal, fontSize=14, leading=18, spaceAfter=4),
        "right": ParagraphStyle("r", parent=normal, alignment=TA_RIGHT),
        "right_small": ParagraphStyle("rs", parent=normal, fontSize=8, alignment=TA_RIGHT),
    }


def _lines(text: str) -> str:
    return "<br/>".join(escape(line) for line in text.splitlines() if line.strip())


def _contact_rows(data) -> list[tuple[str, str]]:
    return [(label, value) for label, value in data.contact if label in ("Telefon", "E-Mail")]


def _letter(org, cache: dict | None = None):
    """Briefbogen der Einheit (je Einheit nur einmal je PDF aufbauen)."""
    if cache is not None and org.pk in cache:
        return cache[org.pk]
    data = letter_data(org)
    if cache is not None:
        cache[org.pk] = data
    return data


def invoice_story(
    invoice: Invoice, dunning: Dunning | None = None, first: bool = True, cache=None
) -> list:
    org = invoice.organization
    cfg = settings_for(org)
    data = _letter(org, cache)
    st = text_styles(data)
    primary = colors.HexColor(data.primary)

    draft = invoice.status == Invoice.Status.DRAFT
    title = "Rechnung (Entwurf)" if draft else "Rechnung"
    if invoice.status == Invoice.Status.CANCELLED:
        title = "Rechnung (storniert)"
    if dunning is not None:
        title = dunning.name
    meta = [
        ("Rechnungsnr.", "–" if draft else invoice.display_number),
        ("Rechnungsdatum", f"{invoice.date:%d.%m.%Y}"),
        ("zahlbar bis", f"{invoice.due_date:%d.%m.%Y}"),
    ]
    if dunning is not None:
        meta = [
            ("Rechnungsnr.", invoice.display_number),
            ("Rechnungsdatum", f"{invoice.date:%d.%m.%Y}"),
            ("urspr. fällig", f"{invoice.due_date:%d.%m.%Y}"),
            ("Datum", f"{dunning.date:%d.%m.%Y}"),
            ("zahlbar bis", f"{dunning.due_date:%d.%m.%Y}"),
        ]
    membership = visible_membership(invoice)
    if membership is not None and membership.club_number:
        meta.append(("Mitgliedsnr.", membership.club_number))
    meta += _contact_rows(data)
    if cfg.tax_number:
        meta.append(("Steuernummer", cfg.tax_number))
    recipient = (invoice.recipient_name + "\n" + invoice.recipient_address).splitlines()
    story: list = LetterDocument.start(data, recipient, meta, first)
    story.append(Paragraph(escape(title), st["title"]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(f"<b>{escape(invoice.subject)}</b>", st["normal"]))
    story.append(Spacer(1, 3 * mm))
    salutation = "Guten Tag,"
    story.append(Paragraph(salutation, st["normal"]))
    if dunning is not None:
        text = dunning.text or (
            f"zu der unten aufgeführten Rechnung konnten wir bis heute keinen vollständigen "
            f"Zahlungseingang feststellen. Bitte überweisen Sie den offenen Betrag bis zum "
            f"{dunning.due_date:%d.%m.%Y}. Sollten Sie inzwischen bezahlt haben, betrachten "
            f"Sie dieses Schreiben bitte als gegenstandslos."
        )
        story.append(Paragraph(_lines(text), st["normal"]))
    elif cfg.intro_text:
        story.append(Paragraph(_lines(cfg.intro_text), st["normal"]))
    story.append(Spacer(1, 4 * mm))

    collective = invoice.recipient_kind == Invoice.Recipient.DEPARTMENT
    head = ["Nr.", "Mitglied" if collective else "Posten", "", "Betrag"]
    rows = [[Paragraph(f"<b>{h}</b>", st["small"]) for h in head]]
    for n, line in enumerate(invoice.lines.all(), start=1):
        rows.append(
            [
                Paragraph(str(n), st["small"]),
                Paragraph(escape(line.text), st["normal"]),
                Paragraph(escape(line.detail), st["small"]),
                Paragraph(euro(line.amount), st["right"]),
            ]
        )
    rows.append(
        [
            "",
            Paragraph("<b>Gesamtbetrag</b>", st["normal"]),
            "",
            Paragraph(f"<b>{euro(invoice.total)}</b>", st["right"]),
        ]
    )
    table = Table(rows, colWidths=[10 * mm, 70 * mm, None, 30 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, primary),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, primary),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f4f5f4")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    vat = vat_breakdown(invoice)
    for row in vat:
        story.append(
            Paragraph(
                f"Im Betrag von {euro(row['gross'])} sind {_rate(row['rate'])} Umsatzsteuer "
                f"enthalten: {euro(row['vat'])} (netto {euro(row['net'])}).",
                st["small"],
            )
        )
    lines = list(invoice.lines.all())
    if not vat:
        if all(line.is_fee or line.is_dunning_fee for line in lines):
            note = "Der Betrag enthält keine Umsatzsteuer (Mitgliedsbeitrag, nicht steuerbar)."
        else:
            note = "Der Betrag enthält keine Umsatzsteuer."
        story.append(Paragraph(note, st["small"]))
    elif any(not line.vat_rate for line in lines):
        story.append(Paragraph("Die übrigen Posten enthalten keine Umsatzsteuer.", st["small"]))
    if invoice.note:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_lines(invoice.note), st["normal"]))

    if invoice.paid and invoice.status != Invoice.Status.CANCELLED:
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                f"Bereits bezahlt: {euro(invoice.paid)} · noch offen: {euro(invoice.outstanding)}",
                st["normal"],
            )
        )

    account = cfg.account
    due = invoice.total if draft else invoice.outstanding
    number = "Rechnung" if draft else invoice.display_number
    purpose = f"{number} {invoice.recipient_name.splitlines()[0]}"
    mandate = _debit_mandate(invoice, cfg)
    if mandate is not None and due > 0 and invoice.status != Invoice.Status.CANCELLED:
        from .sepa import masked_iban

        story.append(Spacer(1, 6 * mm))
        story.append(
            Paragraph(
                f"<b>Der Betrag von {euro(due)} wird per SEPA-Lastschrift von Ihrem Konto "
                f"{escape(masked_iban(mandate.iban))} eingezogen.</b> Den genauen Termin teilen "
                f"wir Ihnen vorher mit. Mandatsreferenz {escape(mandate.reference)}, "
                f"Gläubiger-ID {escape(cfg.creditor_id)}. Bitte nicht überweisen.",
                st["normal"],
            )
        )
    elif account and account.iban and due > 0 and invoice.status != Invoice.Status.CANCELLED:
        bank = [
            Paragraph("<b>Bitte überweisen Sie den Betrag auf folgendes Konto:</b>", st["normal"]),
            Paragraph(f"Kontoinhaber: {escape(org.name)}", st["normal"]),
            Paragraph(f"IBAN: {escape(_iban(account.iban))}", st["normal"]),
        ]
        if account.bic:
            bank.append(Paragraph(f"BIC: {escape(account.bic)}", st["normal"]))
        if account.bank_name:
            bank.append(Paragraph(f"Bank: {escape(account.bank_name)}", st["normal"]))
        bank.append(Paragraph(f"Verwendungszweck: {escape(purpose)}", st["normal"]))
        bank.append(Paragraph(f"Betrag: {euro(due)}", st["normal"]))
        cells = [[bank, ""]]
        if cfg.qr_code:
            qr = qr_drawing(epc_payload(org.name, account.iban, account.bic, due, purpose))
            cells = [[bank, [qr, Paragraph("mit der Banking-App scannen", st["small"])]]]
        story.append(Spacer(1, 6 * mm))
        story.append(
            KeepTogether(
                Table(
                    cells,
                    colWidths=[None, 34 * mm],
                    style=[
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9cfcc")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ],
                )
            )
        )
    if cfg.footer_text:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(_lines(cfg.footer_text), st["normal"]))
    return story


def _debit_mandate(invoice: Invoice, cfg):
    if not cfg.sepa_enabled or not cfg.creditor_id:
        return None
    from .sepa import payer_mandate

    return payer_mandate(invoice)


def prenotification_text(item) -> str:
    from .sepa import masked_iban

    invoice = item.invoice
    org = invoice.organization
    cfg = settings_for(org)
    return (
        f"wir ziehen am {item.run.collection_date:%d.%m.%Y} den Betrag von {euro(item.amount)} "
        f"für die Rechnung {invoice.display_number} ({invoice.subject}) per SEPA-Lastschrift "
        f"von Ihrem Konto {masked_iban(item.mandate.iban)} ein.\n"
        f"Mandatsreferenz: {item.mandate.reference}\n"
        f"Gläubiger-Identifikationsnummer: {cfg.creditor_id}\n"
        f"Bitte sorgen Sie für ausreichende Deckung. Fällt der Termin auf einen Feiertag, "
        f"erfolgt der Einzug am nächsten Bankarbeitstag."
    )


def render_prenotifications(items) -> bytes:
    cache: dict = {}
    story: list = []
    letters = []
    for n, item in enumerate(items):
        invoice = item.invoice
        data = _letter(invoice.organization, cache)
        letters.append(data)
        st = text_styles(data)
        recipient = (invoice.recipient_name + "\n" + invoice.recipient_address).splitlines()
        info = [("Datum", f"{timezone.localdate():%d.%m.%Y}"), *_contact_rows(data)]
        story.extend(LetterDocument.start(data, recipient, info, n == 0))
        story.append(Paragraph("Ankündigung einer SEPA-Lastschrift", st["title"]))
        story.append(Paragraph("Guten Tag,", st["normal"]))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(_lines(prenotification_text(item)), st["normal"]))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"Viele Grüße<br/>{escape(data.name)}", st["normal"]))
    if not story:
        story.append(Paragraph("Keine Ankündigungen.", _styles()["normal"]))
    buf = io.BytesIO()
    LetterDocument(buf, letters, title="Vorabankündigung").build(story)
    return buf.getvalue()


def _rate(rate: Decimal) -> str:
    return f"{rate.normalize():f} %".replace(".", ",")


def _iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def render(invoices: list[Invoice], dunnings: dict[int, Dunning] | None = None) -> bytes:
    dunnings = dunnings or {}
    buf = io.BytesIO()
    first = invoices[0] if invoices else None
    cache: dict = {}
    story: list = []
    for n, invoice in enumerate(invoices):
        story.extend(invoice_story(invoice, dunnings.get(invoice.pk), n == 0, cache))
    letters = [_letter(invoice.organization, cache) for invoice in invoices]
    if not story:
        story.append(Paragraph("Keine Rechnungen.", _styles()["normal"]))
    title = first.display_number if len(invoices) == 1 and first else "Rechnungen"
    LetterDocument(
        buf,
        letters,
        title=title if not dunnings else "Mahnung",
        author=first.organization.name if first else "",
    ).build(story)
    return buf.getvalue()


def filename(invoice: Invoice) -> str:
    if invoice.number is None:
        return f"Rechnung-Entwurf-{invoice.pk}.pdf"
    return f"Rechnung-{invoice.display_number.replace('/', '-')}.pdf"


def dunning_filename(dunning: Dunning) -> str:
    number = dunning.invoice.display_number.replace("/", "-")
    return f"Mahnung-{dunning.level}-{number}.pdf"


def receipt_story(payment: Payment) -> tuple[list, object]:
    """Quittung über eine Zahlung (Schritt B5: bar kassiert, aus der App geteilt)."""
    invoice = payment.invoice
    org = invoice.organization
    cfg = settings_for(org)
    data = _letter(org)
    st = text_styles(data)
    primary = colors.HexColor(data.primary)
    meta = [
        ("Quittung zu", invoice.display_number),
        ("Buchung", payment.booking.display_number),
        ("Datum", f"{payment.date:%d.%m.%Y}"),
    ]
    membership = visible_membership(invoice)
    if membership is not None and membership.club_number:
        meta.append(("Mitgliedsnr.", membership.club_number))
    meta += _contact_rows(data)
    if cfg.tax_number:
        meta.append(("Steuernummer", cfg.tax_number))
    recipient = (invoice.recipient_name + "\n" + invoice.recipient_address).splitlines()
    story: list = LetterDocument.start(data, recipient, meta, True)
    story.append(Paragraph("Quittung", st["title"]))
    story.append(Spacer(1, 5 * mm))
    payer = invoice.recipient_name.splitlines()[0] if invoice.recipient_name else ""
    rows = [
        ("Betrag", f"<b>{euro(payment.amount)}</b>"),
        ("erhalten von", escape(payer)),
        ("für", escape(f"{invoice.subject} ({invoice.display_number})")),
        ("Zahlungsweg", escape(payment.get_method_display())),
        ("am", f"{payment.date:%d.%m.%Y}"),
    ]
    if invoice.status != Invoice.Status.CANCELLED:
        rest = invoice.outstanding
        rows.append(("noch offen", euro(rest) if rest > 0 else "nichts, Rechnung bezahlt"))
    table = Table(
        [[Paragraph(k, st["normal"]), Paragraph(v, st["normal"])] for k, v in rows],
        colWidths=[35 * mm, None],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, primary),
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, primary),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    if vat_breakdown(invoice):
        note = f"Die enthaltene Umsatzsteuer steht auf der Rechnung {invoice.display_number}."
    else:
        note = "Der Betrag enthält keine Umsatzsteuer."
    story.append(Paragraph(escape(note), st["small"]))
    story.append(Spacer(1, 18 * mm))
    user = payment.created_by
    who = (user.get_full_name() or user.email) if user else ""
    sign = Table(
        [
            [
                Paragraph(f"{payment.date:%d.%m.%Y}", st["normal"]),
                Paragraph(escape(who), st["normal"]),
            ],
            [
                Paragraph("Datum", st["small"]),
                Paragraph(f"Betrag erhalten für {escape(org.name)}", st["small"]),
            ],
        ],
        colWidths=[50 * mm, None],
        style=[("LINEABOVE", (0, 1), (-1, 1), 0.5, colors.HexColor("#888888"))],
    )
    story.append(KeepTogether(sign))
    return story, data


def render_receipt(payment: Payment) -> bytes:
    buf = io.BytesIO()
    story, data = receipt_story(payment)
    LetterDocument(
        buf,
        [data],
        title=f"Quittung {payment.invoice.display_number}",
        author=payment.invoice.organization.name,
    ).build(story)
    return buf.getvalue()


def receipt_filename(payment: Payment) -> str:
    number = payment.invoice.display_number.replace("/", "-")
    return f"Quittung-{number}-{payment.pk}.pdf"


# --- Quittung mit Unterschriften (konzepte/digitale-quittung.md) ---


def signature_block(receipt, st, *, preview: bool = False):
    """Zwei Unterschriftenfelder nebeneinander: Kassierer und Gegenseite."""
    from finance import signature

    org = receipt.organization
    box_w, box_h = 70 * mm, 22 * mm
    line = colors.HexColor("#888888")

    def cell(stored, name: str, role: str, signed_at):
        img = signature.drawing(stored, box_w, box_h) if stored else Spacer(box_w, box_h)
        when = f", {timezone.localtime(signed_at):%d.%m.%Y %H:%M} Uhr" if signed_at else ""
        caption = f"{escape(role)}<br/>{escape(name)}{when}"
        return [img, Paragraph(caption, st["small"])]

    org_name = org.name
    if receipt.receives:
        left_role = f"Betrag erhalten für {org_name}"
        right_role = "Betrag gezahlt"
    else:
        left_role = f"Betrag ausgezahlt für {org_name}"
        right_role = "Betrag erhalten"
    left = cell(
        receipt.treasurer_signature,
        receipt.treasurer_name or ("Kassierer" if preview else ""),
        left_role,
        receipt.treasurer_signed_at,
    )
    if receipt.no_signature_reason:
        right = [
            Spacer(box_w, box_h),
            Paragraph(
                f"{escape(right_role)}<br/>{escape(receipt.counterparty_name)}: ohne Unterschrift "
                f"({escape(receipt.no_signature_reason)})",
                st["small"],
            ),
        ]
    else:
        right = cell(
            receipt.counterparty_signature,
            receipt.counterparty_name,
            right_role,
            receipt.counterparty_signed_at,
        )
    table = Table(
        [[left[0], right[0]], [left[1], right[1]]],
        colWidths=[85 * mm, 85 * mm],
        hAlign="LEFT",
        style=[
            ("LINEABOVE", (0, 1), (0, 1), 0.5, line),
            ("LINEABOVE", (1, 1), (1, 1), 0.5, line),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ],
    )
    return KeepTogether(table)


def cash_receipt_story(receipt, *, cancelled: bool = False) -> tuple[list, object]:
    """Quittung ohne oder mit Rechnung, Richtung Verein erhält oder zahlt."""
    from finance.words import euro_words

    org = receipt.organization
    data = _letter(org)
    st = text_styles(data)
    primary = colors.HexColor(data.primary)
    final = receipt.status != receipt.Status.DRAFT
    when = receipt.finalized_at or timezone.now()
    meta = [("Beleg-Nr.", receipt.number if final else "Entwurf")]
    if receipt.receipt_date:
        meta.append(("Datum", f"{receipt.receipt_date:%d.%m.%Y}"))
    if final:
        meta.append(("abgeschlossen", f"{timezone.localtime(when):%d.%m.%Y %H:%M} Uhr"))
    if receipt.invoice_id:
        meta.append(("Rechnung", receipt.invoice.display_number))
    membership = receipt.membership
    if membership is not None and membership.club_number:
        meta.append(("Mitgliedsnr.", membership.club_number))
    meta += _contact_rows(data)
    cfg = BillingSettings.objects.filter(organization=org).first()
    if cfg is not None and cfg.tax_number:
        meta.append(("Steuernummer", cfg.tax_number))
    recipient = (receipt.counterparty_name + "\n" + receipt.counterparty_address).splitlines()
    story: list = LetterDocument.start(data, recipient, meta, True)
    title = "Quittung"
    if not final:
        title = "Quittung (Entwurf, noch nicht gültig)"
    story.append(Paragraph(title, st["title"]))
    if cancelled and receipt.status == receipt.Status.CANCELLED:
        story.append(
            Paragraph(
                f"<b>STORNIERT</b> am {timezone.localtime(receipt.cancelled_at):%d.%m.%Y} "
                f"(Gegenbuchung {escape(receipt.cancel_booking.display_number)}). "
                f"Grund: {escape(receipt.cancel_reason)}",
                ParagraphStyle("storno", parent=st["normal"], textColor=colors.HexColor("#b00020")),
            )
        )
    story.append(Spacer(1, 5 * mm))
    who = escape(receipt.counterparty_name)
    rows = [
        ("Betrag", f"<b>{euro(receipt.amount)}</b>"),
        ("in Worten", escape(euro_words(receipt.amount))),
        ("erhalten von" if receipt.receives else "ausgezahlt an", who),
        ("für", escape(receipt.purpose)),
        ("Zahlungsweg", "bar"),
    ]
    table = Table(
        [[Paragraph(k, st["normal"]), Paragraph(v, st["normal"])] for k, v in rows],
        colWidths=[35 * mm, None],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, primary),
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, primary),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    if receipt.vat_rate:
        rate = receipt.vat_rate
        vat = included_vat(receipt.amount, rate)
        note = f"Im Betrag sind {_rate(rate)} Umsatzsteuer ({euro(vat)}) enthalten."
    else:
        note = "Der Betrag enthält keine Umsatzsteuer."
    story.append(Paragraph(escape(note), st["small"]))
    story.append(Spacer(1, 14 * mm))
    story.append(signature_block(receipt, st, preview=not final))
    story.append(Spacer(1, 8 * mm))
    foot = "Elektronisch erstellt mit HUBIplan, unterschrieben auf dem Bildschirm"
    if receipt.source:
        foot += f" ({receipt.source})"
    foot += "."
    story.append(Paragraph(escape(foot), st["small"]))
    return story, data


def render_cash_receipt(receipt, *, cancelled: bool = False) -> bytes:
    buf = io.BytesIO()
    story, data = cash_receipt_story(receipt, cancelled=cancelled)
    title = f"Quittung {receipt.number}" if receipt.number else "Quittung (Entwurf)"
    LetterDocument(buf, [data], title=title, author=receipt.organization.name).build(story)
    return buf.getvalue()


def cash_receipt_filename(receipt, *, cancelled: bool = False) -> str:
    number = (receipt.number or f"Entwurf-{receipt.pk}").replace("/", "-")
    return f"Quittung-{number}{'-Storno' if cancelled else ''}.pdf"
