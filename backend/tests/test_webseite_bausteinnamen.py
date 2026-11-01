"""Bausteine der Webseite umbenennen (Ralf 2026-11-01, alles erfunden): eigener Name im
Menü und als Überschrift, leer = Standardname."""

import pytest
from django.test import Client

from honors.models import Dignity, Reign
from website.models import Website

JSON = "application/json"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = [*org.enabled_modules, "website"]
    org.save()
    return Website.objects.create(
        organization=org,
        public_key="schluessel-n",
        state="public",
        privacy_text="Datenschutz (erfunden)",
        privacy_published_text="Datenschutz (erfunden)",
    )


def info():
    return Client().get("/api/public/site/v1/schluessel-n/").json()


def labels(entries):
    return [
        (e["label"], [c["label"] for c in e["children"]]) if e.get("children") else e["label"]
        for e in entries
    ]


def test_umbenennen_in_verwaltung_und_menue(api, orgs, board_a, site):
    org = orgs["a"]
    koenig = Dignity.objects.create(organization=org, name="König")
    prinz = Dignity.objects.create(organization=org, name="Prinz")
    Reign.objects.create(organization=org, dignity=koenig, year=2024, name="K (erfunden)")
    Reign.objects.create(organization=org, dignity=prinz, year=2024, name="P (erfunden)")
    c = api(board_a)
    url = f"/api/orgs/{org.pk}/website/"
    names = {"events": "  Unsere   Feste ", "honors": "Majestäten", "contact": "", "board": None}
    resp = c.put(url, {"block_names": names}, content_type=JSON)
    assert resp.status_code == 200, resp.content
    website = resp.json()["website"]
    # Leer = Standardname, Leerzeichen werden zusammengezogen
    assert website["block_names"] == {"events": "Unsere Feste", "honors": "Majestäten"}
    items = {i["key"]: i for i in website["menu_items"]}
    assert items["events"]["label"] == "Unsere Feste"
    assert items["events"]["default_label"] == "Termine"
    assert items["events"]["renamable"] is True
    assert items[f"dignity:{koenig.pk}"]["renamable"] is False
    data = info()
    assert labels(data["nav"]) == [
        "Unsere Feste",
        "Vorstand",
        ("Majestäten", ["König", "Prinz"]),
        "Kontakt",
    ]
    assert data["names"] == {"events": "Unsere Feste", "honors": "Majestäten"}
    assert data["honors_menu"]["label"] == "Majestäten"
    assert data["honors_label"] == "Majestäten"
    # Zurück auf den Standardnamen
    resp = c.put(url, {"block_names": {}}, content_type=JSON)
    assert resp.status_code == 200
    assert labels(info()["nav"])[0] == "Termine"
    assert info()["names"] == {}


def test_geschichte_und_einheiten(site, orgs):
    site.block_names = {"group:history": "Vereinsgeschichte", "units": "Unsere Züge"}
    site.save()
    from website import menu

    items = menu.items(site)
    assert items["group:history"]["label"] == "Vereinsgeschichte"
    assert items["units"]["label"] == "Unsere Züge"


def test_ungueltige_namen(api, orgs, board_a, site):
    c = api(board_a)
    url = f"/api/orgs/{orgs['a'].pk}/website/"
    for bad in ({"social": "Symbole"}, {"page:1": "x"}, {"events": 5}, ["x"]):
        assert c.put(url, {"block_names": bad}, content_type=JSON).status_code == 400, bad
    long = {"events": "x" * 61}
    assert c.put(url, {"block_names": long}, content_type=JSON).status_code == 400
    site.refresh_from_db()
    assert site.block_names == {}
