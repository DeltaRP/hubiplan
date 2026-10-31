# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Regressionstests zum Datenaudit vom 25.10.2026: Finanzen (F01–F08) und Aufnahme (DS08)."""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from billing import services
from billing.models import AgeRate, DebitRun, Invoice, InvoiceLine, Payment
from core.tenancy import tenant_context
from finance.models import Account, Booking
from members.models import Membership, MembershipPeriod, Person

from .factories import make_member
from .test_m9_billing import _private, base, c, club, members, setup, start_run, zug  # noqa: F401
from .test_m10_billing import fbase, fc, fed, fsetup  # noqa: F401
from .test_m11_sepa_abschluss import CREDITOR, next_workday, open_invoice

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def invoice(c, base, members):
    run = start_run(c, base).json()
    c.post(f"{base}/runs/{run['id']}/finalize/")
    return Invoice.objects.get(membership=members["erika"])


def pay(c, base, invoice, setup, key=None, **data):
    headers = {"HTTP_IDEMPOTENCY_KEY": key or str(uuid.uuid4())}
    return c.post(
        f"{base}/invoices/{invoice.pk}/payments/",
        {"date": "2025-02-10", "method": "transfer", "account": setup["bank"], **data},
        content_type=JSON,
        **headers,
    )


class TestZahlungen:
    def test_f01_nullzahlung_bucht_nicht_den_vollen_betrag(self, c, base, setup, invoice):
        resp = pay(c, base, invoice, setup, amount="0")
        assert resp.status_code == 400
        assert not Payment.objects.exists()
        assert not Booking.objects.exists()
        # Ohne Betrag gilt weiter der offene Rest
        resp = pay(c, base, invoice, setup)
        assert resp.status_code == 200, resp.json()
        assert Payment.objects.get().amount == Decimal("60.00")

    def test_f02_gleiche_anfrage_bucht_nur_einmal(self, c, base, setup, invoice):
        key = str(uuid.uuid4())
        first = pay(c, base, invoice, setup, key=key, amount="20.00")
        again = pay(c, base, invoice, setup, key=key, amount="20.00")
        assert first.status_code == again.status_code == 200
        assert again.json()["outstanding"] == "40.00"
        assert Payment.objects.count() == 1
        assert Booking.objects.count() == 1
        # Ein neues Formular (neuer Schlüssel) bucht eine weitere Zahlung
        assert pay(c, base, invoice, setup, key=str(uuid.uuid4()), amount="5").status_code == 200
        assert Payment.objects.count() == 2

    def test_f02_abgelehnte_anfrage_gibt_schluessel_frei(self, c, base, setup, invoice):
        key = str(uuid.uuid4())
        assert pay(c, base, invoice, setup, key=key, amount="999").status_code == 400
        assert pay(c, base, invoice, setup, key=key, amount="20").status_code == 200
        assert Payment.objects.count() == 1

    def test_f02_ungueltiger_schluessel(self, c, base, setup, invoice):
        assert pay(c, base, invoice, setup, key="kein-schluessel").status_code == 400


