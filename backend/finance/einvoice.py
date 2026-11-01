"""E-Rechnungen lesen: XRechnung/UBL, UN/CEFACT CII und ZUGFeRD/Factur-X (Finanzamt-Prüfung B1).

Seit 2025 müssen Unternehmer E-Rechnungen empfangen können, also auch Vereine mit
wirtschaftlichem Geschäftsbetrieb. Maßgeblich ist das XML; es wird unverändert als Beleg
aufbewahrt. Hier werden nur die Angaben für einen Buchungsvorschlag und eine lesbare
Ansicht herausgelesen.
"""

from __future__ import annotations

import datetime
import io
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from django.utils.translation import gettext

MAX_XML = 5 * 1024 * 1024


class EInvoiceError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(node, *names):
    """Pfad über lokale Namen (Namensräume egal); None, wenn ein Teil fehlt."""
    for name in names:
        if node is None:
            return None
        node = next((c for c in node if _local(c.tag) == name), None)
    return node


def _children(node, name):
    return [c for c in node if _local(c.tag) == name] if node is not None else []


def _text(node, *names) -> str:
    found = _child(node, *names)
    return " ".join((found.text or "").split()) if found is not None else ""


def _amount(node, *names) -> Decimal | None:
    raw = _text(node, *names)
    try:
        return Decimal(raw) if raw else None
    except InvalidOperation:
        return None


def _date(raw: str) -> datetime.date | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(raw[:10] if "-" in raw else raw[:8], fmt).date()
        except ValueError:
            continue
    return None


def _root(data: bytes):
    if len(data) > MAX_XML:
        raise EInvoiceError(gettext("Die XML-Datei ist größer als 5 MB."))
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise EInvoiceError(
            gettext("Die Datei enthält eine DTD und wird aus Sicherheitsgründen abgelehnt.")
        )
    try:
        return ET.fromstring(data)  # noqa: S314 - DTD/Entitäten oben abgewiesen
    except ET.ParseError:
        raise EInvoiceError(gettext("Die Datei ist kein gültiges XML.")) from None


def _ubl(root) -> dict:
    credit = _local(root.tag) == "CreditNote"
    supplier = _child(root, "AccountingSupplierParty", "Party")
    customer = _child(root, "AccountingCustomerParty", "Party")
    totals = _child(root, "LegalMonetaryTotal")

    def party_name(party) -> str:
        return (
            _text(party, "PartyLegalEntity", "RegistrationName")
            or _text(party, "PartyName", "Name")
            or ""
        )

    lines = []
    for line in _children(root, "CreditNoteLine" if credit else "InvoiceLine"):
        qty = _child(line, "CreditedQuantity" if credit else "InvoicedQuantity")
        lines.append(
            {
                "text": _text(line, "Item", "Name") or _text(line, "Item", "Description"),
                "quantity": " ".join((qty.text or "").split()) if qty is not None else "",
                "unit": qty.get("unitCode", "") if qty is not None else "",
                "amount": _amount(line, "LineExtensionAmount"),
            }
        )
    iban = ""
    for means in _children(root, "PaymentMeans"):
        iban = _text(means, "PayeeFinancialAccount", "ID")
        if iban:
            break
    return {
        "format": "XRechnung (UBL)",
        "credit_note": credit,
        "number": _text(root, "ID"),
        "date": _date(_text(root, "IssueDate")),
        "due_date": _date(_text(root, "DueDate"))
        or _date(_text(root, "PaymentMeans", "PaymentDueDate")),
        "currency": _text(root, "DocumentCurrencyCode") or "EUR",
        "seller": party_name(supplier),
        "seller_vat_id": _text(supplier, "PartyTaxScheme", "CompanyID"),
        "buyer": party_name(customer),
        "net": _amount(totals, "TaxExclusiveAmount"),
        "tax": _amount(root, "TaxTotal", "TaxAmount"),
        "gross": _amount(totals, "TaxInclusiveAmount"),
        "payable": _amount(totals, "PayableAmount"),
        "iban": iban,
        "buyer_reference": _text(root, "BuyerReference"),
        "lines": lines,
    }


