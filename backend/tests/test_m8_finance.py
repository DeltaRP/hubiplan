"""Meilenstein 8: Kasse mit Konten, Kategorien, Buchungen, Belegen und Prüferzugang."""

import datetime
from decimal import Decimal

import pytest

from audit.models import AuditEntry
from finance.models import Account, Booking, Category, Receipt

from .factories import audit_with, give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.enabled_modules = ["finance", "members"]
    club.save()
    return club


@pytest.fixture
def base(club):
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def kasse(club, api, board_a, base):
    c = api(board_a)
    bank = c.post(
        f"{base}/accounts/",
        {
            "name": "Girokonto",
            "kind": "bank",
            "iban": "DE89 3704 0044 0532 0130 00",
            "opening_balance": "1000.00",
            "opening_date": "2025-01-01",
        },
        content_type=JSON,
    )
    assert bank.status_code == 201, bank.json()
    cash = c.post(
        f"{base}/accounts/",
        {"name": "Barkasse", "kind": "cash", "opening_balance": "50", "opening_date": "2025-01-01"},
        content_type=JSON,
    )
    beitraege = c.post(
        f"{base}/categories/", {"name": "Beiträge", "kind": "income"}, content_type=JSON
    )
    fest = c.post(f"{base}/categories/", {"name": "Schützenfest"}, content_type=JSON)
    return {
        "c": c,
        "bank": bank.json()["id"],
        "cash": cash.json()["id"],
        "beitraege": beitraege.json()["id"],
        "fest": fest.json()["id"],
    }


def book(k, base, **data):
    resp = k["c"].post(f"{base}/bookings/", data, content_type=JSON)
    return resp


