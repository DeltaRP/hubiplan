"""Einheiten Schritt 4b: Rechnungen im Arbeitsbereich einer Untereinheit.

Die Anfragen laufen unter der eingeschränkten Datenbankrolle, damit RLS greift:
Die Mitgliedsdaten liegen im Datenbereich des Vereins, die Rechnungen im
Datenbereich der Untereinheit.
"""

import uuid
from decimal import Decimal

import pytest
from django.db import connection

from access.models import Role, RoleAssignment
from billing.models import Invoice
from core.rls import APP_ROLE
from core.tenancy import set_rls, tenant_context
from finance.models import Booking
from organizations.models import Department
from portal.models import PortalAccess

from .factories import make_member, make_user

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS nur mit PostgreSQL"),
]
JSON = "application/json"


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
def zug(club):
    return Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)


@pytest.fixture
def gruppe(club, zug):
    return Department.objects.create(
        organization=club, parent=zug, name="Gruppe 1", founding_year=1990
    )


@pytest.fixture
def members(club, zug, gruppe):
    return {
        "anna": make_member(club, "Anna", "Zugmitglied", departments=[zug]),
        "bert": make_member(club, "Bert", "Gruppenmitglied", departments=[gruppe]),
        "carl": make_member(club, "Carl", "Ohnezug"),
    }


@pytest.fixture
def kassierer(api, board_a, club, zug):
    c = api(board_a)
    resp = c.patch(
        f"/api/orgs/{club.pk}/departments/{zug.pk}/", {"own_workspace": True}, content_type=JSON
    )
    assert resp.status_code == 200, resp.json()
    user = make_user("zugkasse@example.org")
    with tenant_context(zug.pk):
        role = Role.objects.get(organization=zug)
        RoleAssignment.objects.create(organization=zug, role=role, user=user)
    return api(user)


@pytest.fixture
def rls(members, kassierer):
    """Ab hier wie im Betrieb: eingeschränkte Rolle, RLS greift."""
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    yield
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
    set_rls(None, None, False)


@pytest.fixture
def base(zug):
    return f"/api/orgs/{zug.pk}/billing"


def rechnung(z, base, membership, amount="25.00"):
    return z.post(
        f"{base}/invoices/",
        {
            "recipient_kind": "member",
            "membership": membership.pk,
            "subject": "Zugfahrt",
            "lines": [{"text": "Fahrt", "amount": amount}],
        },
        content_type=JSON,
    )


def portal(api, board_a, club, membership):
    api(board_a).post(f"/api/orgs/{club.pk}/members/{membership.pk}/access/")
    with tenant_context(club.pk):
        access = PortalAccess.objects.select_related("user").get(membership=membership)
    return access, api(access.user)


