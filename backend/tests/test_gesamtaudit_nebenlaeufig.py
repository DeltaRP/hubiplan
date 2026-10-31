# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Gesamtaudit B-V01, B-V02, A-F02: Lastschrift nach Widerruf und gleichzeitige Abläufe.

Die Nebenläufigkeitstests nutzen zwei echte PostgreSQL-Verbindungen (zwei Threads):
Der erste Ablauf hält seine Transaktion offen, der zweite muss warten und sieht
danach dessen Ergebnis."""

import datetime
import threading
import time
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.utils import timezone

from billing import sepa, services
from billing.models import DebitRun, Invoice, Mandate
from changes.models import ChangeSet
from core.tenancy import tenant_context
from finance.models import Account
from members import workflows
from members.models import Membership, MemberType

from .factories import make_member
from .test_m9_billing import _private, base, c, club, setup, zug  # noqa: F401
from .test_m11_sepa_abschluss import CREDITOR, next_workday, open_invoice

JSON = "application/json"
WAIT = 10


def sepa_ready(c, base, club):
    c.patch(
        f"{base}/settings/",
        {"sepa_enabled": True, "creditor_id": CREDITOR, "prenotification_days": 5},
        content_type=JSON,
    )
    erika = make_member(club, "Erika", "Müller", "erika@example.org")
    resp = c.post(
        f"{base}/mandates/",
        {
            "membership": erika.pk,
            "holder": "Erika Müller",
            "iban": "DE02120300000000202051",
            "signed_on": str(timezone.localdate() - datetime.timedelta(days=30)),
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    return erika, open_invoice(c, base, erika)


def create_run(c, base, invoice_id):
    return c.post(
        f"{base}/debits/",
        {"invoices": [invoice_id], "collection_date": str(next_workday(6))},
        content_type=JSON,
    )


@pytest.mark.django_db
class TestLastschriftNachAenderung:
    def test_widerrufenes_mandat_sperrt_die_datei(self, c, base, club, setup):
        _erika, invoice_id = sepa_ready(c, base, club)
        run = create_run(c, base, invoice_id).json()
        assert c.get(f"{base}/debits/{run['id']}/xml/").status_code == 200
        mandate = Mandate.objects.get()
        assert c.post(f"{base}/mandates/{mandate.pk}/revoke/").status_code == 200
        resp = c.get(f"{base}/debits/{run['id']}/xml/")
        assert resp.status_code == 400
        assert "widerrufen" in str(resp.json())
        listed = c.get(f"{base}/debits/").json()
        assert "widerrufen" in listed[0]["problems"][0]
        # Verwerfen bleibt möglich
        assert c.post(f"{base}/debits/{run['id']}/cancel/").status_code == 200

    def test_anders_bezahlte_rechnung_sperrt_die_datei(self, c, base, club, setup):
        _erika, invoice_id = sepa_ready(c, base, club)
        run = create_run(c, base, invoice_id).json()
        invoice = Invoice.objects.get(pk=invoice_id)
        # Altbestand: eine Zahlung am Lauf vorbei
        services.add_payment(
            invoice,
            date=timezone.localdate(),
            amount=Decimal("10.00"),
            method="transfer",
            account=Account.objects.get(pk=setup["bank"]),
            user=None,
            debit=True,
        )
        resp = c.get(f"{base}/debits/{run['id']}/xml/")
        assert resp.status_code == 400
        assert "teilweise bezahlt" in str(resp.json())

    def test_keine_mahnung_waehrend_des_einzugs(self, c, base, club, setup):
        from billing.models import DunningLevel

        _erika, invoice_id = sepa_ready(c, base, club)
        create_run(c, base, invoice_id)
        invoice = Invoice.objects.get(pk=invoice_id)
        Invoice.objects.filter(pk=invoice_id).update(due_date=datetime.date(2020, 1, 1))
        level = DunningLevel.objects.create(organization=club, level=1, name="Erinnerung", days=0)
        assert all(i.pk != invoice_id for i, _level in services.dunning_proposals(club))
        with pytest.raises(Exception, match="Lastschriftlauf"):
            services.dun(invoice, level, None)


def in_thread(func):
    """Führt ``func`` in einem eigenen Thread (eigene DB-Verbindung) aus."""
    result: dict = {}

    def run():
        try:
            result["value"] = func()
        except Exception as exc:  # noqa: BLE001 - Ergebnis wird im Test geprüft
            result["error"] = exc
        finally:
            connection.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def hold_then(first, second):
    """``first`` läuft in einer offenen Transaktion, bis ``second`` nachweislich wartet."""
    holding = threading.Event()
    release = threading.Event()

    def run_first():
        with transaction.atomic():
            value = first()
            holding.set()
            release.wait(WAIT)
            return value

    def run_second():
        holding.wait(WAIT)
        return second()

    t1, r1 = in_thread(run_first)
    assert holding.wait(WAIT)
    t2, r2 = in_thread(run_second)
    time.sleep(0.5)
    waited = t2.is_alive()
    release.set()
    t1.join(WAIT)
    t2.join(WAIT)
    assert "error" not in r1, r1
    return waited, r2


@pytest.mark.django_db(transaction=True)
class TestGleichzeitig:
    def test_zweimal_austritt(self, orgs):
        club = orgs["a"]
        membership = make_member(club, "Erika", "Muster")

        def leave(day):
            def run():
                with tenant_context(club.pk):
                    m = Membership.objects.get(pk=membership.pk)
                    workflows.exit_membership(m, day, "exit")

            return run

        waited, second = hold_then(
            leave(datetime.date(2020, 12, 31)), leave(datetime.date(2021, 6, 30))
        )
        assert waited, "der zweite Austritt hat nicht auf den ersten gewartet"
        assert "bereits beendet" in str(second.get("error"))
        with tenant_context(club.pk):
            periods = list(Membership.objects.get(pk=membership.pk).periods.all())
        assert [p.exit_date for p in periods] == [datetime.date(2020, 12, 31)]

    def test_artwechsel_neben_austritt(self, orgs):
        club = orgs["a"]
        membership = make_member(club, "Erika", "Muster", entry_date=datetime.date(2015, 1, 1))
        with tenant_context(club.pk):
            passiv = MemberType.objects.create(organization=club, name="passiv")

        def leave():
            with tenant_context(club.pk):
                m = Membership.objects.get(pk=membership.pk)
                workflows.exit_membership(m, datetime.date(2020, 12, 31), "exit")

        def change():
            with tenant_context(club.pk):
                m = Membership.objects.get(pk=membership.pk)
                workflows.change_type(m, passiv, datetime.date(2022, 1, 1))

        waited, second = hold_then(leave, change)
        assert waited
        # Nach dem Austritt 2020 gibt es 2022 keine Mitgliedschaft mehr
        assert "keine Mitgliedschaft" in str(second.get("error"))

    def test_zahlung_neben_lastschriftlauf(self, api, board_a, club, setup):
        c = api(board_a)
        base = f"/api/orgs/{club.pk}/billing"
        _erika, invoice_id = sepa_ready(c, base, club)
        account = Account.objects.get(pk=setup["bank"])

        def pay():
            with tenant_context(club.pk):
                invoice = Invoice.objects.get(pk=invoice_id)
                services.add_payment(
                    invoice,
                    date=timezone.localdate(),
                    amount=invoice.outstanding,
                    method="transfer",
                    account=account,
                    user=None,
                )

        def debit():
            with tenant_context(club.pk), transaction.atomic():
                return sepa.create_run(club, [invoice_id], next_workday(6), board_a)

        waited, second = hold_then(pay, debit)
        assert waited, "der Lastschriftlauf hat nicht auf die Zahlung gewartet"
        assert "mindestens eine Rechnung" in str(second.get("error"))
        assert not DebitRun.objects.exists()

    def test_zweimal_rueckgaengig(self, api, orgs, board_a):
        club = orgs["a"]
        c = api(board_a)
        membership = make_member(club, "Erika", "Muster")
        url = f"/api/orgs/{club.pk}/members/{membership.pk}/"
        first = c.patch(url, {"city": "Neustadt"}, content_type=JSON)["X-Change-Set"]
        other = c.patch(url, {"street": "Neuer Weg 1"}, content_type=JSON)["X-Change-Set"]

        def mark_done():
            # Wie ein erstes, noch nicht abgeschlossenes Rückgängig desselben Pakets
            with tenant_context(club.pk):
                ChangeSet.objects.select_for_update().get(pk=first)
                ChangeSet.objects.filter(pk=first).update(reverted_by=other)

        def undo_again():
            return api(board_a).post(
                f"/api/orgs/{club.pk}/changes/{first}/undo/", {}, content_type=JSON
            )

        waited, second = hold_then(mark_done, undo_again)
        assert waited, "das zweite Rückgängig hat nicht gewartet"
        resp = second["value"]
        assert resp.status_code == 409
        assert "bereits rückgängig" in str(resp.json())
