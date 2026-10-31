# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 3: Mitgliederzahlen nach oben, Rechnungen mit Zahlungsstand (erfundene Daten)."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from billing import services as billing
from billing.models import BillingSettings, Invoice, InvoiceLine
from core.tenancy import tenant_context
from finance.models import Account, Booking, Category
from members.models import MemberType
from peering import services
from peering.models import RemoteInvoice, RemoteState

from .factories import give_role, make_member, make_user
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .verbund_netz import release

pytestmark = pytest.mark.django_db
JSON = "application/json"


def account(org):
    with tenant_context(org.pk):
        return Account.objects.create(
            organization=org,
            name="Girokonto",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            bank_name="Musterbank",
            opening_date=datetime.date(2024, 1, 1),
        )


def category(org, kind):
    with tenant_context(org.pk):
        return Category.objects.create(organization=org, name="Verbandsbeiträge", kind=kind)


@pytest.fixture
def members(net, world):
    club = world["club"]
    with net.on(VEREIN):
        with tenant_context(club.pk):
            passiv = MemberType.objects.create(organization=club, name="passiv", active=False)
            intern = MemberType.objects.create(organization=club, name="intern", reported=False)
        make_member(club, "Anna", "Aktiv", birth_date=datetime.date(1980, 5, 17))
        make_member(club, "Bert", "Aktiv", birth_date=datetime.date(2012, 3, 2))
        make_member(club, "Paul", "Passiv", member_type=passiv)
        make_member(club, "Ingo", "Intern", member_type=intern)


def coupled(net, world, members_level="a"):
    lower, upper = couple(net, world)
    with net.on(VEREIN):
        release(lower, {"unit": "on", "events": "on", "members": members_level})
    lower.refresh_from_db()
    upper.refresh_from_db()
    return lower, upper


def fed_settings(fed):
    acc = account(fed)
    cat = category(fed, "income")
    with tenant_context(fed.pk):
        BillingSettings.objects.create(
            organization=fed,
            club_rate_active=Decimal("10"),
            club_rate_passive=Decimal("4"),
            account=acc,
            category=cat,
        )
    return acc


def issue(net, world, upper, amount="30.00"):
    fed = world["fed"]
    with net.on(VERBAND):
        with tenant_context(fed.pk):
            invoice = Invoice.objects.create(
                organization=fed,
                recipient_kind=Invoice.Recipient.CLUB,
                club=upper.remote_unit,
                subject="Verbandsbeitrag 2026",
                date=timezone.localdate(),
                due_date=timezone.localdate() + datetime.timedelta(days=14),
                **billing.club_recipient(upper.remote_unit),
            )
            InvoiceLine.objects.create(
                organization=fed,
                invoice=invoice,
                position=0,
                text="aktive Mitglieder",
                detail="3 × 10,00 €",
                amount=Decimal(amount),
                is_fee=True,
            )
            billing.finalize(invoice)
    return invoice


class TestMitgliederzahlen:
    def test_nur_zahlen_und_beitragsrechnung(self, net, world, members):
        fed = world["fed"]
        lower, upper = coupled(net, world)
        state = RemoteState.objects.get(coupling=upper, key="members")
        assert state.data["total"] == 3  # „intern“ wird nicht gemeldet
        assert {r["kind"] for r in state.data["counts"]} == {"active", "passive"}
        # Keine Namen, nur Geburtsmonat und Anzahl
        assert "Anna" not in str(state.data)
        assert all(set(r) == {"kind", "birth", "n"} for r in state.data["counts"])

        fed_settings(fed)
        with net.on(VERBAND):
            with tenant_context(fed.pk):
                items = billing.plan_federation_run(fed, billing.period(fed, 2026, "yearly", 1))
        item = next(i for i in items if i.club == upper.remote_unit)
        assert item.members == 3
        assert item.total == Decimal("24.00")  # 2 × 10 + 1 × 4

    def test_ohne_freigabe_keine_zahlen(self, net, world, members):
        lower, upper = couple(net, world)
        assert not RemoteState.objects.filter(coupling=upper, key="members").exists()
        with net.on(VEREIN):
            release(lower, {"unit": "on", "members": "a"})
        assert RemoteState.objects.filter(coupling=upper, key="members").exists()
        with net.on(VEREIN):
            release(lower, {"unit": "on"})
        assert not RemoteState.objects.filter(coupling=upper, key="members").exists()


