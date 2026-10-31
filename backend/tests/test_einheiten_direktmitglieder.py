"""Einheiten Schritt 4b: eigene Mitglieder der obersten Einheit (Dachverband).

Die Anfragen laufen unter der eingeschränkten Datenbankrolle, damit RLS greift.
"""

import pytest
from django.db import connection

from core.rls import APP_ROLE
from core.tenancy import set_rls, tenant_context
from members.models import Membership, Person

from .factories import give_role, make_user
from .test_m2_members import admit, make_types

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS nur mit PostgreSQL"),
]
JSON = "application/json"


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def fed(orgs):
    return orgs["federation"]


@pytest.fixture
def board_fed(fed):
    user = make_user("verband@example.org")
    give_role(user, fed)
    return user


@pytest.fixture
def types(orgs, fed):
    with tenant_context(fed.pk):
        fed_types = make_types(fed)
    with tenant_context(orgs["a"].pk):
        a_types = make_types(orgs["a"])
    return {"fed": fed_types, "a": a_types}


@pytest.fixture
def rls(types, board_fed, board_a):
    """Ab hier wie im Betrieb: eingeschränkte Rolle, RLS greift."""
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    yield
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
    set_rls(None, None, False)


def einschalten(c, fed):
    resp = c.patch(f"/api/orgs/{fed.pk}/", {"direct_members": True}, content_type=JSON)
    assert resp.status_code == 200, resp.json()


@pytest.mark.usefixtures("rls")
class TestDirektmitglieder:
    def test_ohne_schalter_keine_eigenen_mitglieder(self, api, fed, board_fed):
        c = api(board_fed)
        assert c.get(f"/api/orgs/{fed.pk}/members/").status_code == 404
        orgs = {o["id"]: o for o in c.get("/api/me/organizations/").json()}
        assert orgs[fed.pk]["direct_members"] is False

    def test_nur_oberste_einheit(self, api, orgs, board_a):
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/", {"direct_members": True}, content_type=JSON
        )
        assert resp.status_code == 400

    def test_aufnahme_im_dachverband(self, api, fed, types, board_fed):
        c = api(board_fed)
        einschalten(c, fed)
        assert c.get("/api/me/organizations/").json()[0]["direct_members"] is True
        resp = admit(c, fed, types["fed"]["passiv"], last_name="Passiv")
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["federation"]["member_number"] == 1
        rows = c.get(f"/api/orgs/{fed.pk}/members/").json()["results"]
        assert [r["last_name"] for r in rows] == ["Passiv"]
        assert c.get(f"/api/orgs/{fed.pk}/members/{data['id']}/").status_code == 200
        with tenant_context(fed.pk):
            membership = Membership.objects.get(pk=data["id"])
            assert membership.organization_id == fed.pk
            assert membership.scope_id == fed.pk
            assert Person.objects.get().scope_id == fed.pk

    def test_verein_sieht_direktmitglieder_nicht(self, api, orgs, fed, types, board_fed, board_a):
        c = api(board_fed)
        einschalten(c, fed)
        admit(c, fed, types["fed"]["passiv"], last_name="Passiv")
        rows = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/members/").json()["results"]
        assert rows == []
        set_rls(orgs["a"].pk, None)
        assert not Membership.objects.exists()

    def test_nur_eine_aktive_mitgliedschaft(self, api, orgs, fed, types, board_fed, board_a):
        c = api(board_fed)
        einschalten(c, fed)
        resp = admit(c, fed, types["fed"]["aktiv"])
        assert resp.status_code == 201
        person = resp.json()["person_id"]
        # dieselbe Person im Verein: als aktives Mitglied gesperrt, als passives möglich
        a = api(board_a)
        resp = admit(a, orgs["a"], types["a"]["aktiv"], person=person)
        assert resp.status_code == 400
        assert "Testbund" in str(resp.json()["member_type"])
        resp = admit(a, orgs["a"], types["a"]["passiv"], person=person)
        assert resp.status_code == 201, resp.json()
        assert resp.json()["federation"]["member_number"] == 1

    def test_ausschalten_mit_mitgliedern_gesperrt(self, api, fed, types, board_fed):
        c = api(board_fed)
        einschalten(c, fed)
        admit(c, fed, types["fed"]["passiv"])
        resp = c.patch(f"/api/orgs/{fed.pk}/", {"direct_members": False}, content_type=JSON)
        assert resp.status_code == 400

    def test_uebersicht_zeigt_direktmitglieder(self, api, orgs, fed, types, board_fed, board_a):
        fed.federation_member_access = "read"
        fed.save()
        c = api(board_fed)
        einschalten(c, fed)
        admit(c, fed, types["fed"]["passiv"], last_name="Passiv")
        admit(
            api(board_a), orgs["a"], types["a"]["aktiv"], last_name="Adler", birth_date="1970-01-01"
        )
        data = c.get(f"/api/orgs/{fed.pk}/federation/members/").json()
        rows = {(r["last_name"], r["club"]) for r in data["results"]}
        assert rows == {("Passiv", "Testbund"), ("Adler", "Verein A")}
