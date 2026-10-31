"""Ein Einheitentyp: Die Art folgt aus Lage und Schalter „führt eigene Mitglieder“."""

import pytest

from access.catalog import CLUBS_MANAGE, MEMBERS_VIEW, codes_for
from access.models import Role
from core.tenancy import tenant_context
from members.models import Membership, Person
from organizations.models import Department, Organization

from .factories import give_role, make_org, make_user

JSON = "application/json"
pytestmark = pytest.mark.django_db

BASE = {"founding_year": 2001, "street": "Weg 2", "postal_code": "54321", "city": "Neustadt"}


@pytest.fixture
def admin(db, django_user_model):
    return django_user_model.objects.create_superuser(email="admin@example.org", password="x")


def create(api, admin, **data):
    return api(admin).post("/api/platform/orgs/", {**BASE, **data}, content_type=JSON)


class TestAnlegen:
    def test_oberste_einheit_mit_mitgliedern(self, api, admin):
        resp = create(api, admin, name="Freier Verein", keeps_members=True)
        assert resp.status_code == 201, resp.json()
        org = Organization.objects.get(name="Freier Verein")
        assert org.type == "club" and org.keeps_members
        assert org.label == "Verein"
        assert resp.json()["keeps_members"] is True
        assert resp.json()["can_switch_members"] is True

    def test_oberste_einheit_ohne_mitglieder(self, api, admin):
        resp = create(api, admin, name="Bund", keeps_members=False)
        assert resp.status_code == 201, resp.json()
        org = Organization.objects.get(name="Bund")
        assert org.type == "federation" and not org.keeps_members
        assert org.department_label == "Verein"
        role = Role.objects.get(organization=org)
        assert CLUBS_MANAGE in role.permissions

    def test_standard_mit_mitgliedern(self, api, admin):
        assert create(api, admin, name="Ohne Angabe").status_code == 201
        assert Organization.objects.get(name="Ohne Angabe").type == "club"

    def test_darunter_immer_mit_mitgliedern(self, api, admin, orgs):
        fed = orgs["federation"]
        resp = create(api, admin, name="Neu", federation=fed.pk, keeps_members=False)
        assert resp.status_code == 400
        assert "keeps_members" in resp.json()
        resp = create(api, admin, name="Neu", federation=fed.pk)
        assert resp.status_code == 201
        assert Organization.objects.get(name="Neu").parent == fed

    def test_nicht_unter_einheit_mit_mitgliedern(self, api, admin, orgs):
        resp = create(api, admin, name="Neu", federation=orgs["c"].pk)
        assert resp.status_code == 400

    def test_alte_aufrufe_mit_art(self, api, admin):
        resp = create(api, admin, name="Bund alt", type="federation")
        assert resp.status_code == 201
        assert Organization.objects.get(name="Bund alt").type == "federation"


class TestUmschalten:
    def test_leere_einheit_wechselt(self, api, admin):
        create(api, admin, name="Probe", keeps_members=True)
        org = Organization.objects.get(name="Probe")
        resp = api(admin).patch(
            f"/api/platform/orgs/{org.pk}/", {"keeps_members": False}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        org.refresh_from_db()
        assert org.type == "federation"
        assert (org.label, org.department_label) == ("Dachverband", "Verein")
        role = Role.objects.get(organization=org)
        assert set(role.permissions) >= set(codes_for("federation"))
        # und zurück
        resp = api(admin).patch(
            f"/api/platform/orgs/{org.pk}/", {"keeps_members": True}, content_type=JSON
        )
        assert resp.status_code == 200
        org.refresh_from_db()
        assert org.type == "club" and org.label == "Verein"
        assert CLUBS_MANAGE not in Role.objects.get(organization=org).permissions

    def test_eigene_bezeichnung_bleibt(self, api, admin):
        create(api, admin, name="Probe", keeps_members=True, label="Gilde", label_plural="Gilden")
        org = Organization.objects.get(name="Probe")
        api(admin).patch(
            f"/api/platform/orgs/{org.pk}/", {"keeps_members": False}, content_type=JSON
        )
        org.refresh_from_db()
        assert org.label == "Gilde"

    def test_mit_mitgliedern_gesperrt(self, api, admin, orgs):
        club = orgs["c"]
        with tenant_context(club.pk):
            person = Person.objects.create(
                scope=club, first_name="A", last_name="B", birth_date="1990-01-01"
            )
            Membership.objects.create(organization=club, scope=club, person=person)
        resp = api(admin).patch(
            f"/api/platform/orgs/{club.pk}/", {"keeps_members": False}, content_type=JSON
        )
        assert resp.status_code == 400
        club.refresh_from_db()
        assert club.type == "club"

    def test_mit_untereinheiten_gesperrt(self, api, admin, orgs):
        club = orgs["c"]
        Department.objects.create(organization=club, name="Zug 1")
        resp = api(admin).patch(
            f"/api/platform/orgs/{club.pk}/", {"keeps_members": False}, content_type=JSON
        )
        assert resp.status_code == 400

    def test_unter_dachverband_gesperrt(self, api, admin, orgs):
        resp = api(admin).patch(
            f"/api/platform/orgs/{orgs['a'].pk}/", {"keeps_members": False}, content_type=JSON
        )
        assert resp.status_code == 400
        assert orgs["a"].keeps_members

    def test_dachverband_mit_vereinen_fuehrt_zusaetzlich(self, api, admin, orgs):
        fed = orgs["federation"]
        resp = api(admin).patch(
            f"/api/platform/orgs/{fed.pk}/", {"keeps_members": True}, content_type=JSON
        )
        assert resp.status_code == 200
        fed.refresh_from_db()
        assert fed.type == "federation" and fed.direct_members

    def test_vorstand_schaltet_in_einstellungen(self, api):
        org = make_org("Leer")
        user = make_user("v@example.org")
        give_role(user, org)
        resp = api(user).patch(f"/api/orgs/{org.pk}/", {"keeps_members": False}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        org.refresh_from_db()
        assert org.type == "federation"
        assert api(user).get(f"/api/orgs/{org.pk}/").json()["keeps_members"] is False
        assert MEMBERS_VIEW in Role.objects.get(organization=org).permissions


class TestJubilaeumsstufen:
    @pytest.mark.parametrize("bad", [[25.9], [True], ["abc"], [None], "25"])
    def test_keine_ganzen_jahre(self, api, bad):
        org = make_org("Verein J")
        user = make_user("j@example.org")
        give_role(user, org)
        for field in ("jubilee_years", "unit_jubilee_years"):
            resp = api(user).patch(f"/api/orgs/{org.pk}/", {field: bad}, content_type=JSON)
            assert resp.status_code == 400, (field, bad)

    def test_ganze_jahre_auch_als_text(self, api):
        org = make_org("Verein J")
        user = make_user("j@example.org")
        give_role(user, org)
        resp = api(user).patch(
            f"/api/orgs/{org.pk}/", {"jubilee_years": ["25", 10, 25.0]}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        org.refresh_from_db()
        assert org.jubilee_years == [10, 25]
