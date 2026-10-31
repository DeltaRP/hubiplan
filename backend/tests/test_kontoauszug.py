"""Kontoauszug im Format CAMT.053 einlesen, zuordnen und buchen."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime
import io
import zipfile
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from billing.models import DebitRun, Invoice, Mandate
from core.rls import APP_ROLE
from core.tenancy import set_rls, tenant_context
from finance import camt
from finance.models import BankLine, Booking

from .test_app_verwaltung_b5 import offen  # noqa: F401
from .test_m9_billing import JSON, base, c, club, members, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db

IBAN = "DE89370400440532013000"  # Girokonto aus setup


def entry(
    amount,
    credit=True,
    *,
    date="2025-03-03",
    name="Erika Muster",
    iban="DE02120300000000202051",
    purpose="",
    ref="",
    e2e="",
    ret="",
    status="BOOK",
):
    role = "Dbtr" if credit else "Cdtr"
    rtr = f"<RtrInf><Rsn><Cd>{ret}</Cd></Rsn></RtrInf>" if ret else ""
    return f"""
      <Ntry>
        <Amt Ccy="EUR">{amount}</Amt>
        <CdtDbtInd>{"CRDT" if credit else "DBIT"}</CdtDbtInd>
        <Sts><Cd>{status}</Cd></Sts>
        <BookgDt><Dt>{date}</Dt></BookgDt>
        <ValDt><Dt>{date}</Dt></ValDt>
        <AcctSvcrRef>{ref}</AcctSvcrRef>
        <NtryDtls><TxDtls>
          <Refs><EndToEndId>{e2e or "NOTPROVIDED"}</EndToEndId></Refs>
          <RltdPties><{role}><Nm>{name}</Nm></{role}><{role}Acct><Id><IBAN>{iban}</IBAN></Id></{role}Acct></RltdPties>
          <RmtInf><Ustrd>{purpose}</Ustrd></RmtInf>
          {rtr}
        </TxDtls></NtryDtls>
      </Ntry>"""


def camt_xml(entries, *, iban=IBAN, opening="0.00", closing=None, version="08"):
    closing_xml = (
        f"""<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{closing}</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2025-03-31</Dt></Dt></Bal>"""
        if closing is not None
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.{version}">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>M1</MsgId><CreDtTm>2025-04-01T08:00:00</CreDtTm></GrpHdr>
    <Stmt>
      <Id>2025-03</Id>
      <FrToDt><FrDtTm>2025-03-01T00:00:00</FrDtTm><ToDtTm>2025-03-31T23:59:59</ToDtTm></FrToDt>
      <Acct><Id><IBAN>{iban}</IBAN></Id><Ccy>EUR</Ccy></Acct>
      <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{opening}</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2025-03-01</Dt></Dt></Bal>
      {closing_xml}
      {"".join(entries)}
    </Stmt>
  </BkToCstmrStmt>
</Document>""".encode()


@pytest.fixture
def fin(club, setup):
    return f"/api/orgs/{club.pk}/finance"


def upload(c, fin, data, name="auszug.xml", **extra):
    return c.post(
        f"{fin}/bank-statements/",
        {"file": SimpleUploadedFile(name, data, content_type="application/xml"), **extra},
    )


def lines(c, fin, **params):
    return c.get(f"{fin}/bank-lines/", params).json()["results"]