class TestKonten:
    def test_iban_wird_geprueft(self, kasse, base):
        resp = kasse["c"].post(
            f"{base}/accounts/",
            {"name": "Falsch", "iban": "DE00123", "opening_date": "2025-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "iban" in resp.json()
        assert Account.objects.get(pk=kasse["bank"]).iban == "DE89370400440532013000"

    def test_name_eindeutig(self, kasse, base):
        resp = kasse["c"].post(
            f"{base}/accounts/",
            {"name": "girokonto", "opening_date": "2025-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_konto_mit_buchungen_nicht_loeschbar(self, kasse, base):
        book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="10",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="Beitrag",
        )
        resp = kasse["c"].delete(f"{base}/accounts/{kasse['bank']}/")
        assert resp.status_code == 400
        assert kasse["c"].delete(f"{base}/accounts/{kasse['cash']}/").status_code == 204


class TestKategorienLoeschen:
    def test_unbenutzte_kategorie_wird_geloescht(self, kasse, base):
        c, fest = kasse["c"], kasse["fest"]
        usage = c.get(f"{base}/categories/{fest}/usage/").json()
        assert usage == {"deletable": True, "reasons": [], "is_archived": False}
        assert c.delete(f"{base}/categories/{fest}/").status_code == 204
        assert not Category.objects.filter(pk=fest).exists()
        assert AuditEntry.objects.filter(action="delete", object_repr="Schützenfest").exists()

    def test_gebuchte_kategorie_wird_archiviert(self, kasse, base):
        c, kat = kasse["c"], kasse["beitraege"]
        resp = book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="10",
            account=kasse["bank"],
            category=kat,
            text="Beitrag",
        )
        booking_id = resp.json()["id"]
        usage = c.get(f"{base}/categories/{kat}/usage/").json()
        assert usage["deletable"] is False
        assert usage["reasons"] == ["in 1 Buchung verwendet (Geschäftsjahr 2025)"]

        resp = c.delete(f"{base}/categories/{kat}/")
        assert resp.status_code == 409
        assert resp.json()["can_archive"] is True
        assert Category.objects.filter(pk=kat).exists()

        resp = c.post(f"{base}/categories/{kat}/archive/")
        assert resp.status_code == 200 and resp.json()["is_active"] is False
        assert audit_with("archiviert", [False, True], action="update", object_repr="Beiträge")
        # Buchung und Kassenbericht unverändert
        b = c.get(f"{base}/bookings/{booking_id}/").json()
        assert b["category"] == kat and b["category_name"] == "Beiträge"
        ov = c.get(f"{base}/overview/?jahr=2025").json()
        assert "Beiträge" in {x["name"] for x in ov["categories"]}

        resp = c.post(f"{base}/categories/{kat}/restore/")
        assert resp.status_code == 200 and resp.json()["is_active"] is True

    def test_umbenennen(self, kasse, base):
        c, kat = kasse["c"], kasse["beitraege"]
        url = f"{base}/categories/{kat}/"
        resp = c.patch(url, {"name": "Mitgliedsbeiträge"}, content_type=JSON)
        assert resp.status_code == 200 and resp.json()["name"] == "Mitgliedsbeiträge"
        resp = c.patch(url, {"name": "schützenfest"}, content_type=JSON)
        assert resp.status_code == 400 and "name" in resp.json()

    def test_beitragskategorie_nicht_loeschbar(self, kasse, base, club):
        from billing.models import BillingSettings

        BillingSettings.objects.create(organization=club, category_id=kasse["fest"])
        c = kasse["c"]
        usage = c.get(f"{base}/categories/{kasse['fest']}/usage/").json()
        assert usage["reasons"] == ["als Kategorie für Beitragszahlungen eingestellt"]
        assert c.delete(f"{base}/categories/{kasse['fest']}/").status_code == 409


class TestBuchungen:
    def test_nummern_je_jahr_und_bestand(self, kasse, base):
        r1 = book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="60.00",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="Beitrag Muster",
        )
        assert r1.status_code == 201, r1.json()
        assert r1.json()["display_number"] == "2025-0001"
        r2 = book(
            kasse,
            base,
            date="2025-06-01",
            kind="expense",
            amount="200",
            account=kasse["bank"],
            category=kasse["fest"],
            text="Zeltmiete",
        )
        assert r2.json()["display_number"] == "2025-0002"
        r3 = book(
            kasse,
            base,
            date="2026-01-05",
            kind="transfer",
            amount="30",
            account=kasse["cash"],
            to_account=kasse["bank"],
            text="Bareinzahlung",
        )
        assert r3.status_code == 201, r3.json()
        assert r3.json()["display_number"] == "2026-0001"
        assert r3.json()["category"] is None

        accounts = {a["name"]: a for a in kasse["c"].get(f"{base}/accounts/").json()}
        assert accounts["Girokonto"]["balance"] == "890.00"
        assert accounts["Barkasse"]["balance"] == "20.00"

        ov = kasse["c"].get(f"{base}/overview/?jahr=2026").json()
        giro = next(a for a in ov["accounts"] if a["name"] == "Girokonto")
        assert Decimal(giro["start"]) == Decimal("860")
        assert Decimal(giro["transfer_in"]) == Decimal("30")
        assert Decimal(giro["end"]) == Decimal("890")
        # Umbuchungen zählen nicht als Einnahme
        assert Decimal(ov["totals"]["income"]) == 0

        ov = kasse["c"].get(f"{base}/overview/?jahr=2025").json()
        assert Decimal(ov["totals"]["income"]) == Decimal("60")
        assert Decimal(ov["totals"]["expense"]) == Decimal("200")
        assert {c["name"] for c in ov["categories"]} == {"Beiträge", "Schützenfest"}
        assert {"year": 2025, "label": "2025"} in ov["years"]

    def test_pruefungen(self, kasse, base):
        # Kategorie nur für Einnahmen
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="expense",
            amount="5",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="x",
        )
        assert r.status_code == 400 and "category" in r.json()
        # Ohne Kategorie
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="5",
            account=kasse["bank"],
            text="x",
        )
        assert "category" in r.json()
        # Umbuchung auf dasselbe Konto
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="transfer",
            amount="5",
            account=kasse["bank"],
            to_account=kasse["bank"],
            text="x",
        )
        assert "to_account" in r.json()
        # Betrag 0
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="0",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="x",
        )
        assert r.status_code == 400
        # vor dem Stichtag
        r = book(
            kasse,
            base,
            date="2024-12-31",
            kind="income",
            amount="5",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="x",
        )
        assert "date" in r.json()
        assert not Booking.objects.exists()

    def test_jahr_nicht_aenderbar(self, kasse, base):
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="5",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="x",
        )
        pk = r.json()["id"]
        resp = kasse["c"].patch(f"{base}/bookings/{pk}/", {"date": "2026-01-01"}, content_type=JSON)
        assert resp.status_code == 400
        resp = kasse["c"].patch(
            f"{base}/bookings/{pk}/", {"date": "2025-04-01", "amount": "7"}, content_type=JSON
        )
        assert resp.status_code == 200
        assert AuditEntry.objects.filter(object_type="Buchung", action="update").exists()

    def test_fremde_objekte_abgelehnt(self, kasse, base, orgs):
        fremd = Account.objects.create(
            organization=orgs["b"], name="Fremd", opening_date=datetime.date(2025, 1, 1)
        )
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="5",
            account=fremd.pk,
            category=kasse["beitraege"],
            text="x",
        )
        assert r.status_code == 400 and "account" in r.json()

    def test_mitglied_und_filter(self, kasse, base, club):
        m = make_member(club, "Erika", "Muster")
        book(
            kasse,
            base,
            date="2025-03-01",
            kind="income",
            amount="60",
            account=kasse["bank"],
            category=kasse["beitraege"],
            text="Beitrag",
            membership=m.pk,
        )
        book(
            kasse,
            base,
            date="2025-03-02",
            kind="expense",
            amount="12.50",
            account=kasse["cash"],
            category=kasse["fest"],
            text="Getränke",
        )
        rows = kasse["c"].get(f"{base}/bookings/?jahr=2025&mitglied={m.pk}").json()["results"]
        assert [r["member_name"] for r in rows] == ["Muster, Erika"]
        rows = kasse["c"].get(f"{base}/bookings/?suche=getr").json()["results"]
        assert [r["text"] for r in rows] == ["Getränke"]
        rows = kasse["c"].get(f"{base}/bookings/?suche=12,50").json()["results"]
        assert len(rows) == 1
        rows = kasse["c"].get(f"{base}/bookings/?konto={kasse['cash']}").json()["results"]
        assert len(rows) == 1
        rows = kasse["c"].get(f"{base}/bookings/?ohne_beleg=1").json()["results"]
        assert len(rows) == 2