@pytest.mark.usefixtures("rls")
class TestRechnungenDerUntereinheit:
    def test_modul_und_rechte(self, zug):
        zug.refresh_from_db()
        assert "billing" in zug.enabled_modules
        with tenant_context(zug.pk):
            role = Role.objects.get(organization=zug)
        assert {"billing.view", "billing.edit"} <= set(role.permissions)

    def test_empfaenger_nur_aus_dem_teilbaum(self, base, kassierer, members):
        names = {r["last_name"] for r in kassierer.get(f"{base}/members/?suche=mitglied").json()}
        assert names == {"Zugmitglied", "Gruppenmitglied"}
        assert kassierer.get(f"{base}/members/?suche=Ohnezug").json() == []
        resp = rechnung(kassierer, base, members["carl"])
        assert resp.status_code == 400
        assert "membership" in resp.json()

    def test_rechnung_nummer_und_kasse(self, zug, base, kassierer, members):
        fin = f"/api/orgs/{zug.pk}/finance"
        account = kassierer.post(
            f"{fin}/accounts/",
            {"name": "Zugkasse", "kind": "cash", "opening_date": "2025-01-01"},
            content_type=JSON,
        ).json()["id"]
        cat = kassierer.post(
            f"{fin}/categories/", {"name": "Fahrten", "kind": "income"}, content_type=JSON
        ).json()["id"]
        resp = kassierer.patch(
            f"{base}/settings/", {"account": account, "category": cat}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()

        resp = rechnung(kassierer, base, members["bert"])
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["recipient_name"].startswith("Bert Gruppenmitglied")
        assert data["recipient_email"] == "bert@example.org"
        assert data["recipient_address"].startswith("Lindenweg 4")
        assert data["issuer_name"] == "Jägerzug"
        resp = kassierer.post(f"{base}/invoices/{data['id']}/finalize/")
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "open"
        assert resp.json()["recipient_name"].startswith("Bert Gruppenmitglied")
        assert kassierer.get(f"{base}/invoices/{data['id']}/pdf/").status_code == 200
        assert kassierer.get(f"{base}/invoices/?mitglied={members['bert'].pk}").json()["count"] == 1

        # Zahlung geht in die Zugkasse
        resp = kassierer.post(
            f"{base}/invoices/{data['id']}/payments/",
            {"date": "2025-02-10", "method": "cash", "account": account},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "paid"
        assert kassierer.get(f"{fin}/bookings/").status_code == 200
        with tenant_context(zug.pk):
            booking = Booking.objects.get(account_id=account)
            invoice = Invoice.objects.get(pk=data["id"])
        assert booking.amount == Decimal("25.00")
        assert booking.counterparty == "Bert Gruppenmitglied"
        assert invoice.organization_id == zug.pk
        assert invoice.membership_id == members["bert"].pk

    def test_kein_beitragslauf_und_keine_lastschrift(self, base, kassierer):
        assert kassierer.get(f"{base}/runs/").status_code == 404
        assert kassierer.get(f"{base}/mandates/").status_code == 404
        resp = kassierer.patch(f"{base}/settings/", {"sepa_enabled": True}, content_type=JSON)
        assert resp.status_code == 400
        assert kassierer.get(f"{base}/overview/").json()["sepa_enabled"] is False

    def test_nur_mitglieder_als_empfaenger(self, base, kassierer, gruppe):
        resp = kassierer.post(
            f"{base}/invoices/",
            {
                "recipient_kind": "department",
                "department": gruppe.pk,
                "lines": [{"text": "x", "amount": "1"}],
            },
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_verein_sieht_zugrechnung_nicht_und_vorstand_liest(
        self, api, board_a, club, base, kassierer, members
    ):
        assert rechnung(kassierer, base, members["anna"]).status_code == 201
        c = api(board_a)
        assert c.get(f"/api/orgs/{club.pk}/billing/invoices/").json()["results"] == []
        # Vorstand darüber liest die Rechnungen der Untereinheit, ändert sie aber nicht
        assert len(c.get(f"{base}/invoices/").json()["results"]) == 1
        assert rechnung(c, base, members["anna"]).status_code == 403

    def test_mitgliederbereich_zeigt_zugrechnung(
        self, api, board_a, club, base, kassierer, members
    ):
        inv = rechnung(kassierer, base, members["anna"]).json()
        assert kassierer.post(f"{base}/invoices/{inv['id']}/finalize/").status_code == 200
        access, anna = portal(api, board_a, club, members["anna"])
        data = anna.get(f"/api/portal/{access.pk}/invoices/").json()
        assert [(i["issuer_name"], i["total"]) for i in data["invoices"]] == [("Jägerzug", "25.00")]
        assert anna.get(f"/api/portal/{access.pk}/invoices/{inv['id']}/pdf/").status_code == 200
        # andere Mitglieder sehen sie nicht
        other, bert = portal(api, board_a, club, members["bert"])
        assert bert.get(f"/api/portal/{other.pk}/invoices/").json()["invoices"] == []
        assert bert.get(f"/api/portal/{other.pk}/invoices/{inv['id']}/pdf/").status_code == 404

    def test_rls_trennt_rechnungen(self, club, zug, base, kassierer, members):
        rechnung(kassierer, base, members["anna"])
        set_rls(club.pk, None)
        assert not Invoice.objects.exists()
        set_rls(zug.pk, None)
        assert Invoice.objects.count() == 1
