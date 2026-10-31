"""Würden an Untereinheiten weitergeben und Menü „Würdenträger“ (Ralf 2026-10-31,
alles erfunden)."""

import pytest
from django.test import Client

from core.tenancy import tenant_context
from honors.models import Companion, Dignity, Reign
from members.models import HonoraryTitle, HonoraryTitleAward
from organizations.models import Department
from website import services
from website.models import Website

from .factories import make_member
from .test_rls import as_app_role

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def buergerkoenig(orgs):
    fed = orgs["federation"]
    d = Dignity.objects.create(organization=fed, name="Bundeskönig", share_down=True)
    r = Reign.objects.create(
        organization=fed, dignity=d, year=2024, name="Karl Bürger", origin=orgs["a"]
    )
    Companion.objects.create(organization=fed, reign=r, label="Königin", name="Anna Bürger")
    # Aus Verein B und ohne Herkunft: für Verein A nicht sichtbar
    Reign.objects.create(organization=fed, dignity=d, year=2023, name="Bert B", origin=orgs["b"])
    Reign.objects.create(
        organization=fed, dignity=d, year=1925, name="Uralt König", origin_name="Alter Verein"
    )
    intern = Dignity.objects.create(organization=fed, name="Verbandsprinz")
    Reign.objects.create(organization=fed, dignity=intern, year=2024, name="Geheim Prinz")
    return d


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    return Website.objects.create(organization=org, public_key="schluessel-x", state="public")


def honors():
    return Client().get("/api/public/site/v1/schluessel-x/honors/").json()["dignities"]


def info():
    return Client().get("/api/public/site/v1/schluessel-x/").json()


