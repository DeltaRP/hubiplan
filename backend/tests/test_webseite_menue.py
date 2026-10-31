"""Menü der Webseite per Ziehen ordnen, mit Unterpunkten (Ralf 2026-10-31, alles erfunden)."""

import pytest
from django.test import Client
from django.utils import timezone

from honors.models import Dignity, Reign
from members.models import HonoraryTitle, HonoraryTitleAward
from website import menu
from website.content_models import WebsiteText
from website.models import Website

from .factories import make_member

JSON = "application/json"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = [*org.enabled_modules, "website"]
    org.save()
    return Website.objects.create(
        organization=org,
        public_key="schluessel-m",
        state="public",
        privacy_text="Datenschutz (erfunden)",
        privacy_published_text="Datenschutz (erfunden)",
    )


def nav():
    return Client().get("/api/public/site/v1/schluessel-m/").json()["nav"]


def labels(entries):
    return [
        (e["label"], [c["label"] for c in e["children"]]) if e.get("children") else e["label"]
        for e in entries
    ]


def page(site, slug, title, **kw):
    return WebsiteText.objects.create(
        organization=site.organization,
        website=site,
        kind=WebsiteText.Kind.PAGE,
        slug=slug,
        title=title,
        published_title=title,
        published_body="Text (erfunden)",
        published_at=timezone.now(),
        **kw,
    )


class TestNormalize:
    known = {
        "a": {"heading": False, "parent": None},
        "g": {"heading": True, "parent": None},
        "b": {"heading": False, "parent": "g"},
        "c": {"heading": False, "parent": None},
    }

    def test_standard(self):
        assert menu.normalize([], self.known) == [
            {"key": "a", "children": []},
            {"key": "g", "children": [{"key": "b", "children": []}]},
            {"key": "c", "children": []},
        ]

    def test_unbekanntes_doppeltes_und_fehlendes(self):
        stored = [
            {"key": "c", "children": [{"key": "a"}, {"key": "x"}, {"key": "g"}]},
            {"key": "a"},
            {"key": "zz"},
        ]
        # „g“ ist eine Überschrift: nie Unterpunkt, kommt an ihren Standardplatz;
        # „b“ fehlt und kommt unter seinen Standard-Oberpunkt
        assert menu.normalize(stored, self.known) == [
            {"key": "g", "children": [{"key": "b", "children": []}]},
            {"key": "c", "children": [{"key": "a", "children": []}]},
        ]

    def test_drei_ebenen_abgelehnt(self):
        with pytest.raises(ValueError):
            menu.validate(
                [{"key": "a", "children": [{"key": "c", "children": [{"key": "b"}]}]}], self.known
            )


class TestVerwaltung:
    def test_menue_speichern(self, api, orgs, board_a, site):
        p = page(site, "festschrift", "Festschrift")
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/website/"
        data = c.get(url).json()
        keys = [i["key"] for i in data["website"]["menu_items"]]
        assert keys[:4] == ["posts", "events", "board", "units"]
        assert f"page:{p.pk}" in keys and "social" not in keys
        assert [n["key"] for n in data["website"]["menu"]][:3] == ["posts", "events", "board"]
        # Kontakt nach vorn, Vorstand und Textseite unter Termine
        new = [
            {"key": "contact"},
            {"key": "posts"},
            {"key": "events", "children": [{"key": "board"}, {"key": f"page:{p.pk}"}]},
        ]
        resp = c.put(url, {"menu": new}, content_type=JSON)
        assert resp.status_code == 200, resp.content
        tree = resp.json()["website"]["menu"]
        assert tree[0] == {"key": "contact", "children": []}
        assert tree[2]["children"] == [
            {"key": "board", "children": []},
            {"key": f"page:{p.pk}", "children": []},
        ]
        bad = [{"key": "events", "children": [{"key": "board", "children": [{"key": "contact"}]}]}]
        assert c.put(url, {"menu": bad}, content_type=JSON).status_code == 400
        assert c.put(url, {"menu": "x"}, content_type=JSON).status_code == 400