class TestEmpfaenger:
    def test_empfaenger_vorschlaege_und_filter(self, kasse, base):
        def ausgabe(partner, text="Einkauf", kind="expense"):
            resp = book(
                kasse,
                base,
                date="2025-04-01",
                kind=kind,
                amount="10",
                account=kasse["bank"],
                category=kasse["fest"],
                text=text,
                counterparty=partner,
            )
            assert resp.status_code == 201, resp.json()
            return resp.json()

        first = ausgabe("  Getränke   Müller ")
        assert first["counterparty"] == "Getränke Müller"
        ausgabe("getränke müller")
        ausgabe("Festzeltbau Schmitz")
        ausgabe("Stadtsparkasse", kind="income", text="Zinsen")
        ausgabe("")

        names = kasse["c"].get(f"{base}/bookings/counterparties/?art=expense").json()
        assert [n["name"] for n in names][:2] == ["Getränke Müller", "Festzeltbau Schmitz"]
        assert names[0]["count"] == 2
        assert names[-1]["name"] == "Stadtsparkasse"
        names = kasse["c"].get(f"{base}/bookings/counterparties/?art=income").json()
        assert names[0]["name"] == "Stadtsparkasse"

        rows = kasse["c"].get(f"{base}/bookings/?partner=GETRÄNKE MÜLLER").json()["results"]
        assert len(rows) == 2
        rows = kasse["c"].get(f"{base}/bookings/?suche=schmitz").json()["results"]
        assert [r["counterparty"] for r in rows] == ["Festzeltbau Schmitz"]

    def test_umbuchung_ohne_empfaenger(self, kasse, base):
        resp = book(
            kasse,
            base,
            date="2025-04-01",
            kind="transfer",
            amount="10",
            account=kasse["bank"],
            to_account=kasse["cash"],
            text="Wechselgeld",
            counterparty="Irgendwer",
        )
        assert resp.status_code == 201, resp.json()
        assert resp.json()["counterparty"] == ""


