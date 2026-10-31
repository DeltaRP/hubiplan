"""Meilenstein 10: Dachverbandsbeiträge an Vereine, Mahnstufen, Umsatzsteuer."""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from billing import services
from billing.models import Dunning, Invoice
from core.tenancy import tenant_context
from members.models import MemberType

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def fed(orgs):
    fed = orgs["federation"]
    fed.enabled_modules = ["finance", "billing"]
    fed.contact_email = "kasse@bund.example.org"
    fed.save()
    for key in ("a", "b"):
        club = orgs[key]
        club.contact_email = f"verein-{key}@example.org"
        club.enabled_modules = ["finance", "members", "billing"]
        club.save()
    return fed


@pytest.fixture
def fc(api, fed):
    user = make_user("kasse@bund.example.org")
    give_role(user, fed)
    return api(user)


@pytest.fixture
def fbase(fed):
    return f"/api/orgs/{fed.pk}/billing"


def _account_and_category(c, org):
    fin = f"/api/orgs/{org.pk}/finance"
    bank = c.post(
        f"{fin}/accounts/",
        {"name": "Girokonto", "iban": "DE89370400440532013000", "opening_date": "2025-01-01"},
        content_type=JSON,
    ).json()["id"]
    cat = c.post(
        f"{fin}/categories/", {"name": "Verbandsbeiträge", "kind": "income"}, content_type=JSON
    ).json()["id"]
    return bank, cat