class TestRechnungen:
    def test_rechnung_zahlung_und_rueckmeldung(self, net, world, members):
        fed, club = world["fed"], world["club"]
        lower, upper = coupled(net, world)
        fed_account = fed_settings(fed)
        invoice = issue(net, world, upper)

        incoming = RemoteInvoice.objects.get(coupling=lower)
        assert incoming.number == invoice.display_number
        assert incoming.total == Decimal("30.00")
        assert incoming.data["bank"]["iban"] == "DE89370400440532013000"
        assert incoming.data["lines"][0]["text"] == "aktive Mitglieder"
        assert incoming.file
        sent = RemoteInvoice.objects.get(coupling=upper)
        assert sent.invoice_id == invoice.pk and sent.uid == incoming.uid

        # Teilzahlung beim Aussteller: Verein sieht den Zahlungsstand
        with net.on(VERBAND):
            with tenant_context(fed.pk):
                billing.add_payment(
                    invoice,
                    date=timezone.localdate(),
                    amount=Decimal("10.00"),
                    method="transfer",
                    account=fed_account,
                    user=None,
                )
        incoming.refresh_from_db()
        assert incoming.data["paid"] == "10.00" and not incoming.data["settled"]

        # Verein: PDF abrufen und als bezahlt melden, mit Ausgabe in der eigenen Kasse
        club_account = account(club)
        club_cat = category(club, "expense")
        with net.on(VEREIN):
            c = api(world["club_board"])
            base = f"/api/orgs/{club.pk}/peering/couplings/{lower.pk}"
            data = c.get(f"{base}/").json()
            entry = data["invoices"][0]
            assert entry["incoming"] and entry["paid"] == "10.00"
            resp = c.get(entry["download_url"])
            assert resp.status_code == 200
            assert b"".join(resp.streaming_content).startswith(b"%PDF")
            resp = c.post(
                f"{base}/invoices/{incoming.pk}/paid/",
                {"date": "2026-10-30", "account": club_account.pk, "category": club_cat.pk},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        with tenant_context(club.pk):
            booking = Booking.objects.get(organization=club)
            assert booking.kind == "expense" and booking.amount == Decimal("30.00")
            assert booking.receipts.count() == 1
        sent.refresh_from_db()
        assert sent.paid_reported_on == datetime.date(2026, 10, 30)
        # Ein zweites „bezahlt melden“ legt keine zweite Ausgabe an (Audit 31.10.b, INF-F06)
        with net.on(VEREIN):
            again = c.post(
                f"{base}/invoices/{incoming.pk}/paid/",
                {"date": "2026-10-31", "account": club_account.pk, "category": club_cat.pk},
                content_type=JSON,
            )
        assert again.status_code == 400
        with tenant_context(club.pk):
            assert Booking.objects.filter(organization=club).count() == 1
        # Maßgeblich bleibt der Zahlungseingang beim Aussteller
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.OPEN

    def test_storno(self, net, world, members):
        lower, upper = coupled(net, world)
        fed_settings(world["fed"])
        invoice = issue(net, world, upper)
        with net.on(VERBAND):
            with tenant_context(world["fed"].pk):
                billing.cancel(invoice)
        incoming = RemoteInvoice.objects.get(coupling=lower)
        assert incoming.status == RemoteInvoice.Status.CANCELLED
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/couplings/{lower.pk}"
                f"/invoices/{incoming.pk}/paid/",
                {},
                content_type=JSON,
            )
        assert resp.status_code == 400

    def test_ohne_freigabe_keine_rechnung_im_verbund(self, net, world, members):
        lower, upper = coupled(net, world)
        with net.on(VERBAND):
            release(upper, {"unit": "on", "events": "on"})
        fed_settings(world["fed"])
        issue(net, world, upper)
        assert not RemoteInvoice.objects.exists()

    def test_buchen_braucht_kassenrecht(self, net, world, members):
        lower, upper = coupled(net, world)
        fed_settings(world["fed"])
        issue(net, world, upper)
        incoming = RemoteInvoice.objects.get(coupling=lower)
        club = world["club"]
        with net.on(VEREIN):
            user = make_user("verbund@verein.example")
            give_role(user, club, permissions=["peering.manage"], name="Verbund")
            resp = api(user).post(
                f"/api/orgs/{club.pk}/peering/couplings/{lower.pk}/invoices/{incoming.pk}/paid/",
                {"account": account(club).pk, "category": category(club, "expense").pk},
                content_type=JSON,
            )
        assert resp.status_code == 403


def test_loesen_behaelt_rechnungen(net, world, members):
    lower, upper = coupled(net, world)
    fed_settings(world["fed"])
    issue(net, world, upper)
    with net.on(VEREIN):
        services.end(lower, None)
    assert RemoteInvoice.objects.filter(coupling=lower).exists()
    assert RemoteInvoice.objects.filter(coupling=upper).exists()
    assert not RemoteState.objects.filter(coupling=upper, key="members").exists()


def test_nur_verbundrecht_sieht_keine_rechnungen(net, world, members):
    """Gesamtaudit 30.10.a (BSEC-V02): Rechnungen brauchen die Rechnungsrechte."""
    from access.catalog import PEERING_MANAGE

    lower, upper = coupled(net, world)
    fed_settings(world["fed"])
    issue(net, world, upper)
    incoming = RemoteInvoice.objects.get(coupling=lower)
    club = world["club"]
    with net.on(VEREIN):
        nur = make_user("verbund@verein.example")
        give_role(nur, club, [PEERING_MANAGE], name="Verbundpflege")
        c = api(nur)
        base = f"/api/orgs/{club.pk}/peering/couplings/{lower.pk}"
        data = c.get(f"{base}/").json()
        assert data["invoices"] == [] and "invoices" in data["hidden"]
        assert c.get(f"{base}/invoices/{incoming.pk}/file/").status_code == 403
        resp = c.post(f"{base}/invoices/{incoming.pk}/paid/", {}, content_type=JSON)
        assert resp.status_code == 403
        # der Vorstand mit allen Rechten sieht sie weiter
        data = api(world["club_board"]).get(f"{base}/").json()
        assert len(data["invoices"]) == 1 and data["hidden"] == []
