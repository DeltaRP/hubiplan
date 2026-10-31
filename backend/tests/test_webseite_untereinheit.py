"""Eigene Webseite einer Untereinheit (z. B. eines Zugs), optional (alles erfunden)."""

from __future__ import annotations

import datetime

import pytest
from django.test import Client
from django.utils import timezone

from access.catalog import ROLES_MANAGE, WEBSITE_MANAGE, codes_for
from access.models import Role, RoleAssignment
from core.tenancy import rls_bypass
from events.models import Event
from members.models import DepartmentRoleHolder
from organizations.models import Department, DepartmentRole
from website.models import Website

from .factories import make_member, make_user

JSON = "application/json"


@pytest.fixture
def club(orgs):
    org = orgs["a"]
    org.enabled_modules = sorted({*(org.enabled_modules or []), "events", "website"})
    org.save()
    return org


@pytest.fixture
def zug(club):
    with rls_bypass():
        return Department.objects.create(
            organization=club, name="Jägerzug", founding_year=1950, own_workspace=True
        )


def patch_unit(api, user, club, unit, **data):
    return api(user).patch(f"/api/orgs/{club.pk}/departments/{unit.pk}/", data, content_type=JSON)


class TestSchalter:
    def test_einschalten_gibt_modul_und_rechte(self, api, club, zug, board_a):
        resp = patch_unit(api, board_a, club, zug, own_website=True)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["own_website"] is True
        zug.refresh_from_db()
        assert "website" in zug.enabled_modules
        with rls_bypass():
            role = Role.objects.get(organization=zug)
        assert ROLES_MANAGE in role.permissions and WEBSITE_MANAGE in role.permissions

    def test_nur_mit_arbeitsbereich(self, api, club, board_a):
        with rls_bypass():
            plain = Department.objects.create(organization=club, name="Ohne", founding_year=1960)
        resp = patch_unit(api, board_a, club, plain, own_website=True)
        assert resp.status_code == 400
        assert "Arbeitsbereich" in resp.json()["own_website"][0]

    def test_nur_wenn_die_einheit_das_modul_hat(self, api, orgs, zug, board_a):
        club = orgs["a"]
        club.enabled_modules = [m for m in club.enabled_modules if m != "website"]
        club.save()
        resp = patch_unit(api, board_a, club, zug, own_website=True)
        assert resp.status_code == 400

    def test_arbeitsbereich_aus_nimmt_webseite_mit(self, api, club, zug, board_a):
        patch_unit(api, board_a, club, zug, own_website=True)
        resp = patch_unit(api, board_a, club, zug, own_workspace=False)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["own_website"] is False

    def test_ausschalten(self, api, club, zug, board_a):
        patch_unit(api, board_a, club, zug, own_website=True)
        assert patch_unit(api, board_a, club, zug, own_website=False).json()["own_website"] is False


@pytest.fixture
def zug_site(api, club, zug, board_a):
    """Zug mit eigener Webseite, Zugführer aus der Mitgliederliste und Gruppe darunter."""
    assert patch_unit(api, board_a, club, zug, own_website=True).status_code == 200
    zug.refresh_from_db()
    erika = make_member(club, "Erika", "Beispiel", email="erika@example.org", departments=[zug])
    otto = make_member(club, "Otto", "Muster", email="otto@example.org")
    with rls_bypass():
        lead = DepartmentRole.objects.create(department=zug, name="Zugführer", on_website=True)
        DepartmentRoleHolder.objects.create(
            role=lead, membership=erika, valid_from=datetime.date(2020, 1, 1)
        )
        # Rolle des Vereins: gehört nicht auf die Zug-Seite
        chair = Role.objects.create(organization=club, name="Vorsitzender", on_website=True)
        RoleAssignment.objects.create(organization=club, role=chair, person=otto.person)
        group = Department.objects.create(
            organization=club, parent=zug, name="Rotte Eins", founding_year=1990
        )
        Department.objects.create(organization=club, name="Anderer Zug", founding_year=1970)
    return {"zug": zug, "group": group, "erika": erika}


def zug_user(zug):
    user = make_user("zug@example.org")
    with rls_bypass():
        role, _ = Role.objects.get_or_create(
            organization=zug, name="Vorstand", defaults={"permissions": codes_for("unit")}
        )
        RoleAssignment.objects.create(
            organization=zug, role=role, user=user, valid_from=datetime.date(2020, 1, 1)
        )
    return user


def get(path):
    return Client().get(f"/api/public/site/v1/{path}")


class TestVerwaltung:
    def test_arbeitsbereich_richtet_webseite_ein(self, api, zug_site):
        zug = zug_site["zug"]
        c = api(zug_user(zug))
        resp = c.post(f"/api/orgs/{zug.pk}/website/", {}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["module_enabled"] is True
        # wählbar: nur die Untereinheiten unter dem Zug
        assert [u["name"] for u in data["units"]] == ["Rotte Eins"]
        with rls_bypass():
            assert Website.objects.get(organization=zug)

    def test_ohne_schalter_keine_webseite(self, api, club, zug, board_a):
        c = api(zug_user(zug))
        assert c.post(f"/api/orgs/{zug.pk}/website/", {}, content_type=JSON).status_code == 404


@pytest.mark.django_db(transaction=True)
class TestOeffentlich:
    @pytest.fixture
    def site(self, zug_site):
        with rls_bypass():
            Website.objects.create(
                organization=zug_site["zug"], public_key="zug-schluessel", state="public"
            )
        return zug_site

    def test_grunddaten(self, site):
        data = get("zug-schluessel/").json()
        assert data["name"] == "Jägerzug"
        assert data["member_of"]["name"] == "Verein A"
        assert [u["slug"] for u in data["units"]] == ["rotte-eins"]

    def test_vorstand_aus_der_mitgliederliste(self, site):
        roles = get("zug-schluessel/board/").json()["roles"]
        assert [r["name"] for r in roles] == ["Zugführer"]
        assert roles[0]["holders"][0]["name"] == "Erika Beispiel"

    def test_termine_des_zugs(self, site, club):
        start = timezone.now() + datetime.timedelta(days=3)
        common = {"organization": club, "starts_at": start, "ends_at": start}
        with rls_bypass():
            Event.objects.create(title="Schützenfest", visibility="public", **common)
            Event.objects.create(
                title="Zugabend", visibility="public", department=site["zug"], **common
            )
            Event.objects.create(
                title="Rottenabend", visibility="public", department=site["group"], **common
            )
        titles = sorted(e["title"] for e in get("zug-schluessel/events/").json()["events"])
        assert titles == ["Rottenabend", "Zugabend"]

    def test_kontakt_an_zugfuehrer(self, site):
        data = get("zug-schluessel/contact/").json()
        assert [r["name"] for r in data["recipients"]] == ["Zugführer"]