def _cii(root) -> dict:
    doc = _child(root, "ExchangedDocument")
    trade = _child(root, "SupplyChainTradeTransaction")
    agreement = _child(trade, "ApplicableHeaderTradeAgreement")
    settlement = _child(trade, "ApplicableHeaderTradeSettlement")
    totals = _child(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation")
    lines = []
    for item in _children(trade, "IncludedSupplyChainTradeLineItem"):
        qty = _child(item, "SpecifiedLineTradeDelivery", "BilledQuantity")
        lines.append(
            {
                "text": _text(item, "SpecifiedTradeProduct", "Name"),
                "quantity": " ".join((qty.text or "").split()) if qty is not None else "",
                "unit": qty.get("unitCode", "") if qty is not None else "",
                "amount": _amount(
                    item,
                    "SpecifiedLineTradeSettlement",
                    "SpecifiedTradeSettlementLineMonetarySummation",
                    "LineTotalAmount",
                ),
            }
        )
    iban = ""
    for means in _children(settlement, "SpecifiedTradeSettlementPaymentMeans"):
        iban = _text(means, "PayeePartyCreditorFinancialAccount", "IBANID")
        if iban:
            break
    seller = _child(agreement, "SellerTradeParty")
    vat = ""
    for reg in _children(seller, "SpecifiedTaxRegistration"):
        found = _child(reg, "ID")
        if found is not None and found.get("schemeID") == "VA":
            vat = (found.text or "").strip()
    return {
        "format": "ZUGFeRD/Factur-X (CII)",
        "credit_note": _text(doc, "TypeCode") == "381",
        "number": _text(doc, "ID"),
        "date": _date(_text(doc, "IssueDateTime", "DateTimeString")),
        "due_date": _date(
            _text(settlement, "SpecifiedTradePaymentTerms", "DueDateDateTime", "DateTimeString")
        ),
        "currency": _text(settlement, "InvoiceCurrencyCode") or "EUR",
        "seller": _text(seller, "Name"),
        "seller_vat_id": vat,
        "buyer": _text(agreement, "BuyerTradeParty", "Name"),
        "net": _amount(totals, "TaxBasisTotalAmount"),
        "tax": _amount(totals, "TaxTotalAmount"),
        "gross": _amount(totals, "GrandTotalAmount"),
        "payable": _amount(totals, "DuePayableAmount") or _amount(totals, "GrandTotalAmount"),
        "iban": iban,
        "buyer_reference": _text(agreement, "BuyerReference"),
        "lines": lines,
    }


def parse_xml(data: bytes) -> dict:
    root = _root(data)
    name = _local(root.tag)
    if name in ("Invoice", "CreditNote"):
        result = _ubl(root)
    elif name == "CrossIndustryInvoice":
        result = _cii(root)
    else:
        raise EInvoiceError(
            gettext(
                "Keine E-Rechnung erkannt. Unterstützt werden XRechnung (UBL oder CII) und ZUGFeRD."
            )
        )
    if not result["number"] or result["payable"] is None:
        raise EInvoiceError(
            gettext("Die E-Rechnung enthält keine Rechnungsnummer oder keinen Betrag.")
        )
    return result


def xml_from_pdf(data: bytes) -> bytes | None:
    """Eingebettetes XML einer ZUGFeRD/Factur-X-PDF (oder None)."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:  # noqa: BLE001 - kaputte PDF: einfach keine E-Rechnung
        return None
    try:
        found = None
        for i in range(pdf.count_attachments()):
            attachment = pdf.get_attachment(i)
            name = (attachment.get_name() or "").lower()
            if name.endswith(".xml"):
                content = bytes(attachment.get_data())
                if name in ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml"):
                    return content
                found = found or content
        return found
    finally:
        pdf.close()


def read(data: bytes, content_type: str) -> dict | None:
    """Angaben einer E-Rechnung (XML oder PDF mit XML); None bei einer PDF ohne E-Rechnung."""
    if content_type == "application/pdf":
        embedded = xml_from_pdf(data)
        if embedded is None:
            return None
        try:
            return parse_xml(embedded)
        except EInvoiceError:
            return None
    return parse_xml(data)


def as_json(info: dict) -> dict:
    """Für die API und das Speichern am Beleg: Beträge als Text, Daten ISO."""

    def conv(value):
        if isinstance(value, Decimal):
            return f"{value:.2f}"
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, list):
            return [conv(v) for v in value]
        if isinstance(value, dict):
            return {k: conv(v) for k, v in value.items()}
        return value

    return conv(info)


def render(info: dict, org_name: str) -> bytes:
    """Lesbare Ansicht (PDF) einer E-Rechnung; maßgeblich bleibt das XML."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from .report import _euro, _styles, _table

    st = _styles()
    r, rb = st["right"], st["right_bold"]
    grey = colors.HexColor("#555555")

    def money(value) -> str:
        return _euro(value) if value not in (None, "") else ""

    title = "Gutschrift" if info.get("credit_note") else "Rechnung"
    story: list = [
        Paragraph(f"<b>{title} {escape(info.get('number') or '')}</b>", st["title"]),
        Paragraph(
            f"Lesbare Ansicht einer E-Rechnung ({escape(info.get('format') or '')}) für "
            f"{escape(org_name)}. Maßgeblich ist die XML-Datei.",
            st["small"],
        ),
        Spacer(1, 4 * mm),
    ]
    facts = [
        ("Rechnungssteller", info.get("seller")),
        ("USt-IdNr.", info.get("seller_vat_id")),
        ("Empfänger", info.get("buyer")),
        ("Rechnungsdatum", _de(info.get("date"))),
        ("fällig am", _de(info.get("due_date"))),
        ("IBAN", info.get("iban")),
        ("Käuferreferenz", info.get("buyer_reference")),
    ]
    for label, value in facts:
        if value:
            story.append(Paragraph(f"<b>{label}:</b> {escape(str(value))}", st["normal"]))
    if info.get("lines"):
        story.append(Paragraph("<b>Positionen</b>", st["h2"]))
        rows = [
            [
                Paragraph("<b>Bezeichnung</b>", st["normal"]),
                Paragraph("<b>Menge</b>", r),
                Paragraph("<b>Betrag</b>", r),
            ]
        ]
        for line in info["lines"]:
            rows.append(
                [
                    Paragraph(escape(line.get("text") or ""), st["normal"]),
                    Paragraph(escape(f"{line.get('quantity', '')} {line.get('unit', '')}"), r),
                    Paragraph(money(line.get("amount")), r),
                ]
            )
        story.append(_table(rows, [100 * mm, 30 * mm, 35 * mm], grey, total_row=False))
    story.append(Paragraph("<b>Summen</b>", st["h2"]))
    rows = [
        [Paragraph(label, st["normal"]), Paragraph(money(info.get(key)), style)]
        for label, key, style in [
            ("netto", "net", r),
            ("Umsatzsteuer", "tax", r),
            ("brutto", "gross", r),
            ("<b>zu zahlen</b>", "payable", rb),
        ]
        if info.get(key) not in (None, "")
    ]
    story.append(_table(rows, [60 * mm, 35 * mm], grey))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm).build(story)
    return buf.getvalue()


def _de(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.date.fromisoformat(value)
    return f"{value:%d.%m.%Y}"
