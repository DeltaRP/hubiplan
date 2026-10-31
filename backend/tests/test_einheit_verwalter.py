"""Ersten Verwalter einer Untereinheit in einem Schritt einrichten."""

import pytest
from django.core import mail

from access.catalog import DEPARTMENT_CODES
from access.models import Role, RoleAssignment
from core.tenancy import tenant_context
from members.models import ContactDetails, DepartmentRoleHolder
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess

from .factories import PASSWORD, give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def club(orgs):
    return orgs["a"]


@pytest.fixture
def zug(club):
    return Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)


def einrichten(c, club, zug, member_id):
    return c.post(
        f"/api/orgs/{club.pk}/departments/{zug.pk}/manager/",
        {"member": member_id},
        content_type=JSON,
    )


class TestVerwalterEinrichten:
    def test_alles_in_einem_schritt(self, api, club, zug, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        resp = einrichten(api(board_a), club, zug, m.pk)
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data == {
            "email": "erika@example.org",
            "role": "Leitung",
            "workspace_role": None,
            "mail": "invitation",
        }
        club.refresh_from_db()
        assert club.department_access_enabled
        zug.refresh_from_db()
        assert zug.self_managed  # Verwalter einrichten schaltet die Selbstverwaltung ein
        role = DepartmentRole.objects.get(department=zug)
        assert set(role.permissions) == DEPARTMENT_CODES
        assert DepartmentRoleHolder.objects.get(role=role).membership_id == m.pk
        access = PortalAccess.objects.get()
        assert access.user.email == "erika@example.org"
        assert "Passwort" in mail.outbox[-1].body

        # Die neue Leitung arbeitet im Zug
        access.user.set_password(PASSWORD)
        access.user.save()
        leitung = api(access.user)
        assert leitung.get(f"/api/depts/{zug.pk}/members/").status_code == 200

    def test_zweimal_ist_harmlos(self, api, club, zug, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        c = api(board_a)
        assert einrichten(c, club, zug, m.pk).status_code == 200
        assert einrichten(c, club, zug, m.pk).status_code == 200
        assert DepartmentRole.objects.filter(department=zug).count() == 1
        assert DepartmentRoleHolder.objects.count() == 1
        assert PortalAccess.objects.count() == 1

    def test_mit_arbeitsbereich_auch_vorstand(self, api, club, zug, board_a):
        c = api(board_a)
        resp = c.patch(
            f"/api/orgs/{club.pk}/departments/{zug.pk}/", {"own_workspace": True}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        resp = einrichten(c, club, zug, m.pk)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["workspace_role"] == "Vorstand"
        with tenant_context(zug.pk):
            assignment = RoleAssignment.objects.get(organization=zug)
            role = Role.objects.get(organization=zug)
        assert assignment.user.email == "erika@example.org"
        assert assignment.role == role

        user = assignment.user
        user.set_password(PASSWORD)
        user.save()
        orgs = {o["id"]: o for o in api(user).get("/api/me/organizations/").json()}
        assert "roles.manage" in orgs[zug.pk]["permissions"]
        assert "finance.edit" in orgs[zug.pk]["permissions"]

    def test_ohne_email_fehler_und_nichts_halb(self, api, club, zug, board_a):
        m = make_member(club, "Otto", "Ohnemail")
        # make_member setzt sonst vorname@example.org
        ContactDetails.objects.filter(person=m.person).update(email="")
        resp = einrichten(api(board_a), club, zug, m.pk)
        assert resp.status_code == 400
        assert "E-Mail" in str(resp.json())
        assert not DepartmentRole.objects.filter(department=zug).exists()
        assert not DepartmentRoleHolder.objects.exists()

    def test_bestehendes_konto_bekommt_hinweis(self, api, club, zug, board_a):
        make_user("erika@example.org")
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        resp = einrichten(api(board_a), club, zug, m.pk)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["mail"] == "password"

    def test_nur_mit_recht_und_eigenem_mitglied(self, api, orgs, club, zug, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        leser = make_user("leser@example.org")
        give_role(leser, club, ["members.view"], name="Leser")
        assert einrichten(api(leser), club, zug, m.pk).status_code == 403
        fremd = make_member(orgs["b"], "Fritz", "Fremd", "fritz@example.org")
        assert einrichten(api(board_a), club, zug, fremd.pk).status_code == 400
        assert einrichten(api(board_a), club, zug, "x").status_code == 400
