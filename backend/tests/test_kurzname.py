"""Optionaler Kurzname für Dachverband, Verein und Abteilung."""

import pytest

from core.tenancy import tenant_context
from exchange.importer import Lookups
from members.views import member_queryset, member_rows
from organizations.models import Department, Organization

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


def test_ohne_kurzname_gilt_der_volle_name(orgs):
    assert orgs["a"].display_name == "Verein A"
    orgs["a"].short_name = "VA"
    assert orgs["a"].display_name == "VA"


class TestOrganisation:
    def test_kurzname_speichern_und_in_navigation(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/"
        resp = c.patch(base, {"short_name": "  Hubertusverein "}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["name"] == "Verein A"
        assert data["short_name"] == "Hubertusverein"
        assert data["display_name"] == "Hubertusverein"

        mine = c.get("/api/me/organizations/").json()
        verein = next(o for o in mine if o["id"] == orgs["a"].pk)
        assert verein["name"] == "Verein A"
        assert verein["display_name"] == "Hubertusverein"
        assert verein["parent_name"] == "Testbund"
        assert verein["parent_display_name"] == "Testbund"

    def test_kurzname_hoechstens_50_zeichen(self, api, orgs, board_a):
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/", {"short_name": "x" * 51}, content_type=JSON
        )
        assert resp.status_code == 400
        assert "short_name" in resp.json()

    def test_plattform_legt_verein_mit_kurzname_an(self, api, orgs):
        admin = make_user("plattform@example.org")
        give_role(admin, Organization.platform())
        orgs["federation"].short_name = "BSV"
        orgs["federation"].save()
        resp = api(admin).post(
            "/api/platform/orgs/",
            {
                "type": "club",
                "federation": orgs["federation"].pk,
                "name": "Hubertus-Schützenverein Neuss-Grimlinghausen von 1920",
                "short_name": "Hubertusverein",
                "founding_year": 1920,
                "street": "Am Hubertusplatz 1",
                "postal_code": "41468",
                "city": "Neuss",
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["display_name"] == "Hubertusverein"
        assert data["federation_name"] == "BSV"
        assert Organization.objects.get(pk=data["id"]).short_name == "Hubertusverein"


class TestAbteilung:
    def test_anlegen_und_liste(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/departments/"
        resp = c.post(
            base,
            {"name": "Jägerzug Edelweiß 1952", "short_name": "Edelweiß", "founding_year": 1952},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        deps = c.get(base).json()
        assert deps[0]["name"] == "Jägerzug Edelweiß 1952"
        assert deps[0]["display_name"] == "Edelweiß"

    def test_kurzname_nicht_doppelt_im_verein(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/departments/"
        c.post(base, {"name": "Edelweiß", "founding_year": 1950}, content_type=JSON)
        c.post(
            base,
            {"name": "Grenadierzug", "short_name": "Grenadiere", "founding_year": 1951},
            content_type=JSON,
        )
        # gleicher Kurzname wie der volle Name einer anderen Abteilung
        resp = c.post(
            base,
            {"name": "Jägerzug Edelweiß", "short_name": "edelweiß", "founding_year": 1952},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "short_name" in resp.json()
        # gleicher Kurzname wie eine andere Abteilung
        resp = c.post(
            base,
            {"name": "Neue Grenadiere", "short_name": "Grenadiere", "founding_year": 1953},
            content_type=JSON,
        )
        assert resp.status_code == 400
        # eigener Kurzname bleibt beim Speichern erlaubt
        dep = Department.objects.get(organization=orgs["a"], name="Grenadierzug")
        resp = c.patch(f"{base}{dep.pk}/", {"short_name": "Grenadiere"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        # in einem anderen Verein darf es den Kurznamen geben
        with tenant_context(orgs["b"].pk):
            Department.objects.create(
                organization=orgs["b"], name="X", short_name="Grenadiere", founding_year=1950
            )

    def test_mitgliederliste_kurz_export_voll(self, api, orgs, board_a):
        club = orgs["a"]
        with tenant_context(club.pk):
            dept = Department.objects.create(
                organization=club,
                name="Jägerzug Edelweiß 1952",
                short_name="Edelweiß",
                founding_year=1952,
            )
        make_member(club, "Erika", "Muster", departments=[dept])
        rows = api(board_a).get(f"/api/orgs/{club.pk}/members/").json()["results"]
        assert rows[0]["departments"] == ["Edelweiß"]
        with tenant_context(club.pk):
            memberships = list(member_queryset(club))
            assert member_rows(memberships, club, full_names=True)[0]["departments"] == [
                "Jägerzug Edelweiß 1952"
            ]

    def test_excel_import_erkennt_kurznamen(self, orgs):
        club = orgs["a"]
        with tenant_context(club.pk):
            dept = Department.objects.create(
                organization=club,
                name="Jägerzug Edelweiß 1952",
                short_name="Edelweiß",
                founding_year=1952,
            )
            lookups = Lookups(club, {})
            assert lookups.departments_of("edelweiß") == [dept]
            assert lookups.departments_of("Jägerzug Edelweiß 1952") == [dept]
