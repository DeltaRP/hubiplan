"""Reihenfolge per Ziehen: Rollen, Untereinheiten, Mitgliedsarten, Ehrungen, Textseiten."""

import pytest

from access.models import Role
from members.models import HonoraryTitle, MemberType
from organizations.models import Department, DepartmentRole

from .factories import audit_with

JSON = "application/json"


@pytest.fixture
def client_a(api, board_a):
    return api(board_a)


def ids_of(rows):
    return [r["id"] for r in rows]


class TestRollen:
    def test_ziehen_gilt_fuer_hubiplan_und_webseite(self, client_a, orgs):
        org = orgs["a"]
        a = Role.objects.create(organization=org, name="Kassierer", on_website=True)
        b = Role.objects.create(organization=org, name="Schriftführer", on_website=True)
        url = f"/api/orgs/{org.pk}/roles/"
        current = ids_of(client_a.get(url).json())
        wanted = [b.pk, *[i for i in current if i not in (a.pk, b.pk)], a.pk]
        resp = client_a.post(f"{url}reorder/", {"ids": wanted}, content_type=JSON)
        assert resp.status_code == 200, resp.content
        assert ids_of(client_a.get(url).json()) == wanted
        b.refresh_from_db()
        a.refresh_from_db()
        assert (b.position, b.website_position) == (1, 1)
        assert a.website_position == a.position == len(wanted)
        # Protokoll: je verschobene Rolle ein Eintrag
        assert audit_with("Reihenfolge", organization=org)

    def test_liste_muss_vollstaendig_sein(self, client_a, orgs):
        org = orgs["a"]
        Role.objects.create(organization=org, name="Kassierer")
        url = f"/api/orgs/{org.pk}/roles/"
        current = ids_of(client_a.get(url).json())
        for bad in (current[:-1], [*current, current[0]], "1,2", [*current[:-1], 999999]):
            resp = client_a.post(f"{url}reorder/", {"ids": bad}, content_type=JSON)
            assert resp.status_code == 400

    def test_fremde_einheit_unsichtbar(self, api, orgs, board_b):
        org = orgs["a"]
        resp = api(board_b).post(
            f"/api/orgs/{org.pk}/roles/reorder/", {"ids": []}, content_type=JSON
        )
        assert resp.status_code == 404

    def test_rollen_einer_untereinheit(self, client_a, orgs):
        org = orgs["a"]
        zug = Department.objects.create(organization=org, parent=org, name="Jägerzug")
        first = DepartmentRole.objects.create(department=zug, name="Zugführer")
        second = DepartmentRole.objects.create(department=zug, name="Spieß")
        assert (first.position, second.position) == (1, 2)
        resp = client_a.post(
            f"/api/orgs/{org.pk}/department-roles/reorder/",
            {"department": zug.pk, "ids": [second.pk, first.pk]},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.content
        assert list(
            DepartmentRole.objects.filter(department=zug).values_list("name", flat=True)
        ) == ["Spieß", "Zugführer"]


class TestUntereinheiten:
    def test_je_ebene(self, client_a, orgs):
        org = orgs["a"]
        a = Department.objects.create(organization=org, parent=org, name="A-Zug")
        b = Department.objects.create(organization=org, parent=org, name="B-Zug")
        g1 = Department.objects.create(organization=org, parent=b, name="Gruppe 1")
        g2 = Department.objects.create(organization=org, parent=b, name="Gruppe 2")
        # Neue Einheiten hinten angestellt, je Ebene
        assert (a.sort_order, b.sort_order, g1.sort_order, g2.sort_order) == (1, 2, 1, 2)
        url = f"/api/orgs/{org.pk}/departments/"
        resp = client_a.post(
            f"{url}reorder/", {"parent": None, "ids": [b.pk, a.pk]}, content_type=JSON
        )
        assert resp.status_code == 200, resp.content
        resp = client_a.post(
            f"{url}reorder/", {"parent": b.pk, "ids": [g2.pk, g1.pk]}, content_type=JSON
        )
        assert resp.status_code == 200, resp.content
        # Baumreihenfolge: B mit seinen Gruppen vor A
        assert ids_of(client_a.get(url).json()) == [b.pk, g2.pk, g1.pk, a.pk]
        # Eine Ebene darf nicht mit einer anderen gemischt werden
        resp = client_a.post(
            f"{url}reorder/", {"parent": None, "ids": [a.pk, g1.pk]}, content_type=JSON
        )
        assert resp.status_code == 400


class TestListen:
    def test_mitgliedsarten(self, client_a, orgs):
        org = orgs["a"]
        url = f"/api/orgs/{org.pk}/member-types/"
        MemberType.objects.create(organization=org, name="Passiv")
        MemberType.objects.create(organization=org, name="Aktiv")
        current = ids_of(client_a.get(url).json())
        wanted = list(reversed(current))
        resp = client_a.post(f"{url}reorder/", {"ids": wanted}, content_type=JSON)
        assert resp.status_code == 200, resp.content
        assert ids_of(client_a.get(url).json()) == wanted

    def test_ehrungen(self, client_a, orgs):
        org = orgs["a"]
        url = f"/api/orgs/{org.pk}/honorary-titles/"
        x = HonoraryTitle.objects.create(organization=org, name="Ehrenmitglied")
        y = HonoraryTitle.objects.create(organization=org, name="Ehrenmajor")
        assert x.sort_order < y.sort_order
        resp = client_a.post(f"{url}reorder/", {"ids": [y.pk, x.pk]}, content_type=JSON)
        assert resp.status_code == 200, resp.content
        assert ids_of(client_a.get(url).json()) == [y.pk, x.pk]


def test_webseite_zeigt_untereinheiten_in_gezogener_reihenfolge(client_a, orgs):
    from django.test import Client

    from website.models import Website

    org = orgs["a"]
    org.enabled_modules = ["members", "events", "website"]
    org.save()
    Website.objects.create(organization=org, public_key="schluessel-r", state="public")
    a = Department.objects.create(organization=org, parent=org, name="Alpha")
    b = Department.objects.create(organization=org, parent=org, name="Beta")
    client_a.post(
        f"/api/orgs/{org.pk}/departments/reorder/",
        {"parent": None, "ids": [b.pk, a.pk]},
        content_type=JSON,
    )
    data = Client().get("/api/public/site/v1/schluessel-r/").json()
    assert [u["slug"] for u in data["units"]] == ["beta", "alpha"]


def test_wuerden_je_einheit(client_a, orgs):
    from honors.models import Dignity

    org = orgs["a"]
    zug = Department.objects.create(organization=org, parent=org, name="Jägerzug")
    king = Dignity.objects.create(organization=org, name="König")
    prince = Dignity.objects.create(organization=org, name="Prinz")
    zk = Dignity.objects.create(organization=org, unit=zug, name="Zugkönig")
    assert (king.sort_order, prince.sort_order, zk.sort_order) == (1, 2, 1)
    url = f"/api/orgs/{org.pk}/honors/dignities/reorder/"
    resp = client_a.post(url, {"unit": None, "ids": [prince.pk, king.pk]}, content_type=JSON)
    assert resp.status_code == 200, resp.content
    king.refresh_from_db()
    assert king.sort_order == 2
    # Würden einer Untereinheit gehören nicht in die Liste der Einheit
    resp = client_a.post(url, {"unit": None, "ids": [prince.pk, king.pk, zk.pk]}, content_type=JSON)
    assert resp.status_code == 400