class TestLesen:
    def test_versionen_und_vorgemerkte(self):
        data = camt_xml(
            [entry("10.00"), entry("5.00", False, name="Bäcker"), entry("7.00", status="PDNG")],
            version="02",
        )
        st = camt.parse(data)[0]
        assert st.iban == IBAN and st.ref == "2025-03"
        assert [(str(x.amount), x.credit) for x in st.lines] == [("10.00", True), ("5.00", False)]
        assert st.lines[1].name == "Bäcker"
        assert st.date_from == datetime.date(2025, 3, 1)

    def test_zip_und_dtd(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.xml", camt_xml([entry("1.00")]))
            z.writestr("b.xml", camt_xml([entry("2.00")]))
        assert len(camt.parse(buf.getvalue())) == 2
        evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Document/>'
        with pytest.raises(camt.CamtError):
            camt.parse(evil)
        with pytest.raises(camt.CamtError, match="CAMT.052"):
            camt.parse(b"<Document><BkToCstmrAcctRpt/></Document>")

    def test_rechnungsnummern(self):
        assert camt.invoice_numbers("Beitrag R2025-0007 und R 2025/26 - 12") == [
            (2025, 7),
            (2025, 12),
        ]


class TestEinlesen:
    def test_rechnung_ueber_nummer_und_doppelt(self, c, fin, offen):
        number = offen.display_number
        data = camt_xml(
            [
                entry("60.00", purpose=f"Mitgliedsbeitrag {number}", ref="A1"),
                entry("12.30", False, name="Druckerei", purpose="Plakate", ref="A2"),
            ],
            closing="47.70",
        )
        resp = upload(c, fin, data)
        assert resp.status_code == 201, resp.json()
        assert resp.json()["lines"] == 2
        rows = lines(c, fin)
        pay = next(r for r in rows if r["credit"])
        assert pay["suggestion"] == "invoice"
        assert pay["suggested"]["invoice"]["number"] == number
        # Dieselbe Datei noch einmal: nichts doppelt
        again = upload(c, fin, data).json()
        assert again["lines"] == 0 and again["duplicates"] == 2
        # Vorschlag übernehmen: Rechnung bezahlt, Buchung im Kassenbuch
        resp = c.post(
            f"{fin}/bank-lines/{pay['id']}/assign/", {"action": "suggestion"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "done" and resp.json()["booking_number"]
        offen.refresh_from_db()
        with tenant_context(offen.organization_id):
            assert Invoice.objects.get(pk=offen.pk).outstanding == Decimal("0")
        # Ausgabe mit Kategorie buchen
        out = next(r for r in rows if not r["credit"])
        cat = c.post(
            f"{fin}/categories/", {"name": "Werbung", "kind": "expense"}, content_type=JSON
        ).json()
        resp = c.post(
            f"{fin}/bank-lines/{out['id']}/assign/",
            {"action": "booking", "category": cat["id"]},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        with tenant_context(offen.organization_id):
            b = Booking.objects.get(pk=resp.json()["booking"])
        assert b.kind == "expense" and b.counterparty == "Druckerei" and b.text == "Plakate"
        # Saldo stimmt jetzt mit dem Kassenbuch überein
        st = c.get(f"{fin}/bank-statements/").json()["results"]
        first = [s for s in st if s["line_count"] == 2][0]
        assert first["balance"]["ok"] is True and first["open_count"] == 0
        # erledigt: nicht noch einmal
        again = c.post(
            f"{fin}/bank-lines/{pay['id']}/assign/", {"action": "ignore"}, content_type=JSON
        )
        assert again.status_code == 400

    def test_rechnung_ueber_mandat(self, c, fin, offen, members, club):
        with tenant_context(club.pk):
            Mandate.objects.create(
                organization=club,
                membership=members["erika"],
                reference="M-1",
                holder="Erika Muster",
                iban="DE02120300000000202051",
                signed_on=datetime.date(2024, 1, 1),
                source="paper",
            )
        upload(c, fin, camt_xml([entry("60.00", purpose="Beitrag", ref="B1")]))
        row = lines(c, fin)[0]
        assert row["suggestion"] == "invoice"
        assert row["suggested"]["membership"]["name"] == "Erika Muster"

    def test_schon_gebucht(self, c, fin, setup):
        b = c.post(
            f"{fin}/bookings/",
            {
                "date": "2025-03-02",
                "kind": "income",
                "amount": "25.00",
                "account": setup["bank"],
                "category": setup["cat"],
                "text": "Spende bar eingezahlt",
                "counterparty": "Erika Muster",
            },
            content_type=JSON,
        ).json()
        upload(c, fin, camt_xml([entry("25.00", ref="C1")]))
        row = lines(c, fin)[0]
        assert row["suggestion"] == "booked" and row["suggested"]["booking"]["id"] == b["id"]
        result = c.post(f"{fin}/bank-lines/apply-suggestions/", {}, content_type=JSON).json()
        assert result == {"done": 1, "failed": []}
        assert lines(c, fin)[0]["booking"] == b["id"]

    def test_lastschriftlauf(self, c, fin, club, setup):
        with tenant_context(club.pk):
            run = DebitRun.objects.create(
                organization=club,
                collection_date=datetime.date(2025, 3, 5),
                account_id=setup["bank"],
                message_id="HUBI-1",
                total=Decimal("0.00"),
            )
        DebitRun.objects.filter(pk=run.pk).update(total=Decimal("180.00"))
        upload(c, fin, camt_xml([entry("180.00", name="", purpose="SEPA-Sammler", ref="D1")]))
        row = lines(c, fin)[0]
        assert row["suggestion"] == "debit_run" and row["suggested"]["run"]["id"] == run.pk

    def test_uebergehen_und_wieder_oeffnen(self, c, fin):
        upload(
            c, fin, camt_xml([entry("3.50", False, name="Bank", purpose="Kontoführung", ref="E1")])
        )
        row = lines(c, fin)[0]
        url = f"{fin}/bank-lines/{row['id']}/assign/"
        assert c.post(url, {"action": "ignore"}, content_type=JSON).json()["status"] == "ignored"
        assert c.post(url, {"action": "reopen"}, content_type=JSON).json()["status"] == "open"

    def test_falsches_konto(self, c, fin, setup):
        data = camt_xml([entry("1.00")], iban="DE44500105175407324931")
        resp = upload(c, fin, data)
        assert resp.status_code == 400 and "account" in resp.json()
        resp = upload(c, fin, data, account=setup["bank"])
        assert resp.status_code == 400
        resp = upload(c, fin, data, account=setup["cash"])  # Barkasse ohne IBAN: erlaubt
        assert resp.status_code == 201

    def test_auszug_loeschen_nur_ohne_buchungen(self, c, fin, setup):
        st = upload(c, fin, camt_xml([entry("4.00", ref="F1")])).json()["statements"][0]
        assert c.delete(f"{fin}/bank-statements/{st['id']}/").status_code == 204
        with tenant_context(setup["aktiv"].organization_id):
            assert BankLine.objects.count() == 0

    def test_nur_lesen(self, c, fin, club, api):
        from .factories import give_role, make_user

        reader = make_user("pruefer@example.org")
        give_role(reader, club, ["finance.view"], name="Prüfer")
        r = api(reader)
        assert r.get(f"{fin}/bank-lines/").status_code == 200
        assert upload(r, fin, camt_xml([entry("1.00")])).status_code == 403


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_rls_kontoauszug(c, fin, club, orgs):
    upload(c, fin, camt_xml([entry("1.00", ref="G1")]))
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        set_rls(orgs["b"].pk)
        assert BankLine.objects.count() == 0
        set_rls(club.pk)
        assert BankLine.objects.count() == 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)
