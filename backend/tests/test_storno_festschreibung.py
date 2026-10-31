"""GoBD: Storno statt Löschen, Festschreibung, Belege ausblenden (Prüfung 31.10.2026)."""
# ruff: noqa: F811  (Fixtures aus test_m9_billing als Parameter)

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from audit.models import AuditEntry
from billing.models import Invoice, Payment
from finance import services
from finance.models import Booking, Category, Donation, Receipt
from organizations.models import Organization

from .test_m9_billing import _private, base, c, club, members, setup, start_run, zug  # noqa: F401

pytestmark = pytest.mark.django_db
JSON = "application/json"
TODAY = timezone.localdate()


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def cats(c, fin):
    fest = c.post(f"{fin}/categories/", {"name": "Schützenfest"}, content_type=JSON).json()["id"]
    spende = c.post(
        f"{fin}/categories/", {"name": "Spenden", "kind": "income"}, content_type=JSON
    ).json()["id"]
    Category.objects.filter(pk=spende).update(donations=True)
    return {"fest": fest, "spende": spende}


def book(c, fin, **data):
    payload = {"date": TODAY.isoformat(), "kind": "income", "amount": "100.00", "text": "Test"}
    payload.update(data)
    resp = c.post(f"{fin}/bookings/", payload, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return Booking.objects.get(pk=resp.json()["id"])


def age(booking, *, days: int, date_too: bool = False):
    """Buchung so tun lassen, als wäre sie vor ``days`` Tagen erfasst worden."""
    then = timezone.now() - datetime.timedelta(days=days)
    fields = {"created_at": then}
    if date_too:
        fields["date"] = then.date()
    Booking.objects.filter(pk=booking.pk).update(**fields)
    booking.refresh_from_db()
    return booking


class TestFestschreibung:
    def test_stichtag(self):
        assert services.auto_fix_cutoff(datetime.date(2026, 5, 1)) == datetime.date(2026, 4, 1)
        assert services.auto_fix_cutoff(datetime.date(2026, 5, 31)) == datetime.date(2026, 4, 1)
        assert services.auto_fix_cutoff(datetime.date(2026, 1, 15)) == datetime.date(2025, 12, 1)

    def test_nach_folgemonat_nur_noch_storno(self, c, fin, setup, cats):
        b = age(book(c, fin, account=setup["bank"], category=cats["fest"]), days=70, date_too=True)
        data = c.get(f"{fin}/bookings/{b.pk}/").json()
        assert data["fixed"] is True
        assert data["deletable"] is False
        resp = c.patch(f"{fin}/bookings/{b.pk}/", {"amount": "90.00"}, content_type=JSON)
        assert resp.status_code == 400
        assert "festgeschrieben" in str(resp.json())
        resp = c.patch(f"{fin}/bookings/{b.pk}/", {"text": "anders"}, content_type=JSON)
        assert resp.status_code == 400
        assert c.delete(f"{fin}/bookings/{b.pk}/").status_code == 400

    def test_nachtraeglich_erfasst_bleibt_aenderbar(self, c, fin, setup, cats):
        old = (TODAY - datetime.timedelta(days=70)).isoformat()
        b = book(c, fin, account=setup["bank"], category=cats["fest"], date=old)
        assert c.get(f"{fin}/bookings/{b.pk}/").json()["fixed"] is False
        resp = c.patch(f"{fin}/bookings/{b.pk}/", {"amount": "90.00"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()

    def test_festschreiben_bis(self, club, c, fin, setup, cats):
        yesterday = TODAY - datetime.timedelta(days=1)
        b = book(c, fin, account=setup["bank"], category=cats["fest"], date=yesterday.isoformat())
        resp = c.patch(
            f"{fin}/settings/", {"locked_until": yesterday.isoformat()}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["locked_until"] == yesterday.isoformat()
        assert Organization.objects.get(pk=club.pk).finance_locked_until == yesterday
        assert c.get(f"{fin}/bookings/{b.pk}/").json()["fixed"] is True
        resp = c.patch(f"{fin}/bookings/{b.pk}/", {"amount": "1.00"}, content_type=JSON)
        assert resp.status_code == 400
        # Nur vorwärts, nicht in die Zukunft
        earlier = (yesterday - datetime.timedelta(days=5)).isoformat()
        assert (
            c.patch(f"{fin}/settings/", {"locked_until": earlier}, content_type=JSON).status_code
            == 400
        )
        tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
        assert (
            c.patch(f"{fin}/settings/", {"locked_until": tomorrow}, content_type=JSON).status_code
            == 400
        )
        assert AuditEntry.objects.filter(changes__has_key="Kasse festgeschrieben bis").exists()
        # Heute erfasste Buchungen danach bleiben änderbar
        today = book(c, fin, account=setup["bank"], category=cats["fest"])
        assert c.get(f"{fin}/bookings/{today.pk}/").json()["fixed"] is False

    def test_neu_nummerieren_gesperrt(self, c, fin, setup, cats):
        b = age(book(c, fin, account=setup["bank"], category=cats["fest"]), days=70, date_too=True)
        resp = c.post(f"{fin}/bookings/renumber/", {"year": b.year}, content_type=JSON)
        assert resp.status_code == 400
        assert "festgeschrieben" in str(resp.json())

    def test_rueckgaengig_gesperrt(self):
        from changes.tracking import _booking_lock

        assert _booking_lock({"cancels_id": 5}) == "Betrifft ein Storno."


class TestLoeschen:
    def test_am_tag_der_erfassung(self, c, fin, setup, cats):
        b = book(c, fin, account=setup["bank"], category=cats["fest"])
        assert c.get(f"{fin}/bookings/{b.pk}/").json()["deletable"] is True
        assert c.delete(f"{fin}/bookings/{b.pk}/").status_code == 204

    def test_am_folgetag_nicht_mehr(self, c, fin, setup, cats):
        b = age(book(c, fin, account=setup["bank"], category=cats["fest"]), days=1)
        resp = c.delete(f"{fin}/bookings/{b.pk}/")
        assert resp.status_code == 400
        assert "stornieren" in str(resp.json())
        assert Booking.objects.filter(pk=b.pk).exists()


class TestStorno:
    def test_gegenbuchung(self, c, fin, setup, cats):
        b = age(book(c, fin, account=setup["bank"], category=cats["fest"]), days=70, date_too=True)
        before = services.balance(b.account)
        assert c.post(f"{fin}/bookings/{b.pk}/storno/", {}, content_type=JSON).status_code == 400
        resp = c.post(
            f"{fin}/bookings/{b.pk}/storno/", {"reason": "doppelt erfasst"}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["cancelled_by"]["reason"] == "doppelt erfasst"
        counter = Booking.objects.get(pk=data["cancelled_by"]["id"])
        assert counter.cancels_id == b.pk
        assert counter.kind == "expense"
        assert counter.amount == b.amount
        assert counter.category_id == b.category_id
        assert counter.date == TODAY
        assert counter.reference == b.display_number
        assert services.balance(b.account) == before - b.amount
        # Ursprüngliche Buchung unverändert
        b2 = Booking.objects.get(pk=b.pk)
        assert (b2.amount, b2.kind, b2.text) == (b.amount, b.kind, b.text)
        assert AuditEntry.objects.filter(changes__has_key="Storno").exists()
        # Kein zweites Storno, kein Storno vom Storno, Gegenbuchung nicht löschbar
        again = c.post(f"{fin}/bookings/{b.pk}/storno/", {"reason": "nochmal"}, content_type=JSON)
        assert again.status_code == 400
        resp = c.post(
            f"{fin}/bookings/{counter.pk}/storno/", {"reason": "zurück"}, content_type=JSON
        )
        assert resp.status_code == 400
        assert c.delete(f"{fin}/bookings/{counter.pk}/").status_code == 400
        resp = c.patch(f"{fin}/bookings/{counter.pk}/", {"amount": "1.00"}, content_type=JSON)
        assert resp.status_code == 400
        listed = c.get(f"{fin}/bookings/{counter.pk}/").json()
        assert listed["cancels"]["number"] == b.display_number

    def test_umbuchung_tauscht_konten(self, c, fin, setup):
        b = book(
            c, fin, kind="transfer", account=setup["bank"], to_account=setup["cash"], amount="30"
        )
        resp = c.post(f"{fin}/bookings/{b.pk}/storno/", {"reason": "falsch"}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        counter = Booking.objects.get(cancels=b)
        assert (counter.kind, counter.account_id, counter.to_account_id) == (
            "transfer",
            setup["cash"],
            setup["bank"],
        )

    def test_barkasse_nie_unter_null(self, c, fin, setup, cats):
        b = book(c, fin, account=setup["cash"], category=cats["fest"], amount="50")
        book(c, fin, kind="expense", account=setup["cash"], category=cats["fest"], amount="40")
        resp = c.post(f"{fin}/bookings/{b.pk}/storno/", {"reason": "falsch"}, content_type=JSON)
        assert resp.status_code == 400
        assert "unter null" in str(resp.json())
        assert not Booking.objects.filter(cancels=b).exists()

    def test_spende_ohne_bestaetigung_faellt_weg(self, club, c, fin, setup, cats):
        b = book(c, fin, account=setup["bank"], category=cats["spende"], counterparty="Max Muster")
        donation = Donation.objects.create(
            organization=club, date=b.date, amount=b.amount, donor_name="Max Muster", booking=b
        )
        resp = c.post(f"{fin}/bookings/{b.pk}/storno/", {"reason": "Irrläufer"}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        assert not Donation.objects.filter(pk=donation.pk).exists()
        # Stornierte Spenden werden nicht mehr als Zuwendung übernommen
        from finance.donations import import_bookings

        assert import_bookings(club, b.date.year, None) == []

    def test_abgeschlossenes_jahr(self, club, c, fin, setup, cats):
        last_year = TODAY.year - 1
        b = book(
            c,
            fin,
            account=setup["bank"],
            category=cats["fest"],
            date=f"{last_year}-06-01",
        )
        from django.db import transaction

        with transaction.atomic():
            services.close_year(club, last_year, None)
        resp = c.post(f"{fin}/bookings/{b.pk}/storno/", {"reason": "falsch"}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        assert Booking.objects.get(cancels=b).year == club.fiscal_year_of(TODAY)


class TestBelege:
    def upload(self, c, fin, booking):
        f = SimpleUploadedFile("beleg.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        resp = c.post(f"{fin}/bookings/{booking.pk}/receipts/", {"file": f})
        assert resp.status_code == 201, resp.json()
        return Receipt.objects.get(pk=resp.json()["id"])

    def test_sofort_loeschbar(self, c, fin, setup, cats):
        b = book(c, fin, account=setup["bank"], category=cats["fest"])
        r = self.upload(c, fin, b)
        assert c.delete(f"{fin}/receipts/{r.pk}/").status_code == 204
        assert not Receipt.objects.filter(pk=r.pk).exists()

    def test_spaeter_nur_ausblenden(self, c, fin, setup, cats):
        b = book(c, fin, account=setup["bank"], category=cats["fest"])
        r = self.upload(c, fin, b)
        Receipt.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=1)
        )
        resp = c.delete(f"{fin}/receipts/{r.pk}/")
        assert resp.status_code == 400
        assert "Grund" in str(resp.json())
        resp = c.delete(f"{fin}/receipts/{r.pk}/", {"reason": "falsche Datei"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        r.refresh_from_db()
        assert r.hidden_at is not None
        assert r.hidden_reason == "falsche Datei"
        assert r.file.storage.exists(r.file.name)
        # Zählt als „ohne Beleg“, bleibt aber in der Buchung sichtbar
        listed = c.get(f"{fin}/bookings/?ohne_beleg=1").json()["results"]
        assert [x["id"] for x in listed] == [b.pk]
        detail = c.get(f"{fin}/bookings/{b.pk}/").json()
        assert detail["receipts"][0]["hidden_reason"] == "falsche Datei"


class TestZahlungEntfernen:
    def test_spaeter_wird_storniert(self, c, base, fin, members, setup):
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        invoice = Invoice.objects.get(membership=members["erika"])
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
        payment = Payment.objects.get(invoice=invoice)
        booking = age(payment.booking, days=1)
        assert c.delete(f"{base}/payments/{payment.pk}/").status_code == 200
        assert Booking.objects.filter(pk=booking.pk).exists()
        counter = Booking.objects.get(cancels=booking)
        assert counter.kind == "expense"
        assert counter.amount == Decimal("20.00")
        invoice.refresh_from_db()
        assert invoice.paid == Decimal("0")
        assert invoice.status == Invoice.Status.OPEN