class TestVerwaltung:
    def test_verein_sieht_weitergegebene_wuerden(self, orgs, board_a, board_c, api, buergerkoenig):
        resp = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/honors/shared/")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [d["name"] for d in data] == ["Bundeskönig"]
        assert data[0]["owner"] == "Testbund"
        assert data[0]["reigns"][0]["numbered_name"] == "Karl Bürger"
        assert data[0]["reigns"][0]["companions"] == [{"label": "Königin", "name": "Anna Bürger"}]
        # Verein ohne Dachverband: nichts
        assert api(board_c).get(f"/api/orgs/{orgs['c'].pk}/honors/shared/").json() == []

    def test_herkunft_auswahl_und_frei(self, orgs, board_a, api):
        fed = orgs["federation"]
        from .factories import give_role, make_user

        fed_user = make_user("verband@example.org")
        give_role(fed_user, fed)
        c = api(fed_user)
        origins = c.get(f"/api/orgs/{fed.pk}/honors/origins/").json()
        assert {o["name"] for o in origins} == {"Verein A", "Verein B"}
        d = c.post(
            f"/api/orgs/{fed.pk}/honors/dignities/", {"name": "Bundeskönig"}, "application/json"
        )
        dignity = d.json()["id"]
        ok = c.post(
            f"/api/orgs/{fed.pk}/honors/reigns/",
            {"dignity": dignity, "year": 1925, "name": "Uralt", "origin_name": " Alter Verein "},
            "application/json",
        )
        assert ok.status_code == 201, ok.content
        assert ok.json()["origin_text"] == "Alter Verein"
        ok = c.post(
            f"/api/orgs/{fed.pk}/honors/reigns/",
            {"dignity": dignity, "year": 1926, "name": "Neu", "origin": orgs["a"].pk},
            "application/json",
        )
        assert ok.json()["origin_text"] == "Verein A"
        bad = c.post(
            f"/api/orgs/{fed.pk}/honors/reigns/",
            {"dignity": dignity, "year": 1927, "name": "X", "origin": orgs["c"].pk},
            "application/json",
        )
        assert bad.status_code == 400

    def test_herkunft_aus_zug_vorbelegt(self, orgs, board_a, api):
        from members.models import DepartmentMembership

        org = orgs["a"]
        zug = Department.objects.create(organization=org, parent=org, name="Jägerzug")
        otto = make_member(org, "Otto", "Muster")
        DepartmentMembership.objects.create(
            organization=org, membership=otto, department=zug, valid_from="2000-01-01"
        )
        koenig = Dignity.objects.create(organization=org, name="König")
        resp = api(board_a).post(
            f"/api/orgs/{org.pk}/honors/reigns/",
            {"dignity": koenig.pk, "year": 2024, "person": otto.person_id},
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()["origin"] == zug.pk

    def test_schalter_ueber_die_schnittstelle(self, orgs, board_a, api):
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/honors/dignities/",
            {"name": "König", "share_down": True},
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()["share_down"] is True

    def test_rls_nur_weitergegebene(self, orgs, board_a, buergerkoenig):
        with as_app_role(), tenant_context(orgs["a"].pk, board_a.pk):
            names = set(Dignity.objects.values_list("name", flat=True))
            reigns = set(Reign.objects.values_list("name", flat=True))
            companions = set(Companion.objects.values_list("name", flat=True))
        assert names == {"Bundeskönig"}
        assert reigns == {"Karl Bürger"}
        assert companions == {"Anna Bürger"}
        with as_app_role(), tenant_context(orgs["c"].pk, board_a.pk):
            assert not Dignity.objects.exists()


class TestWebseite:
    def test_nur_mit_schalter(self, orgs, site, buergerkoenig):
        assert honors() == []
        site.include_parent_honors = True
        site.save()
        data = honors()
        assert [d["name"] for d in data] == ["Bundeskönig"]
        assert data[0]["owner"] == "Testbund"
        assert "Geheim" not in str(data)
        assert info()["honors_label"] == "Bundeskönig"

    def test_einwilligung_der_vergebenden_einheit(self, orgs, site, buergerkoenig):
        fed = orgs["federation"]
        fed.direct_members = True
        fed.save()
        otto = make_member(fed, "Otto", "Verband")
        Reign.objects.create(
            organization=fed, dignity=buergerkoenig, year=2025, person=otto.person, origin=orgs["a"]
        )
        services.set_entry(otto, "honors", True, "paper", None)  # Widerspruch
        site.include_parent_honors = True
        site.save()
        reigns = honors()[0]["reigns"]
        assert [r["holder"]["name"] for r in reigns] == ["Karl Bürger"]

    def test_zugseite_zeigt_weitergegebene_vereinswuerde(self, orgs):
        org = orgs["a"]
        org.enabled_modules = ["members", "website"]
        org.save()
        zug = Department.objects.create(organization=org, parent=org, name="Jägerzug")
        zug.enabled_modules = ["website"]
        zug.save()
        koenig = Dignity.objects.create(organization=org, name="Hubertuskönig", share_down=True)
        Reign.objects.create(
            organization=org, dignity=koenig, year=2024, name="Hans Hubertus", origin=zug
        )
        Reign.objects.create(organization=org, dignity=koenig, year=2023, name="Anderer Zug")
        zk = Dignity.objects.create(organization=org, unit=zug, name="Zugkönig")
        Reign.objects.create(organization=org, dignity=zk, year=2024, name="Zug Mann")
        Website.objects.create(
            organization=zug, public_key="schluessel-z", state="public", include_parent_honors=True
        )
        resp = Client().get("/api/public/site/v1/schluessel-z/honors/")
        assert resp.status_code == 200, resp.content
        data = resp.json()["dignities"]
        assert [d["name"] for d in data] == ["Zugkönig", "Hubertuskönig"]
        assert [r["holder"]["name"] for r in data[1]["reigns"]] == ["Hans Hubertus"]

    def test_menue_wuerdentraeger(self, orgs, site, buergerkoenig):
        org = orgs["a"]
        koenig = Dignity.objects.create(organization=org, name="König")
        for year in (2023, 2024):
            Reign.objects.create(organization=org, dignity=koenig, year=year, name=f"K {year}")
        site.include_parent_honors = True
        site.save()
        menu = info()["honors_menu"]
        assert menu["label"] == "Würdenträger"
        assert [d["label"] for d in menu["dignities"]] == ["Könige", "Bundeskönig"]
        assert menu["honorary"] is False
        title = HonoraryTitle.objects.create(organization=org, name="Ehrenmitglied", is_public=True)
        member = make_member(org, "Erika", "Ehre")
        HonoraryTitleAward.objects.create(
            organization=org, title=title, person=member.person, valid_from="2020-01-01"
        )
        menu = info()["honors_menu"]
        assert menu["honorary"] is True and menu["honorary_label"] == "Ehrenmitglied"
        # Ehrungen auch ohne Baustein „Vorstand“ abrufbar
        site.blocks = {**site.blocks, "board": False}
        site.save()
        board = Client().get("/api/public/site/v1/schluessel-x/board/").json()
        assert board["roles"] == [] and board["honorary"][0]["title"] == "Ehrenmitglied"
