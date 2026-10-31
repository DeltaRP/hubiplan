"""Einheiten Schritt 3: Untereinheiten mit eigenen Untereinheiten (z. B. Zug › Gruppe)."""

import pytest

from members.models import DepartmentRoleHolder
from organizations.models import Department, DepartmentRole
from organizations.tree import MAX_DEPTH, UnitTree
from portal.models import PortalAccess

from .factories import make_member

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.department_access_enabled = True
    club.department_label, club.department_label_plural = "Zug", "Züge"
    club.department_label_gender, club.department_label_genitive = "m", "Zugs"
    club.save()
    return club


@pytest.fixture
def zug(club):
    return Department.objects.create(
        self_managed=True, organization=club, name="Jägerzug", founding_year=1950
    )


def base(club) -> str:
    return f"/api/orgs/{club.pk}/departments/"


def anlegen(c, club, name, parent=None):
    return c.post(
        base(club),
        {"name": name, "founding_year": 1990, "parent_unit": parent},
        content_type=JSON,
    )


class TestBaum:
    def test_gruppe_unter_zug(self, club, zug, api, board_a):
        c = api(board_a)
        resp = anlegen(c, club, "Gruppe 1", zug.pk)
        assert resp.status_code == 201, resp.json()
        gruppe = Department.objects.get(pk=resp.json()["id"])
        assert gruppe.parent_id == zug.pk
        assert gruppe.organization_id == club.pk
        # Bezeichnung nach der Vorgabe des Zugs („Gruppe“)
        assert gruppe.label == "Gruppe"
        rows = c.get(base(club)).json()
        assert [(r["name"], r["depth"], r["parent_unit"]) for r in rows] == [
            ("Jägerzug", 0, None),
            ("Gruppe 1", 1, zug.pk),
        ]
        assert rows[1]["path"] == "Jägerzug › Gruppe 1"
        assert rows[0]["child_terms"]["pl"] == "Gruppen"

    def test_bezeichnung_der_gruppen_aendern(self, club, zug, api, board_a):
        c = api(board_a)
        gruppe_id = anlegen(c, club, "Gruppe 1", zug.pk).json()["id"]
        resp = c.patch(
            f"{base(club)}{zug.pk}/",
            {"department_label": "Rotte", "department_label_plural": "Rotten"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert Department.objects.get(pk=gruppe_id).label == "Rotte"
        # Der Zug selbst behält seine Bezeichnung
        zug.refresh_from_db()
        assert zug.label == "Zug"

    def test_gleicher_name_in_verschiedenen_zuegen(self, club, zug, api, board_a):
        c = api(board_a)
        other = Department.objects.create(
            self_managed=True, organization=club, name="Schützenzug", founding_year=1960
        )
        assert anlegen(c, club, "Gruppe 1", zug.pk).status_code == 201
        assert anlegen(c, club, "Gruppe 1", other.pk).status_code == 201
        assert anlegen(c, club, "gruppe 1", zug.pk).status_code == 400

    def test_kein_kreis_und_fremder_bereich(self, club, zug, orgs, api, board_a):
        c = api(board_a)
        gruppe_id = anlegen(c, club, "Gruppe 1", zug.pk).json()["id"]
        resp = c.patch(f"{base(club)}{zug.pk}/", {"parent_unit": gruppe_id}, content_type=JSON)
        assert resp.status_code == 400
        assert "parent_unit" in resp.json()
        fremd = Department.objects.create(
            self_managed=True, organization=orgs["b"], name="Fremd", founding_year=1960
        )
        assert anlegen(c, club, "Gruppe 2", fremd.pk).status_code == 400

    def test_hoechstens_sechs_ebenen(self, club, zug, api, board_a):
        c = api(board_a)
        parent = zug.pk
        for level in range(2, MAX_DEPTH + 1):
            resp = anlegen(c, club, f"Ebene {level}", parent)
            assert resp.status_code == 201, resp.json()
            parent = resp.json()["id"]
        assert anlegen(c, club, "Zu tief", parent).status_code == 400

    def test_loeschen_und_deaktivieren_mit_untereinheiten(self, club, zug, api, board_a):
        c = api(board_a)
        gruppe_id = anlegen(c, club, "Gruppe 1", zug.pk).json()["id"]
        resp = c.delete(f"{base(club)}{zug.pk}/")
        assert resp.status_code == 400
        assert "Gruppen" in str(resp.json())
        assert c.delete(f"{base(club)}{gruppe_id}/").status_code == 204
        assert c.delete(f"{base(club)}{zug.pk}/").status_code == 204

    def test_stilllegen_nimmt_untereinheiten_mit(self, club, zug, api, board_a):
        """FQ-14: stilllegen legt alles darunter still, reaktivieren holt es zurück."""
        c = api(board_a)
        gruppe_id = anlegen(c, club, "Gruppe 1", zug.pk).json()["id"]
        stillgelegt_id = anlegen(c, club, "Gruppe 2", zug.pk).json()["id"]
        unter_id = anlegen(c, club, "Riege", stillgelegt_id).json()["id"]
        resp = c.patch(f"{base(club)}{stillgelegt_id}/", {"is_active": False}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert not Department.objects.get(pk=unter_id).is_active

        resp = c.patch(f"{base(club)}{zug.pk}/", {"is_active": False}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert not Department.objects.filter(
            pk__in=[gruppe_id, stillgelegt_id, unter_id], is_active=True
        ).exists()

        resp = c.patch(f"{base(club)}{zug.pk}/", {"is_active": True}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert Department.objects.get(pk=gruppe_id).is_active
        # Von Hand stillgelegt bleibt stillgelegt, mit allem darunter
        assert not Department.objects.get(pk=stillgelegt_id).is_active
        assert not Department.objects.get(pk=unter_id).is_active
        resp = c.patch(f"{base(club)}{stillgelegt_id}/", {"is_active": True}, content_type=JSON)
        assert Department.objects.get(pk=unter_id).is_active

    def test_verein_stilllegen_legt_zuege_still(self, club, zug):
        club.is_active = False
        club.save()
        zug.refresh_from_db()
        assert not zug.is_active and zug.inactive_by_parent
        club.is_active = True
        club.save(update_fields=["is_active"])
        zug.refresh_from_db()
        assert zug.is_active and not zug.inactive_by_parent

    def test_baum_hilfen(self, club, zug):
        gruppe = Department.objects.create(
            self_managed=True, organization=club, parent=zug, name="Gruppe 1", founding_year=1990
        )
        tree = UnitTree.of(club.pk)
        assert tree.subtree(zug.pk) == [zug.pk, gruppe.pk]
        assert tree.ancestors(gruppe.pk) == [gruppe.pk, zug.pk]
        assert tree.with_ancestors([gruppe.pk]) == {zug.pk, gruppe.pk}


class TestMitgliederImBaum:
    def test_zug_zaehlt_mitglieder_der_gruppen(self, club, zug, api, board_a):
        gruppe = Department.objects.create(
            self_managed=True, organization=club, parent=zug, name="Gruppe 1", founding_year=1990
        )
        make_member(club, "Zora", "Zug", departments=[zug])
        make_member(club, "Gerd", "Gruppe", departments=[gruppe])
        make_member(club, "Otto", "Ohne")
        c = api(board_a)
        rows = c.get(f"/api/orgs/{club.pk}/members/?abteilung={zug.pk}").json()["results"]
        assert sorted(r["first_name"] for r in rows) == ["Gerd", "Zora"]
        rows = c.get(f"/api/orgs/{club.pk}/members/?abteilung={gruppe.pk}").json()["results"]
        assert [r["first_name"] for r in rows] == ["Gerd"]

    def test_rolle_im_zug_gilt_fuer_gruppen(self, club, zug, api, board_a):
        gruppe = Department.objects.create(
            self_managed=True, organization=club, parent=zug, name="Gruppe 1", founding_year=1990
        )
        role = DepartmentRole.objects.create(
            organization=club,
            department=zug,
            name="Zugführer",
            permissions=["dept.members.view"],
        )
        m = make_member(club, "Karl", "Kasse", "karl@example.org", departments=[zug])
        DepartmentRoleHolder.objects.create(
            organization=club, membership=m, role=role, valid_from="2020-01-01"
        )
        make_member(club, "Gerd", "Gruppe", departments=[gruppe])
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        user = PortalAccess.objects.get(membership=m).user
        user.set_password("Sicheres-Passwort-123")
        user.save()

        c = api(user)
        ctx = c.get("/api/me/contexts/").json()
        assert sorted(d["name"] for d in ctx["departments"]) == ["Gruppe 1", "Jägerzug"]
        rows = c.get(f"/api/depts/{zug.pk}/members/").json()["results"]
        assert sorted(r["first_name"] for r in rows) == ["Gerd", "Karl"]
        rows = c.get(f"/api/depts/{gruppe.pk}/members/").json()["results"]
        assert [r["first_name"] for r in rows] == ["Gerd"]
        info = c.get(f"/api/depts/{gruppe.pk}/").json()
        assert info["path"] == "Jägerzug › Gruppe 1"
        assert info["terms"]["sg"] == "Gruppe"
