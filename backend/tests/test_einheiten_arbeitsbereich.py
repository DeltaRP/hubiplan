"""Einheiten Schritt 4a: eigener Arbeitsbereich für Untereinheiten (Kasse, Rollen)."""

import pytest

from access.models import Role, RoleAssignment
from core.tenancy import tenant_context
from finance.models import Account
from organizations.models import Department

from .factories import PASSWORD, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
ACCOUNT = {"name": "Zugkasse", "kind": "cash", "opening_balance": "0", "opening_date": "2025-01-01"}


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.enabled_modules = sorted({*(club.enabled_modules or []), "finance"})
    club.save()
    return club


@pytest.fixture
def zug(club):
    return Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)


def einschalten(c, club, zug):
    resp = c.patch(
        f"/api/orgs/{club.pk}/departments/{zug.pk}/", {"own_workspace": True}, content_type=JSON
    )
    assert resp.status_code == 200, resp.json()
    return resp


class TestArbeitsbereich:
    def test_ohne_schalter_kein_bereich(self, api, club, zug, board_a):
        c = api(board_a)
        assert c.get(f"/api/orgs/{zug.pk}/finance/accounts/").status_code == 404
        ids = [o["id"] for o in c.get("/api/me/organizations/").json()]
        assert zug.pk not in ids

    def test_einschalten_legt_vorstand_an(self, api, club, zug, board_a):
        einschalten(api(board_a), club, zug)
        zug.refresh_from_db()
        assert zug.own_workspace
        assert {"finance", "billing"} <= set(zug.enabled_modules)
        with tenant_context(zug.pk):
            role = Role.objects.get(organization=zug)
        assert role.name == "Vorstand"
        assert set(role.permissions) == {
            "roles.manage",
            "finance.view",
            "finance.edit",
            "billing.view",
            "billing.edit",
        }

    def test_vorstand_darueber_richtet_ein_und_liest(self, api, club, zug, board_a):
        c = api(board_a)
        einschalten(c, club, zug)
        orgs = {o["id"]: o for o in c.get("/api/me/organizations/").json()}
        assert orgs[zug.pk]["type"] == "unit"
        assert set(orgs[zug.pk]["permissions"]) == {"finance.view", "billing.view", "roles.manage"}
        assert c.get(f"/api/orgs/{zug.pk}/finance/accounts/").status_code == 200
        # nur lesen
        resp = c.post(f"/api/orgs/{zug.pk}/finance/accounts/", ACCOUNT, content_type=JSON)
        assert resp.status_code == 403

    def test_zugkassierer_fuehrt_eigene_kasse(self, api, client, club, zug, board_a):
        c = api(board_a)
        einschalten(c, club, zug)
        with tenant_context(zug.pk):
            role = Role.objects.get(organization=zug)
        resp = c.post(
            f"/api/orgs/{zug.pk}/assignments/",
            {"email": "zugkasse@example.org", "role": role.pk},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        kassierer = RoleAssignment.objects.get(role=role).user
        kassierer.set_password(PASSWORD)
        kassierer.save()

        z = api(kassierer)
        resp = z.post(f"/api/orgs/{zug.pk}/finance/accounts/", ACCOUNT, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        # Getrennt: Vereinskasse bleibt verschlossen, die Zugkasse taucht dort nicht auf
        assert z.get(f"/api/orgs/{club.pk}/finance/accounts/").status_code == 404
        names = [a["name"] for a in c.get(f"/api/orgs/{club.pk}/finance/accounts/").json()]
        assert "Zugkasse" not in names
        assert Account.objects.get(name="Zugkasse").organization_id == zug.pk

    def test_ausschalten_sperrt(self, api, club, zug, board_a):
        c = api(board_a)
        einschalten(c, club, zug)
        c.patch(
            f"/api/orgs/{club.pk}/departments/{zug.pk}/",
            {"own_workspace": False},
            content_type=JSON,
        )
        assert c.get(f"/api/orgs/{zug.pk}/finance/accounts/").status_code == 404

    def test_fremder_vorstand_sieht_nichts(self, api, club, zug, board_a, board_b):
        einschalten(api(board_a), club, zug)
        b = api(board_b)
        assert b.get(f"/api/orgs/{zug.pk}/finance/accounts/").status_code == 404
        assert zug.pk not in [o["id"] for o in b.get("/api/me/organizations/").json()]

    def test_gruppe_unter_zug_erbt_vom_zugvorstand(self, api, club, zug, board_a):
        c = api(board_a)
        einschalten(c, club, zug)
        gruppe = Department.objects.create(
            organization=club, parent=zug, name="Gruppe 1", founding_year=1990
        )
        einschalten(c, club, gruppe)
        zugvorstand = make_user("zugvorstand@example.org")
        with tenant_context(zug.pk):
            role = Role.objects.get(organization=zug)
            RoleAssignment.objects.create(organization=zug, role=role, user=zugvorstand)
        z = api(zugvorstand)
        orgs = {o["id"]: o for o in z.get("/api/me/organizations/").json()}
        assert set(orgs) == {zug.pk, gruppe.pk}
        expected = {"finance.view", "billing.view", "roles.manage"}
        assert set(orgs[gruppe.pk]["permissions"]) == expected


def test_rls_zugkasse(api, club, zug, board_a):
    from core.tenancy import set_rls

    from .test_rls import as_app_role

    einschalten(api(board_a), club, zug)
    with tenant_context(zug.pk):
        Account.objects.create(organization=zug, name="Zugkasse", opening_date="2025-01-01")
    with tenant_context(club.pk):
        Account.objects.create(organization=club, name="Vereinskasse", opening_date="2025-01-01")
    with as_app_role():
        set_rls(club.pk, None)
        assert list(Account.objects.values_list("name", flat=True)) == ["Vereinskasse"]
        set_rls(zug.pk, None)
        assert list(Account.objects.values_list("name", flat=True)) == ["Zugkasse"]
