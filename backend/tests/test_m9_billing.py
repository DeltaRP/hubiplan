"""Meilenstein 9: Beitragsregeln, Beitragslauf, Rechnungen, PDF, Versand und Zahlungseingang."""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core import mail

from billing.models import Invoice, Payment
from billing.pdf import epc_payload
from core.tenancy import tenant_context
from finance.models import Booking
from members.models import ContactDetails, DepartmentRoleHolder, MembershipPeriod, MemberType
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.enabled_modules = ["finance", "members", "billing"]
    club.member_portal_enabled = True
    club.department_access_enabled = True
    club.contact_email = "kasse@verein-a.example.org"
    club.save()
    return club


@pytest.fixture
def base(club):
    return f"/api/orgs/{club.pk}/billing"


@pytest.fixture
def c(api, board_a):
    return api(board_a)


@pytest.fixture
def zug(club):
    return Department.objects.create(
        self_managed=True, organization=club, name="Jägerzug", founding_year=1950
    )


@pytest.fixture
def setup(club, c, base, zug):
    """Konto, Kategorie, Beitragssätze und eine Altersstufe."""
    fin = f"/api/orgs/{club.pk}/finance"
    bank = c.post(
        f"{fin}/accounts/",
        {
            "name": "Girokonto",
            "iban": "DE89370400440532013000",
            "bic": "COBADEFFXXX",
            "opening_date": "2025-01-01",
        },
        content_type=JSON,
    ).json()["id"]
    cash = c.post(
        f"{fin}/accounts/",
        {"name": "Barkasse", "kind": "cash", "opening_date": "2025-01-01"},
        content_type=JSON,
    ).json()["id"]
    cat = c.post(
        f"{fin}/categories/", {"name": "Mitgliedsbeiträge", "kind": "income"}, content_type=JSON
    ).json()["id"]
    resp = c.patch(f"{base}/settings/", {"account": bank, "category": cat}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    with tenant_context(club.pk):
        aktiv, _ = MemberType.objects.get_or_create(
            organization=club, name="aktiv", defaults={"active": True}
        )
        passiv = MemberType.objects.create(organization=club, name="passiv", active=False)
        frei = MemberType.objects.create(organization=club, name="Ehrenmitglied", active=False)
    resp = c.put(
        f"{base}/fees/",
        [
            {"member_type": aktiv.pk, "amount": "60.00"},
            {"member_type": passiv.pk, "amount": "30"},
            {"member_type": frei.pk, "amount": None},
        ],
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()
    resp = c.post(
        f"{base}/age-rates/",
        {"name": "Jugend", "max_age": 17, "discount_percent": "50"},
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    return {"bank": bank, "cash": cash, "cat": cat, "aktiv": aktiv, "passiv": passiv, "frei": frei}


@pytest.fixture
def members(club, setup, zug):
    erika = make_member(club, "Erika", "Muster", "erika@example.org")
    jung = make_member(club, "Jan", "Jung", birth_date=datetime.date(2010, 3, 1))
    passiv = make_member(club, "Paul", "Passiv", member_type=setup["passiv"])
    z1 = make_member(club, "Zacharias", "Zug", departments=[zug])
    z2 = make_member(club, "Zita", "Zug", departments=[zug], member_type=setup["passiv"])
    selbst = make_member(club, "Sven", "Selbst", departments=[zug])
    selbst.pays_fee_self = True
    selbst.save()
    ehren = make_member(club, "Emil", "Ehre", member_type=setup["frei"])
    neu = make_member(club, "Nina", "Neu", entry_date=datetime.date(2025, 7, 15))
    alt = make_member(club, "Otto", "Alt")
    with tenant_context(club.pk):
        MembershipPeriod.objects.filter(membership=alt).update(
            exit_date=datetime.date(2024, 12, 31), exit_reason="exit"
        )
    return locals()


def start_run(c, base, **extra):
    return c.post(
        f"{base}/runs/",
        {"year": 2025, "period": 1, "invoice_date": "2025-02-01", **extra},
        content_type=JSON,
    )


class TestBeitragsregeln:
    def test_einstellungen_und_saetze(self, c, base, setup):
        data = c.get(f"{base}/settings/").json()
        assert data["rhythm"] == "yearly"
        assert data["account"] == setup["bank"]
        assert [p["label"] for p in data["periods"]["2025"]] == ["2025"]
        fees = {f["name"]: f["amount"] for f in c.get(f"{base}/fees/").json()}
        assert fees == {"aktiv": "60.00", "passiv": "30.00", "Ehrenmitglied": None}

    def test_altersstufe_braucht_betrag_oder_abschlag(self, c, base, setup):
        resp = c.post(f"{base}/age-rates/", {"name": "Senioren", "min_age": 70}, content_type=JSON)
        assert resp.status_code == 400

    def test_kategorie_muss_einnahme_sein(self, club, c, base, setup):
        aus = c.post(
            f"/api/orgs/{club.pk}/finance/categories/",
            {"name": "Saalmiete", "kind": "expense"},
            content_type=JSON,
        ).json()["id"]
        resp = c.patch(f"{base}/settings/", {"category": aus}, content_type=JSON)
        assert resp.status_code == 400

    def test_halbjahre_bei_eigenem_geschaeftsjahr(self, club, c, base, setup):
        club.fiscal_start_month = 7
        club.save()
        c.patch(f"{base}/settings/", {"rhythm": "halfyearly"}, content_type=JSON)
        periods = c.get(f"{base}/settings/").json()["periods"]["2025"]
        assert [(p["label"], p["start"], p["end"]) for p in periods] == [
            ("1. Halbjahr 2025/26", "2025-07-01", "2025-12-31"),
            ("2. Halbjahr 2025/26", "2026-01-01", "2026-06-30"),
        ]


class TestBeitragslauf:
    def test_vorschau(self, c, base, members, club):
        # Jan ist weder per E-Mail noch per Post erreichbar, Paul nur per Post
        with tenant_context(club.pk):
            ContactDetails.objects.filter(person__last_name="Jung").update(email="", street="")
            ContactDetails.objects.filter(person__last_name="Passiv").update(email="")
        data = c.post(
            f"{base}/runs/preview/", {"year": 2025, "period": 1}, content_type=JSON
        ).json()
        assert data["members"] == 5  # Erika, Jan, Paul, Sven, Nina
        assert data["departments"] == [
            {"id": members["zug"].pk, "name": "Jägerzug", "members": 2, "total": "90.00"}
        ]
        assert {s["name"] for s in data["skipped"]} == {"Ehre, Emil"}
        # Prüfliste vor dem Beitragslauf
        assert data["checks"] == {"unreachable": 1, "with_mandate": 0, "open_change_requests": 0}

    def test_lauf_erzeugt_entwuerfe(self, c, base, members):
        resp = start_run(c, base)
        assert resp.status_code == 201, resp.json()
        run = resp.json()
        assert run["summary"]["counts"]["draft"] == 6
        invoices = {i.recipient_name.splitlines()[0]: i for i in Invoice.objects.all()}
        assert invoices["Erika Muster"].total == Decimal("60.00")
        assert invoices["Jan Jung"].total == Decimal("30.00")  # Jugend 50 %
        assert invoices["Paul Passiv"].total == Decimal("30.00")
        assert invoices["Sven Selbst"].total == Decimal("60.00")
        assert invoices["Nina Neu"].total == Decimal("60.00")  # nicht anteilig
        zug = invoices["Abteilung Jägerzug"]
        assert zug.recipient_kind == "department"
        assert zug.total == Decimal("90.00")
        assert [line.text for line in zug.lines.all()] == ["Zug, Zacharias", "Zug, Zita"]
        assert invoices["Erika Muster"].due_date == datetime.date(2025, 2, 15)
        # kein zweiter Lauf für denselben Zeitraum
        assert start_run(c, base).status_code == 400

    def test_anteilig(self, c, base, members):
        c.patch(f"{base}/settings/", {"pro_rata": True}, content_type=JSON)
        start_run(c, base)
        nina = Invoice.objects.get(membership=members["neu"])
        assert nina.total == Decimal("30.00")  # Juli bis Dezember: 6/12
        assert "anteilig 6/12 Monate" in nina.lines.get().detail

    def test_festschreiben_versenden_pdf(self, club, c, base, members):
        run = start_run(c, base).json()
        resp = c.post(f"{base}/runs/{run['id']}/finalize/")
        assert resp.status_code == 200, resp.json()
        assert resp.json()["summary"]["counts"]["open"] == 6
        numbers = sorted(Invoice.objects.values_list("number", flat=True))
        assert numbers == [1, 2, 3, 4, 5, 6]
        assert (
            Invoice.objects.filter(recipient_kind="member")
            .first()
            .display_number.startswith("R2025-")
        )
        # Zug hat keinen Kassierer → keine E-Mail
        resp = c.post(f"{base}/runs/{run['id']}/send/")
        assert resp.json()["sent"] == 5
        assert len(mail.outbox) == 5
        msg = next(m for m in mail.outbox if m.to == ["erika@example.org"])
        assert msg.attachments[0][0].startswith("Rechnung-R2025-")
        assert msg.attachments[0][1][:4] == b"%PDF"
        assert msg.reply_to == ["kasse@verein-a.example.org"]
        assert resp.json()["summary"]["without_email"] == 1
        pdf = c.get(f"{base}/runs/{run['id']}/pdf/?nur=ohne_email")
        assert pdf.status_code == 200
        assert pdf.content[:4] == b"%PDF"
        # Lauf mit festgeschriebenen Rechnungen lässt sich nicht löschen
        assert c.delete(f"{base}/runs/{run['id']}/").status_code == 400

    def test_nachzuegler(self, club, c, base, members):
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        make_member(club, "Lena", "Later", entry_date=datetime.date(2025, 3, 1))
        resp = c.post(f"{base}/runs/{run['id']}/rebuild/")
        assert resp.json()["created"] == 1
        assert Invoice.objects.filter(status="draft").get().recipient_name == "Lena Later"

    def test_lauf_loeschen_solange_entwurf(self, c, base, members):
        run = start_run(c, base).json()
        assert c.delete(f"{base}/runs/{run['id']}/").status_code == 204
        assert not Invoice.objects.exists()


class TestZahlung:
    @pytest.fixture
    def invoice(self, c, base, members):
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        return Invoice.objects.get(membership=members["erika"])

    def test_zahlung_bucht_in_die_kasse(self, club, c, base, setup, invoice):
        resp = c.post(
            f"{base}/invoices/{invoice.pk}/payments/",
            {
                "date": "2025-02-10",
                "amount": "20.00",
                "method": "transfer",
                "account": setup["bank"],
            },
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "open"
        assert resp.json()["outstanding"] == "40.00"
        booking = Booking.objects.get()
        assert booking.kind == "income"
        assert booking.amount == Decimal("20.00")
        assert booking.category_id == setup["cat"]
        assert booking.membership_id == invoice.membership_id
        assert booking.reference == invoice.display_number
        assert booking.counterparty == invoice.recipient_name.splitlines()[0]
        # Rest bar, ohne Betrag = offener Rest
        resp = c.post(
            f"{base}/invoices/{invoice.pk}/payments/",
            {"date": "2025-02-11", "method": "cash", "account": setup["cash"]},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.json()["status"] == "paid"
        # Überzahlung abgelehnt
        resp = c.post(
            f"{base}/invoices/{invoice.pk}/payments/",
            {"date": "2025-02-11", "amount": "1", "method": "cash", "account": setup["cash"]},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 400
        # Buchung aus der Kasse nicht löschbar, Zahlung schon
        fin = f"/api/orgs/{club.pk}/finance"
        assert c.delete(f"{fin}/bookings/{booking.pk}/").status_code == 400
        listed = c.get(f"{fin}/bookings/").json()["results"]
        assert listed[0]["invoice"]["number"] == invoice.display_number
        payment = Payment.objects.get(booking=booking)
        assert c.delete(f"{base}/payments/{payment.pk}/").status_code == 200
        assert not Booking.objects.filter(pk=booking.pk).exists()
        invoice.refresh_from_db()
        assert invoice.paid == Decimal("40.00")

    def test_stornieren(self, c, base, invoice, setup):
        assert c.post(f"{base}/invoices/{invoice.pk}/cancel/").json()["status"] == "cancelled"
        resp = c.post(
            f"{base}/invoices/{invoice.pk}/payments/",
            {"date": "2025-02-10", "method": "cash", "account": setup["cash"]},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 400

    def test_ohne_kategorie_keine_zahlung(self, c, base, invoice, setup):
        c.patch(f"{base}/settings/", {"category": None}, content_type=JSON)
        resp = c.post(
            f"{base}/invoices/{invoice.pk}/payments/",
            {"date": "2025-02-10", "method": "cash", "account": setup["cash"]},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 400
        assert "Kategorie" in str(resp.json())


class TestEinzelrechnung:
    def test_entwurf_rueckgaengig_festgeschrieben_nicht(self, c, base, members):
        erika = members["erika"]
        resp = c.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "member",
                "membership": erika.pk,
                "date": "2025-03-01",
                "subject": "Uniform",
                "lines": [{"text": "Uniform", "amount": "80.00"}],
            },
            content_type=JSON,
        )
        assert resp["X-Change-Undoable"] == "1"
        created = resp["X-Change-Set"]
        invoice = resp.json()["id"]
        change = c.patch(
            f"{base}/invoices/{invoice}/",
            {"lines": [{"text": "Uniform", "amount": "90.00"}]},
            content_type=JSON,
        )
        assert change["X-Change-Undoable"] == "1"
        org = base.removesuffix("/billing")
        undo = c.post(f"{org}/changes/{change['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert c.get(f"{base}/invoices/{invoice}/").json()["total"] == "80.00"
        # Festschreiben ist endgültig; danach lässt sich auch das Anlegen nicht zurücknehmen
        fin = c.post(f"{base}/invoices/{invoice}/finalize/")
        assert fin.get("X-Change-Undoable") != "1"
        resp = c.post(f"{org}/changes/{created}/undo/", {"force": True}, content_type=JSON)
        assert resp.status_code == 409
        assert "festgeschriebene Rechnung" in " ".join(resp.json()["problems"])

    def test_anlegen_aendern_festschreiben(self, c, base, members):
        erika = members["erika"]
        resp = c.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "member",
                "membership": erika.pk,
                "date": "2025-03-01",
                "subject": "Aufnahmegebühr und Uniform",
                "lines": [
                    {"text": "Aufnahmegebühr", "amount": "25.00"},
                    {"text": "Ermäßigung", "amount": "-5.00"},
                ],
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["total"] == "20.00"
        assert data["number"] == "Entwurf"
        assert data["due_date"] == "2025-03-15"
        resp = c.patch(
            f"{base}/invoices/{data['id']}/",
            {"lines": [{"text": "Aufnahmegebühr", "amount": "30.00"}]},
            content_type=JSON,
        )
        assert resp.json()["total"] == "30.00"
        pdf = c.get(f"{base}/invoices/{data['id']}/pdf/")
        assert pdf.content[:4] == b"%PDF"
        resp = c.post(f"{base}/invoices/{data['id']}/finalize/")
        assert resp.json()["number"] == "R2025-0001"
        # festgeschrieben: Posten nicht mehr änderbar, Hinweis schon
        resp = c.patch(
            f"{base}/invoices/{data['id']}/",
            {"lines": [{"text": "x", "amount": "1"}]},
            content_type=JSON,
        )
        assert resp.status_code == 400
        resp = c.patch(f"{base}/invoices/{data['id']}/", {"note": "Danke!"}, content_type=JSON)
        assert resp.json()["note"] == "Danke!"
        assert c.delete(f"{base}/invoices/{data['id']}/").status_code == 400
        resp = c.post(f"{base}/invoices/{data['id']}/send/")
        assert resp.status_code == 200
        assert resp.json()["sent_at"]

    def test_betrag_null_nicht_festschreibbar(self, c, base, members):
        data = c.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "member",
                "membership": members["erika"].pk,
                "lines": [{"text": "nichts", "amount": "0"}],
            },
            content_type=JSON,
        ).json()
        assert c.post(f"{base}/invoices/{data['id']}/finalize/").status_code == 400

    def test_filter(self, c, base, members):
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        rows = c.get(f"{base}/invoices/?mitglied={members['z1'].pk}").json()["results"]
        assert [r["recipient_kind"] for r in rows] == ["department"]
        rows = c.get(f"{base}/invoices/?suche=Muster").json()["results"]
        assert len(rows) == 1


class TestZugriff:
    def test_anderer_verein_und_modul(self, orgs, club, api, board_b, c, base, members):
        assert api(board_b).get(f"{base}/invoices/").status_code == 404
        club.enabled_modules = ["members"]
        club.save()
        assert c.get(f"{base}/invoices/").status_code == 404

    def test_nur_lesen(self, club, api, base, members):
        reader = make_user("pruefer@example.org")
        give_role(reader, club, ["billing.view"], name="Prüfer")
        r = api(reader)
        assert r.get(f"{base}/invoices/").status_code == 200
        assert start_run(r, base).status_code == 403

    def test_mitgliederbereich_und_zugkassierer(self, club, c, base, members, api, zug):
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        # Mitglied sieht eigene Rechnung
        c.post(f"/api/orgs/{club.pk}/members/{members['erika'].pk}/access/")
        erika = api(PortalAccess.objects.get(membership=members["erika"]).user)
        access = PortalAccess.objects.get(membership=members["erika"])
        data = erika.get(f"/api/portal/{access.pk}/invoices/").json()
        assert [i["total"] for i in data["invoices"]] == ["60.00"]
        own = data["invoices"][0]["id"]
        assert erika.get(f"/api/portal/{access.pk}/invoices/{own}/pdf/").status_code == 200
        other = Invoice.objects.get(membership=members["jung"]).pk
        assert erika.get(f"/api/portal/{access.pk}/invoices/{other}/pdf/").status_code == 404
        # Zugmitglied sieht seinen Posten in der Sammelrechnung
        c.post(f"/api/orgs/{club.pk}/members/{members['z1'].pk}/access/")
        z_access = PortalAccess.objects.get(membership=members["z1"])
        data = api(z_access.user).get(f"/api/portal/{z_access.pk}/invoices/").json()
        assert data["invoices"] == []
        assert data["collective"][0]["amount"] == "60.00"
        # Zugkassierer sieht die Sammelrechnung
        role = DepartmentRole.objects.create(
            organization=club,
            department=zug,
            name="Zugkassierer",
            permissions=["dept.members.view", "dept.invoices.view"],
        )
        DepartmentRoleHolder.objects.create(
            organization=club, membership=members["z1"], role=role, valid_from="2020-01-01"
        )
        k = api(z_access.user)
        rows = k.get(f"/api/depts/{zug.pk}/invoices/").json()
        assert len(rows) == 1
        assert len(rows[0]["lines"]) == 2
        assert k.get(f"/api/depts/{zug.pk}/invoices/{rows[0]['id']}/pdf/").status_code == 200
        role.permissions = ["dept.members.view"]
        role.save()
        assert k.get(f"/api/depts/{zug.pk}/invoices/").status_code == 403

    def test_kassierer_wird_empfaenger(self, club, c, base, members, zug):
        role = DepartmentRole.objects.create(
            organization=club, department=zug, name="Kassierer", permissions=["dept.invoices.view"]
        )
        DepartmentRoleHolder.objects.create(
            organization=club, membership=members["z1"], role=role, valid_from="2020-01-01"
        )
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        inv = Invoice.objects.get(recipient_kind="department")
        assert inv.recipient_name == "Abteilung Jägerzug\nz. Hd. Zacharias Zug"
        assert inv.recipient_email == "zacharias@example.org"


def test_epc_qr_inhalt():
    payload = epc_payload("Verein A", "DE89370400440532013000", "", Decimal("60"), "R2025-0001")
    assert payload.splitlines() == [
        "BCD",
        "002",
        "1",
        "SCT",
        "",
        "Verein A",
        "DE89370400440532013000",
        "EUR60.00",
        "",
        "",
        "R2025-0001",
    ]


def test_zahlt_selbst_in_der_akte(club, c, members):
    url = f"/api/orgs/{club.pk}/members/{members['z1'].pk}/"
    assert c.get(url).json()["pays_fee_self"] is False
    resp = c.patch(url, {"pays_fee_self": True}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    members["z1"].refresh_from_db()
    assert members["z1"].pays_fee_self is True
