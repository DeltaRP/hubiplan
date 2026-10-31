"""Listen der Abteilungen (Verein) und Vereine (Dachverband) für die Tabellenansicht."""

import pytest

from audit.models import AuditEntry
from core.tenancy import rls_bypass, tenant_context
from organizations.models import Department, Organization

from .factories import give_role, make_member, make_org, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def board_fed(orgs):
    user = make_user("verband@example.org")
    give_role(user, orgs["federation"])
    return user


def zug(club, name="1. Zug"):
    with tenant_context(club.pk):
        return Department.objects.create(organization=club, name=name, founding_year=1950)


class TestAbteilungen:
    def test_mitgliederzahl(self, api, orgs, board_a):
        club = orgs["a"]
        z1, z2 = zug(club), zug(club, "2. Zug")
        make_member(club, "Erika", "Muster", departments=[z1])
        make_member(club, "Max", "Muster", departments=[z1])
        resp = api(board_a).get(f"/api/orgs/{club.pk}/departments/")
        assert resp.status_code == 200
        counts = {d["name"]: d["member_count"] for d in resp.json()}
        assert counts == {"1. Zug": 2, "2. Zug": 0}
        detail = api(board_a).get(f"/api/orgs/{club.pk}/departments/{z1.pk}/").json()
        assert detail["member_count"] == 2
        assert z2

    def test_loeschen_leer(self, api, orgs, board_a):
        z = zug(orgs["a"])
        resp = api(board_a).delete(f"/api/orgs/{orgs['a'].pk}/departments/{z.pk}/")
        assert resp.status_code == 204
        with tenant_context(orgs["a"].pk):
            assert not Department.objects.filter(pk=z.pk).exists()

    def test_loeschen_mit_mitgliedern_verweigert(self, api, orgs, board_a):
        club = orgs["a"]
        club.department_label = "Zug"
        club.department_label_plural = "Züge"
        club.department_label_gender = "m"
        club.save()
        z = zug(club)
        make_member(club, "Erika", "Muster", departments=[z])
        resp = api(board_a).delete(f"/api/orgs/{club.pk}/departments/{z.pk}/")
        assert resp.status_code == 400
        text = str(resp.json())
        assert "Dieser Zug" in text and "den Zug" in text
        assert "Abteilung" not in text
        with tenant_context(club.pk):
            assert Department.objects.filter(pk=z.pk).exists()
            # Kein Protokolleintrag für ein Löschen, das nicht stattfand
            assert not AuditEntry.objects.filter(organization=club, action="delete").exists()


class TestVereineImDachverband:
    def test_liste_nur_eigene_vereine(self, api, orgs, board_fed):
        other = make_org("Anderer Bund", "federation")
        make_org("Fremdverein", parent=other)
        orgs["b"].is_active = False
        orgs["b"].save()
        resp = api(board_fed).get(f"/api/orgs/{orgs['federation'].pk}/clubs/")
        assert resp.status_code == 200
        data = {c["name"]: c for c in resp.json()}
        assert set(data) == {"Verein A", "Verein B"}
        assert data["Verein B"]["is_active"] is False
        assert data["Verein A"]["city"] == "Musterstadt"

    def test_aendern_und_deaktivieren(self, api, orgs, board_fed):
        c = api(board_fed)
        url = f"/api/orgs/{orgs['federation'].pk}/clubs/{orgs['a'].pk}/"
        resp = c.patch(url, {"name": "Verein A neu", "city": "Neuss"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        resp = c.patch(url, {"is_active": False}, content_type=JSON)
        assert resp.status_code == 200
        club = Organization.objects.get(pk=orgs["a"].pk)
        assert (club.name, club.city, club.is_active) == ("Verein A neu", "Neuss", False)
        with rls_bypass():
            assert AuditEntry.objects.filter(organization=club, action="update").count() == 2
            assert (
                AuditEntry.objects.filter(organization=orgs["federation"], action="update").count()
                == 2
            )
        # Deaktiviert: Der Vorstand des Vereins kommt nicht mehr hinein, Daten bleiben
        assert Organization.objects.filter(pk=club.pk).exists()

    def test_kein_loeschen(self, api, orgs, board_fed):
        url = f"/api/orgs/{orgs['federation'].pk}/clubs/{orgs['a'].pk}/"
        assert api(board_fed).delete(url).status_code == 405

    def test_fremder_verein_unerreichbar(self, api, orgs, board_fed):
        url = f"/api/orgs/{orgs['federation'].pk}/clubs/{orgs['c'].pk}/"
        assert api(board_fed).patch(url, {"name": "X"}, content_type=JSON).status_code == 404

    def test_ohne_recht(self, api, orgs):
        user = make_user("leser@example.org")
        give_role(user, orgs["federation"], permissions=["members.view"], name="Leser")
        assert api(user).get(f"/api/orgs/{orgs['federation'].pk}/clubs/").status_code == 403

    def test_nur_im_dachverband(self, api, orgs, board_a):
        assert api(board_a).get(f"/api/orgs/{orgs['a'].pk}/clubs/").status_code == 404

    def test_gruendungsjahr_geprueft(self, api, orgs, board_fed):
        url = f"/api/orgs/{orgs['federation'].pk}/clubs/{orgs['a'].pk}/"
        resp = api(board_fed).patch(url, {"founding_year": 3000}, content_type=JSON)
        assert resp.status_code == 400