class TestSchnittstelle:
    def test_standardmenue(self, site):
        page(site, "festschrift", "Festschrift")
        entries = nav()
        # „Würdenträger“ ohne Würden und Ehrungen entfällt
        assert labels(entries) == ["Termine", "Vorstand", "Festschrift", "Kontakt"]
        assert entries[2] == {"key": "page", "label": "Festschrift", "slug": "festschrift"}

    def test_eigene_anordnung(self, site):
        p = page(site, "festschrift", "Festschrift")
        site.menu = [
            {"key": "contact"},
            {"key": "posts"},
            {"key": "events", "children": [{"key": "board"}, {"key": f"page:{p.pk}"}]},
        ]
        site.save()
        assert labels(nav()) == [
            "Kontakt",
            ("Termine", ["Vorstand", "Festschrift"]),
        ]
        # Ausgeschalteter Oberpunkt: Unterpunkte rücken nach oben
        site.blocks = {**site.blocks, "events": False}
        site.save()
        assert labels(nav()) == ["Kontakt", "Vorstand", "Festschrift"]

    def test_wuerdentraeger_unterpunkte_verschieben(self, orgs, site):
        org = orgs["a"]
        koenig = Dignity.objects.create(organization=org, name="König")
        prinz = Dignity.objects.create(organization=org, name="Prinz")
        Reign.objects.create(organization=org, dignity=koenig, year=2024, name="K (erfunden)")
        Reign.objects.create(organization=org, dignity=prinz, year=2024, name="P (erfunden)")
        entries = nav()
        assert labels(entries)[2] == ("Würdenträger", ["König", "Prinz"])
        assert entries[2]["heading"] is True
        assert entries[2]["children"][0]["id"]
        # Prinz als eigener Hauptpunkt: nur noch König unter „Würdenträger“ → direkt im Menü
        tree = menu.normalize([], menu.items(site))
        honors = next(n for n in tree if n["key"] == "honors")
        honors["children"] = [c for c in honors["children"] if c["key"] != f"dignity:{prinz.pk}"]
        tree.append({"key": f"dignity:{prinz.pk}", "children": []})
        site.menu = tree
        site.save()
        assert labels(nav()) == ["Termine", "Vorstand", "König", "Kontakt", "Prinz"]

    def test_wuerden_und_ehrungen_einzeln_ausschalten(self, api, orgs, board_a, site):
        """Ralf 2026-10-31: jeder Unterpunkt von „Würdenträger“ hat ein eigenes Häkchen."""
        org = orgs["a"]
        koenig = Dignity.objects.create(organization=org, name="König")
        prinz = Dignity.objects.create(organization=org, name="Prinz")
        Reign.objects.create(organization=org, dignity=koenig, year=2024, name="K (erfunden)")
        Reign.objects.create(organization=org, dignity=prinz, year=2024, name="P (erfunden)")
        title = HonoraryTitle.objects.create(organization=org, name="Ehrenmitglied", is_public=True)
        member = make_member(org, "Erika", "Ehre")
        HonoraryTitleAward.objects.create(
            organization=org, title=title, person=member.person, valid_from="2020-01-01"
        )
        c = api(board_a)
        url = f"/api/orgs/{org.pk}/website/"
        items = {i["key"]: i for i in c.get(url).json()["website"]["menu_items"]}
        assert items[f"dignity:{koenig.pk}"]["toggle"] == f"dignity:{koenig.pk}"
        assert items["honorary"]["toggle"] == "honorary"
        assert labels(nav())[2] == ("Würdenträger", ["König", "Prinz", "Ehrenmitglied"])
        # Prinz und Ehrungen aus; fremde Schlüssel werden nicht gespeichert
        blocks = {
            **site.blocks,
            f"dignity:{prinz.pk}": False,
            "honorary": False,
            "dignity:999999": False,
        }
        resp = c.put(url, {"blocks": blocks}, content_type=JSON)
        assert resp.status_code == 200, resp.content
        site.refresh_from_db()
        assert site.blocks[f"dignity:{prinz.pk}"] is False and "dignity:999999" not in site.blocks
        assert labels(nav())[2] == "König"
        public = Client().get("/api/public/site/v1/schluessel-m/")
        assert public.json()["honors_menu"]["honorary"] is False
        honors = Client().get("/api/public/site/v1/schluessel-m/honors/").json()["dignities"]
        assert [d["name"] for d in honors] == ["König"]
        board = Client().get("/api/public/site/v1/schluessel-m/board/").json()
        assert board["honorary"] == []
        # Wieder an
        c.put(url, {"blocks": {**site.blocks, "honorary": True}}, content_type=JSON)
        assert labels(nav())[2] == ("Würdenträger", ["König", "Ehrenmitglied"])

    def test_geschichte_als_ueberschrift(self, site):
        # Nur die Chronik (Textseite „geschichte“) hat Inhalt: sie steht direkt im Menü
        page(site, "geschichte", "Chronik")
        entries = nav()
        assert "Chronik" in labels(entries)
        assert not any(e.get("heading") for e in entries)
        # Chronik unter Kontakt gezogen: Kontakt wird Aufklappmenü
        tree = menu.normalize([], menu.items(site))
        group = next(n for n in tree if n["key"] == "group:history")
        group["children"] = []
        next(n for n in tree if n["key"] == "contact")["children"] = [{"key": "history"}]
        site.menu = tree
        site.save()
        assert labels(nav())[-1] == ("Kontakt", ["Chronik"])
