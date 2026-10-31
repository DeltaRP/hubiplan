"""Meilenstein 11: SEPA-Mandate, Lastschriftlauf (pain.008), Kassenbericht, Jahresabschluss."""

import datetime
import uuid
from xml.etree import ElementTree as ET

import pytest
from django.core import mail
from django.utils import timezone

from billing import sepa
from billing.models import Invoice, Mandate
from core.tenancy import tenant_context
from finance.models import Booking
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
CREDITOR = "DE98ZZZ09999999999"
NS = {"p": sepa.NS}


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.enabled_modules = ["finance", "members", "billing"]
    club.member_portal_enabled = True
    club.save()
    return club


@pytest.fixture
def c(api, board_a):
    return api(board_a)


@pytest.fixture
def base(club):
    return f"/api/orgs/{club.pk}/billing"


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def setup(c, base, fin):
    bank = c.post(
        f"{fin}/accounts/",
        {
            "name": "Girokonto",
            "iban": "DE89370400440532013000",
            "bic": "COBADEFFXXX",
            "opening_date": "2024-01-01",
        },
        content_type=JSON,
    ).json()["id"]
    cat = c.post(
        f"{fin}/categories/", {"name": "Mitgliedsbeiträge", "kind": "income"}, content_type=JSON
    ).json()["id"]
    resp = c.patch(
        f"{base}/settings/",
        {
            "account": bank,
            "category": cat,
            "sepa_enabled": True,
            "creditor_id": CREDITOR,
            "prenotification_days": 5,
        },
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()
    return {"bank": bank, "cat": cat}


def open_invoice(c, base, member, amount="60.00"):
    resp = c.post(
        f"{base}/invoices/",
        {
            "recipient_kind": "member",
            "membership": member.pk,
            "subject": "Mitgliedsbeitrag",
            "lines": [{"text": "Beitrag", "amount": amount}],
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    pk = resp.json()["id"]
    assert c.post(f"{base}/invoices/{pk}/finalize/").status_code == 200
    return pk


def next_workday(days: int) -> datetime.date:
    d = timezone.localdate() + datetime.timedelta(days=days)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d


class TestPruefungen:
    def test_glaeubiger_id(self):
        assert sepa.creditor_id_valid(CREDITOR)
        assert sepa.creditor_id_valid("DE98 ZZZ0 9999 9999 99".replace(" ", ""))
        assert not sepa.creditor_id_valid("DE97ZZZ09999999999")
        assert not sepa.creditor_id_valid("")

    def test_sepa_text(self):
        assert sepa.sepa_text("Jägerzug Grüße & Co.", 70) == "Jaegerzug Gruesse Co."

    def test_ungueltige_glaeubiger_id_wird_abgelehnt(self, c, base, setup):
        resp = c.patch(f"{base}/settings/", {"creditor_id": "DE00ZZZ1"}, content_type=JSON)
        assert resp.status_code == 400


class TestMandate:
    def test_papiermandat_ersetzt_altes(self, c, base, setup, club):
        erika = make_member(club, "Erika", "Muster")
        data = {
            "membership": erika.pk,
            "holder": "Erika Muster",
            "iban": "DE02 1203 0000 0000 2020 51",
            "signed_on": "2025-01-10",
        }
        first = c.post(f"{base}/mandates/", data, content_type=JSON)
        assert first.status_code == 201, first.json()
        assert first.json()["reference"].startswith("MITGL-")
        assert first.json()["iban"] == "DE02120300000000202051"
        second = c.post(f"{base}/mandates/", data, content_type=JSON).json()
        assert second["reference"] != first.json()["reference"]
        statuses = {
            m["reference"]: m["status"] for m in c.get(f"{base}/mandates/").json()["results"]
        }
        assert statuses == {first.json()["reference"]: "revoked", second["reference"]: "active"}
        bad = c.post(f"{base}/mandates/", {**data, "iban": "DE00123"}, content_type=JSON)
        assert bad.status_code == 400
        assert "iban" in bad.json()

    def test_mandat_im_mitgliederbereich(self, c, base, setup, club, api):
        erika = make_member(club, "Erika", "Muster", "erika@example.org")
        c.post(f"/api/orgs/{club.pk}/members/{erika.pk}/access/")
        access = PortalAccess.objects.get(membership=erika)
        me = api(access.user)
        url = f"/api/portal/{access.pk}/mandate/"
        data = me.get(url).json()
        assert data["available"] is True
        assert data["mandate"] is None
        assert "Ich ermächtige Verein A" in data["text"]
        refused = me.post(
            url, {"holder": "Erika Muster", "iban": "DE02120300000000202051"}, content_type=JSON
        )
        assert refused.status_code == 400
        resp = me.post(
            url,
            {"holder": "Erika Muster", "iban": "DE02120300000000202051", "consent": True},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert resp.json()["mandate"]["source"] == "online"
        assert any("SEPA-Lastschriftmandat" in m.subject for m in mail.outbox)
        # Andere Mitglieder sehen es nicht, der Verein schon
        assert c.get(f"{base}/mandates/?mitglied={erika.pk}").json()["count"] == 1
        resp = me.delete(url)
        assert resp.json()["mandate"] is None
        with tenant_context(club.pk):
            assert Mandate.objects.get(membership=erika).status == "revoked"

    def test_ohne_glaeubiger_id_kein_mandat_im_mitgliederbereich(self, c, club, api):
        erika = make_member(club, "Erika", "Muster", "erika@example.org")
        c.post(f"/api/orgs/{club.pk}/members/{erika.pk}/access/")
        access = PortalAccess.objects.get(membership=erika)
        me = api(access.user)
        assert me.get(f"/api/portal/{access.pk}/mandate/").json()["available"] is False

    def test_ausgeschaltet_verschwindet_alles(self, c, base, setup, club, api):
        erika = make_member(club, "Erika", "Muster", "erika@example.org")
        c.post(f"/api/orgs/{club.pk}/members/{erika.pk}/access/")
        access = PortalAccess.objects.get(membership=erika)
        orgs = {o["id"]: o for o in c.get("/api/me/organizations/").json()}
        assert orgs[club.pk]["sepa_enabled"] is True

        resp = c.patch(f"{base}/settings/", {"sepa_enabled": False}, content_type=JSON)
        assert resp.status_code == 200
        assert resp.json()["sepa_enabled"] is False
        orgs = {o["id"]: o for o in c.get("/api/me/organizations/").json()}
        assert orgs[club.pk]["sepa_enabled"] is False
        assert c.get(f"{base}/mandates/").status_code == 404
        assert c.get(f"{base}/debits/").status_code == 404
        assert c.get(f"{base}/debits/proposals/").status_code == 404
        overview = c.get(f"{base}/overview/").json()
        assert overview["sepa_enabled"] is False
        assert overview["debits_ready"] == 0
        me = api(access.user)
        assert me.get(f"/api/portal/{access.pk}/mandate/").json()["available"] is False


class TestLastschrift:
    def test_lauf_datei_und_buchung(self, c, base, setup, club):
        erika = make_member(club, "Erika", "Müller", "erika@example.org")
        otto = make_member(club, "Otto", "Ohnemail")
        ohne = make_member(club, "Uwe", "Ueberweiser")
        for m, holder in [(erika, "Erika Müller"), (otto, "Otto Ohnemail")]:
            c.post(
                f"{base}/mandates/",
                {
                    "membership": m.pk,
                    "holder": holder,
                    "iban": "DE02120300000000202051",
                    "signed_on": "2025-01-10",
                },
                content_type=JSON,
            )
        inv_e = open_invoice(c, base, erika)
        inv_o = open_invoice(c, base, otto, "30.00")
        open_invoice(c, base, ohne)
        with tenant_context(club.pk):
            Invoice.objects.filter(pk=inv_o).update(recipient_email="")

        # PDF der Rechnung kündigt die Lastschrift an
        assert c.get(f"{base}/invoices/{inv_e}/pdf/").status_code == 200

        props = c.get(f"{base}/debits/proposals/").json()
        assert sorted(i["id"] for i in props["invoices"]) == sorted([inv_e, inv_o])
        # Daten für die Prüfliste vor dem Lastschriftlauf
        assert props["creditor_valid"] is True
        assert props["expiring_soon"] == 0
        assert {i["id"]: i["has_email"] for i in props["invoices"]} == {inv_e: True, inv_o: False}
        too_early = c.post(
            f"{base}/debits/",
            {"invoices": [inv_e], "collection_date": str(timezone.localdate())},
            content_type=JSON,
        )
        assert too_early.status_code == 400
        date = next_workday(6)
        resp = c.post(
            f"{base}/debits/",
            {"invoices": [inv_e, inv_o], "collection_date": str(date)},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        run = resp.json()
        assert run["total"] == "90.00"
        assert run["prenotified"] == 1
        assert {i["sequence"] for i in run["items"]} == {"FRST"}
        assert any("Ankündigung SEPA-Lastschrift" in m.subject for m in mail.outbox)
        # In einem offenen Lauf werden die Rechnungen nicht erneut vorgeschlagen
        assert c.get(f"{base}/debits/proposals/").json()["invoices"] == []

        pdf = c.get(f"{base}/debits/{run['id']}/prenotifications/")
        assert pdf.content.startswith(b"%PDF")

        xml = c.get(f"{base}/debits/{run['id']}/xml/")
        assert xml.status_code == 200
        root = ET.fromstring(xml.content)  # noqa: S314 (eigene Ausgabe)
        assert root.find("p:CstmrDrctDbtInitn/p:GrpHdr/p:NbOfTxs", NS).text == "2"
        assert root.find("p:CstmrDrctDbtInitn/p:GrpHdr/p:CtrlSum", NS).text == "90.00"
        info = root.find("p:CstmrDrctDbtInitn/p:PmtInf", NS)
        assert info.find("p:PmtTpInf/p:SeqTp", NS).text == "FRST"
        assert info.find("p:PmtTpInf/p:LclInstrm/p:Cd", NS).text == "CORE"
        assert info.find("p:ReqdColltnDt", NS).text == date.isoformat()
        assert info.find("p:CdtrAcct/p:Id/p:IBAN", NS).text == "DE89370400440532013000"
        assert info.find("p:CdtrSchmeId/p:Id/p:PrvtId/p:Othr/p:Id", NS).text == CREDITOR
        names = [n.text for n in info.findall("p:DrctDbtTxInf/p:Dbtr/p:Nm", NS)]
        assert "Erika Mueller" in names
        assert info.find("p:DrctDbtTxInf/p:DbtrAgt/p:FinInstnId/p:Othr/p:Id", NS).text == (
            "NOTPROVIDED"
        )

        booked = c.post(f"{base}/debits/{run['id']}/book/")
        assert booked.status_code == 200, booked.json()
        assert booked.json()["booked"] == 2
        assert c.get(f"{base}/invoices/{inv_e}/").json()["status"] == "paid"
        with tenant_context(club.pk):
            assert Booking.objects.filter(organization=club, amount=90).count() == 0
            assert Booking.objects.filter(organization=club, date=date).count() == 2
            assert Mandate.objects.get(membership=erika, status="active").last_used_on == date

        # Nächster Einzug für Erika ist eine Folgelastschrift
        inv2 = open_invoice(c, base, erika, "10.00")
        run2 = c.post(
            f"{base}/debits/",
            {"invoices": [inv2], "collection_date": str(next_workday(8))},
            content_type=JSON,
        ).json()
        assert run2["items"][0]["sequence"] == "RCUR"
        assert c.post(f"{base}/debits/{run2['id']}/cancel/").json()["status"] == "cancelled"
        assert [i["id"] for i in c.get(f"{base}/debits/proposals/").json()["invoices"]] == [inv2]

    def test_ohne_glaeubiger_id_kein_lauf(self, c, base, setup, club):
        c.patch(f"{base}/settings/", {"creditor_id": ""}, content_type=JSON)
        erika = make_member(club, "Erika", "Muster")
        c.post(
            f"{base}/mandates/",
            {
                "membership": erika.pk,
                "holder": "Erika",
                "iban": "DE02120300000000202051",
                "signed_on": "2025-01-10",
            },
            content_type=JSON,
        )
        inv = open_invoice(c, base, erika)
        resp = c.post(
            f"{base}/debits/",
            {"invoices": [inv], "collection_date": str(next_workday(10))},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "creditor_id" in resp.json()

    def test_abgelaufenes_mandat(self, club):
        erika = make_member(club, "Erika", "Muster")
        with tenant_context(club.pk):
            m = Mandate(
                organization=club,
                membership=erika,
                reference="X",
                holder="E",
                iban="DE02120300000000202051",
                signed_on=datetime.date(2020, 1, 1),
                source="paper",
            )
            assert sepa.mandate_expired(m, datetime.date(2023, 1, 1))
            m.last_used_on = datetime.date(2022, 6, 1)
            assert not sepa.mandate_expired(m, datetime.date(2023, 1, 1))


class TestJahresabschluss:
    def test_buchung_rueckgaengig_bis_zum_abschluss(self, c, fin, setup, club):
        org = fin.removesuffix("/finance")

        def booking(text):
            return c.post(
                f"{fin}/bookings/",
                {
                    "date": "2024-05-01",
                    "kind": "income",
                    "amount": "50",
                    "account": setup["bank"],
                    "category": setup["cat"],
                    "text": text,
                },
                content_type=JSON,
            )

        first = booking("Spende")
        assert first["X-Change-Undoable"] == "1"
        undo = c.post(f"{org}/changes/{first['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert c.get(f"{fin}/bookings/{first.json()['id']}/").status_code == 404
        second = booking("Spende 2")
        assert c.post(f"{fin}/closings/", {"year": 2024}, content_type=JSON).status_code == 201
        resp = c.post(
            f"{org}/changes/{second['X-Change-Set']}/undo/", {"force": True}, content_type=JSON
        )
        assert resp.status_code == 409
        assert "2024 ist abgeschlossen" in " ".join(resp.json()["problems"])

    def test_bericht_abschluss_und_sperre(self, c, fin, setup, club, api, board_a):
        b = c.post(
            f"{fin}/bookings/",
            {
                "date": "2024-05-01",
                "kind": "income",
                "amount": "50",
                "account": setup["bank"],
                "category": setup["cat"],
                "text": "Spende",
            },
            content_type=JSON,
        )
        assert b.status_code == 201, b.json()
        booking = b.json()["id"]
        # Prüfliste vor dem Abschluss: Zahlen für das Jahr, ohne zu blockieren
        years = {y["year"]: y for y in c.get(f"{fin}/closings/").json()["years"]}
        checks = years[2024]["checks"]
        assert checks["bookings"] == 1
        assert checks["without_receipt"] == 1
        assert checks["open_invoices"] == 0
        assert checks["unbooked_debit_runs"] == 0
        report = c.get(f"{fin}/report/?jahr=2024")
        assert report.status_code == 200
        assert report.content.startswith(b"%PDF")

        current = club.fiscal_year_of(timezone.localdate())
        assert c.post(f"{fin}/closings/", {"year": current}, content_type=JSON).status_code == 400
        resp = c.post(f"{fin}/closings/", {"year": 2024}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        closed = {y["year"]: y["closed"] for y in resp.json()["years"]}
        assert closed[2024] is True

        # Gesperrt: ändern, löschen, neu buchen, neu nummerieren
        assert (
            c.patch(f"{fin}/bookings/{booking}/", {"text": "x"}, content_type=JSON).status_code
            == 400
        )
        assert c.delete(f"{fin}/bookings/{booking}/").status_code == 400
        new = c.post(
            f"{fin}/bookings/",
            {
                "date": "2024-06-01",
                "kind": "income",
                "amount": "5",
                "account": setup["bank"],
                "category": setup["cat"],
                "text": "nachträglich",
            },
            content_type=JSON,
        )
        assert new.status_code == 400
        assert "abgeschlossen" in str(new.json())
        assert (
            c.post(f"{fin}/bookings/renumber/", {"year": 2024}, content_type=JSON).status_code
            == 400
        )
        acc = c.patch(
            f"{fin}/accounts/{setup['bank']}/", {"opening_balance": "10"}, content_type=JSON
        )
        assert acc.status_code == 400

        # Kassenprüfer ohne Rollenverwaltung kann nicht aufheben
        kasse = make_user("kasse@example.org")
        give_role(kasse, club, ["finance.view", "finance.edit"], name="Kassierer")
        assert api(kasse).delete(f"{fin}/closings/?jahr=2024").status_code == 403
        # Aufheben nur mit Grund; der alte Stand bleibt erhalten (Finanzamt-Prüfung B4)
        assert c.delete(f"{fin}/closings/?jahr=2024").status_code == 400
        resp = c.delete(
            f"{fin}/closings/?jahr=2024",
            {"reason": "Rechnung der Brauerei fehlte"},
            content_type=JSON,
        )
        assert resp.status_code == 200
        year = next(y for y in resp.json()["years"] if y["year"] == 2024)
        assert year["closed"] is False
        assert year["reopened"][0]["reason"] == "Rechnung der Brauerei fehlte"
        assert c.delete(f"{fin}/bookings/{booking}/").status_code == 204

        # Erneut abschließen: Unterschiede zum aufgehobenen Stand werden gezeigt
        resp = c.post(f"{fin}/closings/", {"year": 2024}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        year = next(y for y in resp.json()["years"] if y["year"] == 2024)
        assert year["closed"] is True and len(year["reopened"]) == 1
        assert any(line.startswith("Einnahmen:") for line in year["changes"])

    def test_zahlung_in_gesperrtem_jahr(self, c, base, fin, setup, club):
        erika = make_member(club, "Erika", "Muster")
        inv = open_invoice(c, base, erika)
        c.post(f"{fin}/closings/", {"year": 2024}, content_type=JSON)
        resp = c.post(
            f"{base}/invoices/{inv}/payments/",
            {"date": "2024-12-30", "method": "transfer", "account": setup["bank"]},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 400
        assert "abgeschlossen" in str(resp.json())