class TestBeitragslauf:
    def test_f03_bearbeiteter_beitrag_wird_nicht_erneut_berechnet(self, c, base, members):
        run = start_run(c, base).json()
        erika = Invoice.objects.get(membership=members["erika"])
        line = erika.lines.get()
        resp = c.patch(
            f"{base}/invoices/{erika.pk}/",
            {
                "lines": [
                    {"id": line.pk, "text": line.text, "amount": "55.00"},
                    {"text": "Spende", "amount": "5.00"},
                ]
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        lines = list(InvoiceLine.objects.filter(invoice=erika).order_by("position"))
        assert [(x.is_fee, x.membership_id) for x in lines] == [
            (True, members["erika"].pk),
            (False, members["erika"].pk),
        ]
        c.post(f"{base}/invoices/{erika.pk}/finalize/")
        resp = c.post(f"{base}/runs/{run['id']}/rebuild/")
        assert resp.status_code in (200, 201), resp.json()
        assert Invoice.objects.filter(membership=members["erika"]).count() == 1

    def test_f03_alte_bearbeitete_rechnung_ohne_herkunft_zaehlt_trotzdem(self, c, base, members):
        run = start_run(c, base).json()
        erika = Invoice.objects.get(membership=members["erika"])
        # Stand vor der Korrektur: Posten hat seine Herkunft verloren
        InvoiceLine.objects.filter(invoice=erika).update(is_fee=False)
        c.post(f"{base}/invoices/{erika.pk}/finalize/")
        c.post(f"{base}/runs/{run['id']}/rebuild/")
        assert Invoice.objects.filter(membership=members["erika"]).count() == 1

    def test_f04_luecke_in_der_mitgliedschaft_bricht_den_lauf_nicht_ab(self, c, base, members):
        club = members["erika"].organization
        with tenant_context(club.pk):
            # früher Mitglied, ausgetreten 2010, Wiedereintritt erst 2030
            MembershipPeriod.objects.filter(membership=members["alt"]).update(
                entry_date=datetime.date(2000, 1, 1), exit_date=datetime.date(2010, 12, 31)
            )
            MembershipPeriod.objects.create(
                organization=club, membership=members["alt"], entry_date=datetime.date(2030, 1, 1)
            )
        resp = start_run(c, base)
        assert resp.status_code == 201, resp.json()
        assert not Invoice.objects.filter(membership=members["alt"]).exists()

    def test_f05_monatsendanker_zaehlt_den_ganzen_monat(self, club, c, base, setup):
        club.fiscal_start_month = 1
        club.fiscal_start_day = 31
        club.save()
        c.patch(f"{base}/settings/", {"pro_rata": True}, content_type=JSON)
        p = services.period(club, 2025, "monthly", 2)
        assert (p.start, p.end) == (datetime.date(2025, 2, 28), datetime.date(2025, 3, 30))
        span = MembershipPeriod(entry_date=datetime.date(2025, 3, 29))
        assert services._member_months([span], p) == 1
        p3 = services.period(club, 2025, "quarterly", 1)
        late = MembershipPeriod(entry_date=datetime.date(2025, 4, 29))
        assert services._member_months([late], p3) == 1


class TestVerbandsbeitrag:
    def test_f06_gleichnamige_altersstufen(self, fed, fc, fbase, fsetup, orgs):
        # Zweite Stufe gleichen Namens mit eigenem Betrag für Senioren
        resp = fc.post(
            f"{fbase}/age-rates/",
            {"name": "Jugend", "min_age": 70, "amount": "1.00"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        make_member(orgs["a"], "Sina", "Senior", birth_date=datetime.date(1940, 1, 1))
        p = services.period(fed, 2025, "yearly", 1)
        item = next(i for i in services.plan_federation_run(fed, p) if i.club.pk == orgs["a"].pk)
        amounts = sorted(amount for _, _, amount in item.lines)
        # 1,00 (Senior), 4,00 (passiv), 5,00 (Jugend 50 %), 20,00 (2 aktiv), 25,00 Grundbetrag
        assert amounts == [
            Decimal("1.00"),
            Decimal("4.00"),
            Decimal("5.00"),
            Decimal("20.00"),
            Decimal("25.00"),
        ]
        with tenant_context(fed.pk):
            assert AgeRate.objects.filter(organization=fed, name="Jugend").count() == 2


class TestKonto:
    def test_f08_eroeffnung_nicht_nach_eingehender_umbuchung(self, club, c, setup):
        fin = f"/api/orgs/{club.pk}/finance"
        bank, cash = setup["bank"], setup["cash"]
        resp = c.post(
            f"{fin}/bookings/",
            {
                "date": "2025-03-01",
                "kind": "transfer",
                "amount": "10.00",
                "account": bank,
                "to_account": cash,
                "text": "Wechselgeld",
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        resp = c.patch(f"{fin}/accounts/{cash}/", {"opening_date": "2025-06-01"}, content_type=JSON)
        assert resp.status_code == 400
        with tenant_context(club.pk):
            assert Account.objects.get(pk=cash).opening_date == datetime.date(2025, 1, 1)


class TestLastschrift:
    @pytest.fixture
    def sepa_setup(self, c, base, setup, club):
        c.patch(
            f"{base}/settings/",
            {"sepa_enabled": True, "creditor_id": CREDITOR, "prenotification_days": 5},
            content_type=JSON,
        )
        erika = make_member(club, "Erika", "Müller", "erika@example.org")
        c.post(
            f"{base}/mandates/",
            {
                "membership": erika.pk,
                "holder": "Erika Müller",
                "iban": "DE02120300000000202051",
                "signed_on": "2025-01-10",
            },
            content_type=JSON,
        )
        inv = open_invoice(c, base, erika)
        run = c.post(
            f"{base}/debits/",
            {"invoices": [inv], "collection_date": str(next_workday(6))},
            content_type=JSON,
        ).json()
        return {"invoice": Invoice.objects.get(pk=inv), "run": run}

    def test_f07_keine_zahlung_und_kein_storno_waehrend_offenem_lauf(
        self, c, base, setup, sepa_setup
    ):
        invoice = sepa_setup["invoice"]
        today = str(timezone.localdate())
        resp = pay(c, base, invoice, setup, amount="10.00", date=today)
        assert resp.status_code == 400
        assert "Lastschriftlauf" in str(resp.json())
        assert c.post(f"{base}/invoices/{invoice.pk}/cancel/").status_code == 400
        booked = c.post(f"{base}/debits/{sepa_setup['run']['id']}/book/")
        assert booked.status_code == 200, booked.json()
        # Gebucht wird genau der Betrag aus der Bankdatei
        assert [p.amount for p in Payment.objects.all()] == [Decimal("60.00")]

    def test_f07_abweichende_rechnung_bucht_nichts(self, c, base, setup, sepa_setup):
        invoice = sepa_setup["invoice"]
        # Altbestand: Zahlung kam am Lauf vorbei hinein
        services.add_payment(
            invoice,
            date=timezone.localdate(),
            amount=Decimal("10.00"),
            method="transfer",
            account=Account.objects.get(pk=setup["bank"]),
            user=None,
            debit=True,
        )
        resp = c.post(f"{base}/debits/{sepa_setup['run']['id']}/book/")
        assert resp.status_code == 400
        assert invoice.display_number in str(resp.json())
        assert DebitRun.objects.get().status == DebitRun.Status.CREATED
        assert Payment.objects.count() == 1


class TestAufnahme:
    def test_ds08_wiederholte_aufnahme_legt_keine_zweite_person_an(self, api, orgs, board_a):
        from .test_m2_members import make_types, person_data

        types = make_types(orgs["a"])
        client = api(board_a)
        key = str(uuid.uuid4())

        def admit():
            return client.post(
                f"/api/orgs/{orgs['a'].pk}/members/admit/",
                person_data(member_type=types["aktiv"].pk),
                content_type=JSON,
                HTTP_IDEMPOTENCY_KEY=key,
            )

        first = admit()
        assert first.status_code == 201, first.json()
        again = admit()
        assert again.status_code == 200, again.json()
        assert again.json()["id"] == first.json()["id"]
        with tenant_context(orgs["a"].pk):
            assert Membership.objects.filter(organization=orgs["a"]).count() == 1
            assert Person.objects.filter(last_name="Muster").count() == 1
