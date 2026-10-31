"""Finanzamt-Prüfung B1: E-Rechnungen (XRechnung/UBL, CII, ZUGFeRD) als Beleg (erfundene Daten)."""
# ruff: noqa: F811, E501  (Fixtures als Parameter, XML-Beispiele)

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from finance import einvoice
from finance.models import Receipt

from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db

UBL = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>RE-2025-0815</cbc:ID>
  <cbc:IssueDate>2025-07-14</cbc:IssueDate>
  <cbc:DueDate>2025-07-28</cbc:DueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>04011000-12345-67</cbc:BuyerReference>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Musterbrauerei</cbc:Name></cac:PartyName>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Musterbrauerei GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyLegalEntity><cbc:RegistrationName>Schützenverein Musterstadt</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount><cbc:ID>DE02120300000000202051</cbc:ID></cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">95.00</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="EUR">500.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">595.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">595.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="H87">10</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">500.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Fass Pils 50 l</cbc:Name></cac:Item>
  </cac:InvoiceLine>
</Invoice>""".encode()

CII = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument><ram:ID>ZV-77</ram:ID><ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20250701</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Festzelt 3 Tage</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="DAY">3</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation>
        <ram:LineTotalAmount>1200.00</ram:LineTotalAmount>
      </ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>Zeltverleih Beispiel</ram:Name>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE987654321</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Schützenverein Musterstadt</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>1200.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">228.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>1428.00</ram:GrandTotalAmount>
        <ram:DuePayableAmount>1428.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>""".encode()


def simple_pdf() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    page = canvas.Canvas(buf)
    page.drawString(100, 700, "Rechnung")
    page.showPage()
    page.save()
    return buf.getvalue()


def zugferd_pdf(xml: bytes) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(simple_pdf())
    attachment = pdf.new_attachment("factur-x.xml")
    attachment.set_data(xml)
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


class TestLesen:
    def test_ubl(self):
        info = einvoice.parse_xml(UBL)
        assert info["number"] == "RE-2025-0815" and info["seller"] == "Musterbrauerei GmbH"
        assert info["payable"] == Decimal("595.00") and info["tax"] == Decimal("95.00")
        assert info["iban"] == "DE02120300000000202051"
        assert info["lines"][0]["text"] == "Fass Pils 50 l"

    def test_cii(self):
        info = einvoice.parse_xml(CII)
        assert info["number"] == "ZV-77" and info["seller"] == "Zeltverleih Beispiel"
        assert str(info["date"]) == "2025-07-01" and info["payable"] == Decimal("1428.00")
        assert info["seller_vat_id"] == "DE987654321"

    def test_zugferd_pdf(self):
        info = einvoice.read(zugferd_pdf(CII), "application/pdf")
        assert info["number"] == "ZV-77"

    def test_pdf_ohne_xml(self):
        assert einvoice.read(simple_pdf(), "application/pdf") is None

    def test_abgelehnt(self):
        with pytest.raises(einvoice.EInvoiceError, match="DTD"):
            einvoice.parse_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Invoice/>')
        with pytest.raises(einvoice.EInvoiceError, match="Keine E-Rechnung"):
            einvoice.parse_xml(b"<Document/>")

    def test_ansicht(self):
        pdf = einvoice.render(einvoice.as_json(einvoice.parse_xml(UBL)), "Verein")
        assert pdf.startswith(b"%PDF")


def test_vorschlag_und_beleg(c, fin, setup):
    resp = c.post(
        f"{fin}/einvoice/",
        {"file": SimpleUploadedFile("rechnung.xml", UBL, content_type="application/xml")},
    )
    assert resp.status_code == 200, resp.json()
    s = resp.json()["suggestion"]
    assert s == {
        "kind": "expense",
        "date": "2025-07-14",
        "amount": "595.00",
        "counterparty": "Musterbrauerei GmbH",
        "reference": "RE-2025-0815",
        "text": "Rechnung RE-2025-0815 Musterbrauerei GmbH",
    }
    cat = c.post(
        f"{fin}/categories/", {"name": "Getränkeeinkauf", "kind": "expense"}, content_type=JSON
    ).json()["id"]
    c.post(
        f"{fin}/bookings/",
        {
            "date": "2025-07-01",
            "kind": "income",
            "amount": "1000",
            "account": setup["bank"],
            "category": setup["cat"],
            "text": "Einlage",
        },
        content_type=JSON,
    )
    booking = c.post(
        f"{fin}/bookings/",
        {**s, "account": setup["bank"], "category": cat},
        content_type=JSON,
    )
    assert booking.status_code == 201, booking.json()
    up = c.post(
        f"{fin}/bookings/{booking.json()['id']}/receipts/",
        {"file": SimpleUploadedFile("rechnung.xml", UBL, content_type="text/xml")},
    )
    assert up.status_code == 201, up.json()
    assert up.json()["content_type"] == "application/xml"
    assert up.json()["einvoice"]["number"] == "RE-2025-0815"
    receipt = Receipt.objects.get()
    with receipt.file.open("rb") as fh:
        assert fh.read() == UBL  # Original unverändert
    raw = c.get(f"{fin}/receipts/{receipt.pk}/")
    assert "attachment" in raw["Content-Disposition"]
    view = c.get(f"{fin}/receipts/{receipt.pk}/?ansicht=1")
    assert view["Content-Type"] == "application/pdf"


def test_beliebiges_xml_wird_abgelehnt(c, fin, setup):
    booking = c.post(
        f"{fin}/bookings/",
        {
            "date": "2025-07-01",
            "kind": "income",
            "amount": "10",
            "account": setup["bank"],
            "category": setup["cat"],
            "text": "x",
        },
        content_type=JSON,
    ).json()["id"]
    resp = c.post(
        f"{fin}/bookings/{booking}/receipts/",
        {"file": SimpleUploadedFile("x.xml", b"<html/>", content_type="application/xml")},
    )
    assert resp.status_code == 400 and "Keine E-Rechnung" in str(resp.json())