class TestBelege:
    def test_hochladen_ansehen_loeschen(self, kasse, base):
        r = book(
            kasse,
            base,
            date="2025-03-01",
            kind="expense",
            amount="20",
            account=kasse["cash"],
            category=kasse["fest"],
            text="Bons",
        )
        pk = r.json()["id"]
        from django.core.files.uploadedfile import SimpleUploadedFile

        pdf = SimpleUploadedFile("quittung.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        resp = kasse["c"].post(f"{base}/bookings/{pk}/receipts/", {"file": pdf})
        assert resp.status_code == 201, resp.json()
        rid = resp.json()["id"]
        detail = kasse["c"].get(f"{base}/bookings/{pk}/").json()
        assert detail["receipts"][0]["name"] == "quittung.pdf"
        resp = kasse["c"].get(f"{base}/receipts/{rid}/")
        assert resp.status_code == 200
        assert b"".join(resp.streaming_content).startswith(b"%PDF")

        fake = SimpleUploadedFile("x.pdf", b"kein pdf", content_type="application/pdf")
        assert kasse["c"].post(f"{base}/bookings/{pk}/receipts/", {"file": fake}).status_code == 400
        exe = SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload")
        assert kasse["c"].post(f"{base}/bookings/{pk}/receipts/", {"file": exe}).status_code == 400

        assert kasse["c"].delete(f"{base}/receipts/{rid}/").status_code == 204
        assert not Receipt.objects.exists()


class TestZugriff:
    def test_kassenpruefer_nur_lesen(self, kasse, base, club, api):
        pruefer = make_user("pruefer@example.org")
        give_role(pruefer, club, ["finance.view"], name="Kassenprüfer")
        c = api(pruefer)
        assert c.get(f"{base}/accounts/").status_code == 200
        assert c.get(f"{base}/overview/").status_code == 200
        assert c.get(f"{base}/settings/").json()["can_edit"] is False
        r = c.post(f"{base}/categories/", {"name": "Neu"}, content_type=JSON)
        assert r.status_code == 403

    def test_ohne_recht_und_ohne_modul(self, kasse, base, club, api):
        jemand = make_user("mitglieder@example.org")
        give_role(jemand, club, ["members.view"], name="Schriftführer")
        assert api(jemand).get(f"{base}/accounts/").status_code == 403
        club.enabled_modules = ["members"]
        club.save()
        assert kasse["c"].get(f"{base}/accounts/").status_code == 404

    def test_steuerliche_bereiche(self, kasse, base, club):
        r = kasse["c"].post(
            f"{base}/categories/", {"name": "Zinsen", "tax_area": "assets"}, content_type=JSON
        )
        assert r.json()["tax_area"] == ""  # nicht freigeschaltet
        club.tax_areas_enabled = True
        club.save()
        r = kasse["c"].post(
            f"{base}/categories/", {"name": "Zinsen2", "tax_area": "assets"}, content_type=JSON
        )
        assert r.json()["tax_area"] == "assets"
        book(
            kasse,
            base,
            date="2025-05-01",
            kind="income",
            amount="3",
            account=kasse["bank"],
            category=r.json()["id"],
            text="Zinsen",
        )
        ov = kasse["c"].get(f"{base}/overview/?jahr=2025").json()
        assert ov["tax_areas"][0]["label"] == "Vermögensverwaltung"

    def test_verein_schaltet_bereiche_selbst(self, orgs, api, kasse, base, club):
        from organizations.models import Organization

        resp = kasse["c"].patch(f"{base}/settings/", {"tax_areas_enabled": True}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["tax_areas_enabled"] is True
        club.refresh_from_db()
        assert club.tax_areas_enabled
        # Lesende Kassenprüfer dürfen nicht umschalten
        pruefer = make_user("pruefer@example.org")
        give_role(pruefer, club, ["finance.view"], name="Kassenprüfer")
        resp = api(pruefer).patch(
            f"{base}/settings/", {"tax_areas_enabled": False}, content_type=JSON
        )
        assert resp.status_code == 403
        # Die Plattform schaltet es nicht mehr
        admin = make_user("admin@example.org")
        give_role(admin, Organization.platform())
        api(admin).patch(
            f"/api/platform/orgs/{club.pk}/", {"tax_areas_enabled": False}, content_type=JSON
        )
        club.refresh_from_db()
        assert club.tax_areas_enabled


class TestGeschaeftsjahr:
    def test_abweichendes_geschaeftsjahr(self, club, api, board_a, base):
        c = api(board_a)
        resp = c.patch(
            f"/api/orgs/{club.pk}/",
            {"fiscal_start_month": 7, "fiscal_start_day": 1},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert "/" in resp.json()["fiscal_label"]
        konto = c.post(
            f"{base}/accounts/",
            {"name": "Giro", "opening_balance": "100", "opening_date": "2025-07-01"},
            content_type=JSON,
        ).json()["id"]
        kat = c.post(f"{base}/categories/", {"name": "Beiträge"}, content_type=JSON).json()["id"]
        data = {"kind": "income", "account": konto, "category": kat, "text": "x"}
        r1 = c.post(
            f"{base}/bookings/", {**data, "date": "2026-06-30", "amount": "10"}, content_type=JSON
        ).json()
        r2 = c.post(
            f"{base}/bookings/", {**data, "date": "2026-07-01", "amount": "20"}, content_type=JSON
        ).json()
        assert r1["display_number"] == "2025/26-0001"
        assert r1["year"] == 2025 and r2["year"] == 2026
        assert r2["display_number"] == "2026/27-0001"
        ov = c.get(f"{base}/overview/?jahr=2025").json()
        assert ov["label"] == "2025/26"
        assert ov["start_date"] == "2025-07-01" and ov["end_date"] == "2026-06-30"
        assert ov["totals"]["income"] == "10.00"
        assert c.get(f"{base}/overview/?jahr=2026").json()["accounts"][0]["start"] == "110.00"
        rows = c.get(f"{base}/bookings/?suche=2026/27-0001").json()["results"]
        assert [r["id"] for r in rows] == [r2["id"]]
        # Mit Buchungen lässt sich das Geschäftsjahr nicht mehr ändern
        resp = c.patch(f"/api/orgs/{club.pk}/", {"fiscal_start_month": 1}, content_type=JSON)
        assert resp.status_code == 400

    def test_ungueltiger_tag(self, club, api, board_a):
        resp = api(board_a).patch(
            f"/api/orgs/{club.pk}/",
            {"fiscal_start_month": 2, "fiscal_start_day": 30},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_abteilung_hat_geschaeftsjahr(self, club, api, board_a):
        from organizations.models import Department

        d = Department.objects.create(organization=club, name="1. Zug", founding_year=1950)
        resp = api(board_a).patch(
            f"/api/orgs/{club.pk}/departments/{d.pk}/",
            {"fiscal_start_month": 10, "fiscal_start_day": 1},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        d.refresh_from_db()
        assert d.fiscal_label(2025) == "2025/26"


class TestNummern:
    def test_nummer_korrigieren_und_neu_nummerieren(self, kasse, base):
        data = {
            "kind": "income",
            "account": kasse["bank"],
            "category": kasse["beitraege"],
            "text": "x",
            "amount": "1",
        }
        ids = [
            kasse["c"]
            .post(f"{base}/bookings/", {**data, "date": d}, content_type=JSON)
            .json()["id"]
            for d in ("2025-05-01", "2025-03-01", "2025-04-01")
        ]
        c = kasse["c"]
        # Nummer schon vergeben
        r = c.patch(f"{base}/bookings/{ids[0]}/", {"number": 2}, content_type=JSON)
        assert r.status_code == 400 and "number" in r.json()
        r = c.patch(f"{base}/bookings/{ids[0]}/", {"number": 17}, content_type=JSON)
        assert r.status_code == 200 and r.json()["display_number"] == "2025-0017"
        # Neue Buchungen ignorieren eine mitgeschickte Nummer
        r = c.post(
            f"{base}/bookings/", {**data, "date": "2025-06-01", "number": 3}, content_type=JSON
        )
        assert r.json()["number"] == 18
        r = c.post(f"{base}/bookings/renumber/", {"year": 2025}, content_type=JSON)
        assert r.status_code == 200 and r.json()["changed"] == 4
        numbers = {b.pk: b.number for b in Booking.objects.all()}
        assert [numbers[i] for i in ids] == [3, 1, 2]
        assert AuditEntry.objects.filter(action="update", object_type="Organisation").exists()


def test_rls_kasse(kasse, base, club, orgs):
    from core.tenancy import set_rls

    from .test_rls import as_app_role

    book(
        kasse,
        base,
        date="2025-03-01",
        kind="income",
        amount="5",
        account=kasse["bank"],
        category=kasse["beitraege"],
        text="x",
    )
    with as_app_role():
        set_rls(orgs["b"].pk, None)
        assert not Account.objects.exists()
        assert not Category.objects.exists()
        assert not Booking.objects.exists()
        set_rls(club.pk, None)
        assert Booking.objects.count() == 1