@pytest.fixture
def fsetup(fed, fc, fbase, orgs):
    bank, cat = _account_and_category(fc, fed)
    resp = fc.patch(
        f"{fbase}/settings/",
        {
            "account": bank,
            "category": cat,
            "club_rate_active": "10.00",
            "club_rate_passive": "4.00",
            "club_base_amount": "25.00",
        },
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()
    resp = fc.post(
        f"{fbase}/age-rates/",
        {"name": "Jugend", "max_age": 17, "discount_percent": "50"},
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    a = orgs["a"]
    with tenant_context(a.pk):
        passiv = MemberType.objects.create(organization=a, name="passiv", active=False)
        intern = MemberType.objects.create(
            organization=a, name="Gast", active=False, reported=False
        )
    make_member(a, "Anna", "Aktiv")
    make_member(a, "Bert", "Aktiv")
    make_member(a, "Jan", "Jung", birth_date=datetime.date(2012, 1, 1))
    make_member(a, "Paula", "Passiv", member_type=passiv)
    make_member(a, "Gerd", "Gast", member_type=intern)
    make_member(orgs["b"], "Bea", "Bverein")
    return {"bank": bank, "cat": cat}


class TestDachverband:
    def test_vorschau_zaehlt_gemeldete_mitglieder(self, fc, fbase, fsetup):
        resp = fc.post(f"{fbase}/runs/preview/", {"year": 2025}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        clubs = {c["name"]: c for c in resp.json()["clubs"]}
        # 2 aktiv × 10 + 1 Jugend × 5 + 1 passiv × 4 + Grundbetrag 25
        assert clubs["Verein A"]["members"] == 4
        assert clubs["Verein A"]["total"] == "54.00"
        assert clubs["Verein B"]["total"] == "35.00"

    def test_lauf_festschreiben_und_verein_sieht_rechnung(self, fc, fbase, fsetup, orgs, api):
        resp = fc.post(
            f"{fbase}/runs/", {"year": 2025, "invoice_date": "2025-02-01"}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        run = resp.json()
        assert run["created"] == 2
        invoices = fc.get(f"{fbase}/invoices/?lauf={run['id']}").json()["results"]
        inv_a = next(i for i in invoices if i["club_name"] == "Verein A")
        assert inv_a["recipient_kind"] == "club"
        assert inv_a["recipient_email"] == "verein-a@example.org"
        detail = fc.get(f"{fbase}/invoices/{inv_a['id']}/").json()
        assert [line["detail"] for line in detail["lines"]] == [
            "2 × 10,00 €",
            "1 × 5,00 €",
            "1 × 4,00 €",
            "",
        ]

        # Vor dem Festschreiben sieht der Verein nichts
        board = make_user("vorstand@verein-a.example.org")
        give_role(board, orgs["a"])
        vc = api(board)
        received = vc.get(f"/api/orgs/{orgs['a'].pk}/billing/received/").json()
        assert received == {"federation": "Testbund", "invoices": []}

        assert fc.post(f"{fbase}/runs/{run['id']}/finalize/").status_code == 200
        resp = fc.post(f"{fbase}/runs/{run['id']}/send/")
        assert resp.json()["sent"] == 2
        assert {m.to[0] for m in mail.outbox} == {"verein-a@example.org", "verein-b@example.org"}

        received = vc.get(f"/api/orgs/{orgs['a'].pk}/billing/received/").json()
        assert [i["number"] for i in received["invoices"]] == ["R2025-0001"]
        assert received["invoices"][0]["total"] == "54.00"
        pk = received["invoices"][0]["id"]
        pdf = vc.get(f"/api/orgs/{orgs['a'].pk}/billing/received/{pk}/pdf/")
        assert pdf.status_code == 200
        assert pdf["Content-Type"] == "application/pdf"

        # Verein B sieht die Rechnung von Verein A nicht
        other = make_user("vorstand@verein-b.example.org")
        give_role(other, orgs["b"])
        bc = api(other)
        assert bc.get(f"/api/orgs/{orgs['b'].pk}/billing/received/{pk}/pdf/").status_code == 404

    def test_zahlung_im_verband(self, fc, fbase, fsetup):
        fc.post(f"{fbase}/runs/", {"year": 2025, "invoice_date": "2025-02-01"}, content_type=JSON)
        run = fc.get(f"{fbase}/runs/").json()[0]
        fc.post(f"{fbase}/runs/{run['id']}/finalize/")
        inv = fc.get(f"{fbase}/invoices/?status=open").json()["results"][0]
        resp = fc.post(
            f"{fbase}/invoices/{inv['id']}/payments/",
            {"date": "2025-02-20", "method": "transfer", "account": fsetup["bank"]},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "paid"

    def test_einzelrechnung_an_verein(self, fc, fbase, fsetup, orgs):
        resp = fc.post(
            f"{fbase}/invoices/",
            {
                "club": orgs["b"].pk,
                "subject": "Fahnenweihe",
                "lines": [{"text": "Festschrift", "amount": "120.00"}],
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert resp.json()["recipient_name"] == "Verein B"
        # Fremder Verein ohne diesen Dachverband geht nicht
        resp = fc.post(
            f"{fbase}/invoices/",
            {"club": orgs["c"].pk, "lines": [{"text": "x", "amount": "1"}]},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_beitragssaetze_je_mitgliedsart_nur_im_verein(self, fc, fbase, fsetup):
        assert fc.get(f"{fbase}/fees/").status_code == 404


@pytest.fixture
def club(orgs):
    club = orgs["c"]
    club.enabled_modules = ["finance", "members", "billing"]
    club.contact_email = "kasse@verein-c.example.org"
    club.save()
    return club


@pytest.fixture
def c(api, board_c):
    return api(board_c)


@pytest.fixture
def base(club):
    return f"/api/orgs/{club.pk}/billing"


@pytest.fixture
def open_invoice(club, c, base):
    bank, cat = _account_and_category(c, club)
    c.patch(f"{base}/settings/", {"account": bank, "category": cat}, content_type=JSON)
    member = make_member(club, "Erika", "Muster", "erika@example.org")
    due = timezone.localdate() - datetime.timedelta(days=30)
    resp = c.post(
        f"{base}/invoices/",
        {
            "recipient_kind": "member",
            "membership": member.pk,
            "date": str(due - datetime.timedelta(days=14)),
            "due_date": str(due),
            "subject": "Mitgliedsbeitrag",
            "lines": [{"text": "Beitrag", "amount": "60.00"}],
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    pk = resp.json()["id"]
    assert c.post(f"{base}/invoices/{pk}/finalize/").status_code == 200
    return pk


class TestMahnungen:
    def test_stufen_vorschlag_und_mahnung(self, c, base, open_invoice):
        for level, name, days, fee in [
            (1, "Zahlungserinnerung", 14, "0"),
            (2, "1. Mahnung", 28, "5.00"),
            (3, "2. Mahnung", 60, "10.00"),
        ]:
            resp = c.post(
                f"{base}/dunning-levels/",
                {"level": level, "name": name, "days": days, "fee": fee},
                content_type=JSON,
            )
            assert resp.status_code == 201, resp.json()
        dup = c.post(
            f"{base}/dunning-levels/",
            {"level": 1, "name": "doppelt", "days": 1, "fee": "0"},
            content_type=JSON,
        )
        assert dup.status_code == 400

        data = c.get(f"{base}/dunnings/").json()
        assert len(data["levels"]) == 3
        [proposal] = data["proposals"]
        # 30 Tage überfällig: Stufe 1 ist dran (die nächste noch nicht erreichte Stufe)
        assert proposal["next_level"] == 1
        assert proposal["days_overdue"] == 30

        resp = c.post(f"{base}/dunnings/", {"invoices": [open_invoice]}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        assert resp.json() == {"created": 1, "sent": 1, "unsent": []}
        assert mail.outbox[-1].subject.startswith("Zahlungserinnerung: Rechnung R")
        assert mail.outbox[-1].attachments[0][0].startswith("Mahnung-1-")

        # Stufe 2 ist nach 28 Tagen ebenfalls fällig, jetzt mit Gebühr
        [proposal] = c.get(f"{base}/dunnings/").json()["proposals"]
        assert proposal["next_level"] == 2
        c.post(f"{base}/dunnings/", {"invoices": [open_invoice], "send": False}, content_type=JSON)
        detail = c.get(f"{base}/invoices/{open_invoice}/").json()
        assert detail["dunning_level"] == 2
        assert detail["total"] == "65.00"
        assert [d["name"] for d in detail["dunnings"]] == ["Zahlungserinnerung", "1. Mahnung"]
        assert detail["lines"][-1]["is_dunning_fee"] is True

        # Stufe 3 erst nach 60 Tagen
        assert c.get(f"{base}/dunnings/").json()["proposals"] == []

        dunning = Dunning.objects.filter(invoice_id=open_invoice, level=2).get()
        pdf = c.get(f"{base}/dunnings/pdf/?ids={dunning.pk}")
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")

    def test_bezahlte_rechnung_wird_nicht_gemahnt(self, c, base, open_invoice, club):
        c.post(
            f"{base}/dunning-levels/",
            {"level": 1, "name": "Erinnerung", "days": 0, "fee": "0"},
            content_type=JSON,
        )
        with tenant_context(club.pk):
            Invoice.objects.filter(pk=open_invoice).update(status=Invoice.Status.PAID)
        assert c.get(f"{base}/dunnings/").json()["proposals"] == []
        resp = c.post(f"{base}/dunnings/", {"invoices": [open_invoice]}, content_type=JSON)
        assert resp.status_code == 400


class TestUmsatzsteuer:
    def test_steuersatz_je_posten(self, c, base, club):
        member = make_member(club, "Erika", "Muster")
        c.patch(
            f"{base}/settings/",
            {"vat_enabled": True, "tax_number": "122/5000/1234"},
            content_type=JSON,
        )
        resp = c.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "member",
                "membership": member.pk,
                "lines": [
                    {"text": "Vereinsshirt", "amount": "23.80", "vat_rate": "19"},
                    {"text": "Beitrag", "amount": "60.00"},
                ],
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["vat"] == [{"rate": "19", "gross": "23.80", "net": "20.00", "vat": "3.80"}]
        pdf = c.get(f"{base}/invoices/{data['id']}/pdf/")
        assert pdf.status_code == 200

    def test_ohne_umsatzsteuer_wird_satz_ignoriert(self, c, base, club):
        member = make_member(club, "Erika", "Muster")
        resp = c.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "member",
                "membership": member.pk,
                "lines": [{"text": "Shirt", "amount": "23.80", "vat_rate": "19"}],
            },
            content_type=JSON,
        )
        assert resp.json()["vat"] == []
        assert resp.json()["lines"][0]["vat_rate"] is None

    def test_breakdown(self, club):
        with tenant_context(club.pk):
            member = make_member(club, "X", "Y")
            invoice = Invoice.objects.create(
                organization=club,
                recipient_kind="member",
                membership=member,
                date=datetime.date(2025, 1, 1),
                due_date=datetime.date(2025, 1, 15),
            )
            invoice.lines.create(
                organization=club, text="a", amount=Decimal("10.70"), vat_rate=Decimal("7")
            )
            assert services.vat_breakdown(invoice)[0]["vat"] == Decimal("0.70")


class TestUebersicht:
    def test_kennzahlen(self, c, base, open_invoice, club):
        c.post(
            f"{base}/dunning-levels/",
            {"level": 1, "name": "Erinnerung", "days": 7, "fee": "0"},
            content_type=JSON,
        )
        member = make_member(club, "Max", "Entwurf")
        c.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "member",
                "membership": member.pk,
                "date": str(timezone.localdate()),
                "due_date": str(timezone.localdate()),
                "lines": [{"text": "Beitrag", "amount": "12.50"}],
            },
            content_type=JSON,
        )
        resp = c.get(f"{base}/overview/")
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["drafts"] == {"count": 1, "amount": "12.50"}
        assert data["open"] == {"count": 1, "amount": "60.00"}
        assert data["overdue"] == {"count": 1, "amount": "60.00"}
        assert data["dunnings_due"] == 1
        assert data["debits_ready"] == 0
        assert data["debits_pending"] == []
        assert data["last_run"] is None

    def test_ohne_recht_verboten(self, api, base):
        outsider = make_user("fremd@example.org")
        assert api(outsider).get(f"{base}/overview/").status_code in (403, 404)
