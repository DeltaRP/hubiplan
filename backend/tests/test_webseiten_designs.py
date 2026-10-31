"""Webseiten-Designs zur Auswahl und Farbpalette je Einheit (Ralf 2026-10-31, erfunden)."""

import pytest
from django.test import Client

from organizations.models import Department
from organizations.theme import effective_theme
from website import designs
from website.models import Website, WebsiteDomain

pytestmark = pytest.mark.django_db(transaction=True)
JSON = "application/json"


class TestPalette:
    def test_ohne_weitere_farben_zwei_eintraege(self, orgs):
        palette = effective_theme(orgs["a"].ancestors())["palette"]
        assert len(palette) == 2
        assert {"color", "on_color", "name"} <= set(palette[0])

    def test_weitere_farben_speichern_und_pruefen(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/theme/"
        resp = c.patch(
            url,
            {
                "primary_color": "#1f4e2c",
                "primary_color_name": "Grün",
                "accent_color_name": "Gold",
                "extra_colors": [{"color": "#8B1E2D", "name": "Weinrot"}],
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.content
        palette = resp.json()["effective"]["palette"]
        assert [p["name"] for p in palette] == ["Grün", "Gold", "Weinrot"]
        assert palette[2] == {"color": "#8b1e2d", "on_color": "#ffffff", "name": "Weinrot"}

    def test_hoechstens_sechs_farben(self, api, orgs, board_a):
        url = f"/api/orgs/{orgs['a'].pk}/theme/"
        five = [{"color": "#1f4e2c", "name": ""}] * 5
        resp = api(board_a).patch(url, {"extra_colors": five}, content_type=JSON)
        assert resp.status_code == 400
        assert "sechs" in str(resp.json())

    def test_schlecht_lesbare_farbe_abgelehnt(self, api, orgs, board_a):
        url = f"/api/orgs/{orgs['a'].pk}/theme/"
        bad = [{"color": "#888888", "name": "Grau"}]
        resp = api(board_a).patch(url, {"extra_colors": bad}, content_type=JSON)
        assert resp.status_code == 400
        resp = api(board_a).patch(url, {"extra_colors": [{"color": "rot"}]}, content_type=JSON)
        assert resp.status_code == 400

    def test_palette_erbt_als_ganzes(self, orgs):
        club = orgs["a"]
        club.primary_color = "#1f4e2c"
        club.extra_colors = [{"color": "#8b1e2d", "name": "Weinrot"}]
        club.save()
        unit = Department.objects.create(organization=club, parent=club, name="Jägerzug")
        assert len(effective_theme(unit.ancestors())["palette"]) == 3
        # Eigene Hauptfarbe: eigene Palette, ohne die weiteren Farben des Vereins
        unit.primary_color = "#123e7a"
        unit.save()
        palette = effective_theme(unit.ancestors())["palette"]
        assert len(palette) == 2 and palette[0]["color"] == "#123e7a"


class TestDesigns:
    PALETTE = [
        {"color": "#1f4e2c", "on_color": "#ffffff", "name": ""},
        {"color": "#c9a227", "on_color": "#1d2421", "name": ""},
    ]

    def test_fuenf_designs_klassisch_vorgabe(self):
        assert list(designs.DESIGNS) == ["classic", "festive", "sidebar", "stage", "newspaper"]
        assert Website._meta.get_field("design").default == "classic"

    def test_fehlende_dritte_farbe_faellt_zurueck(self):
        colors = designs.resolve("festive", self.PALETTE)
        assert colors["date"]["color"] == "#1f4e2c"
        three = [*self.PALETTE, {"color": "#8b1e2d", "on_color": "#ffffff", "name": ""}]
        assert designs.resolve("festive", three)["date"]["color"] == "#8b1e2d"

    def test_eigene_zuordnung(self):
        roles = {"classic": {"footer": 1, "header": "light", "unbekannt": 0}, "gibtsnicht": {}}
        assert designs.normalize_color_roles(roles) == {"classic": {"footer": 1, "header": "light"}}
        colors = designs.resolve("classic", self.PALETTE, roles)
        assert colors["footer"] == {"color": "#c9a227", "on_color": "#1d2421"}
        assert colors["header"]["color"] == "#ffffff"
        # Platz ohne Farbe: Vorgabe des Designs
        colors = designs.resolve("classic", self.PALETTE, {"classic": {"footer": 4}})
        assert colors["footer"]["color"] == "#1d2421"

    def test_unbekanntes_design_wie_klassisch(self):
        assert designs.resolve("gibtsnicht", self.PALETTE) == designs.resolve(
            "classic", self.PALETTE
        )


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = [*org.enabled_modules, "website"]
    org.save()
    site = Website.objects.create(
        organization=org,
        public_key="schluessel-d",
        state="public",
        privacy_text="Datenschutz (erfunden)",
        privacy_published_text="Datenschutz (erfunden)",
    )
    WebsiteDomain.objects.create(organization=org, website=site, hostname="www.design.example")
    return site


class TestEinstellungen:
    def test_auswahl_und_zuordnung(self, api, orgs, board_a, site):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/website/"
        data = c.get(url).json()
        assert [d["key"] for d in data["designs"]] == list(designs.DESIGNS)
        assert data["website"]["design"] == "classic"
        assert set(data["website"]["design_colors"]) == set(designs.DESIGNS)
        assert len(data["palette"]) == 2
        resp = c.put(
            url,
            {"design": "stage", "color_roles": {"stage": {"band2": 1, "falsch": 3}}},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.content
        site.refresh_from_db()
        assert site.design == "stage"
        assert site.color_roles == {"stage": {"band2": 1}}
        assert c.put(url, {"design": "bunt"}, content_type=JSON).status_code == 400
        assert c.put(url, {"color_roles": [1]}, content_type=JSON).status_code == 400

    def test_schnittstelle_liefert_design(self, site):
        site.design = "newspaper"
        site.save()
        data = Client().get("/api/public/site/v1/schluessel-d/").json()
        assert data["design"] == "newspaper"
        assert set(data["designs"]) == set(designs.DESIGNS)
        assert data["designs"]["newspaper"]["footer"]["color"] == "#1d2421"
        # Altes Feld bleibt für ältere Stände der Webseite
        assert set(data["theme"]) == {"primary", "on_primary", "accent", "on_accent"}
