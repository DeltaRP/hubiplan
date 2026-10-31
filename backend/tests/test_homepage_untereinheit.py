"""Untereinheiten können eine eigene Homepage hinterlegen und auf ihrer Seite der
Vereinswebseite verlinken lassen."""

import pytest
from django.test import Client

from organizations.models import Department
from website.models import Website

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def unit(orgs):
    org = orgs["a"]
    org.enabled_modules = [*(org.enabled_modules or []), "website"]
    org.save()
    Website.objects.create(organization=org, public_key="schluessel-a", state="public")
    return Department.objects.create(organization=org, parent=org, name="Jägerzug")


def test_homepage_pflegen(api, orgs, board_a, unit):
    c = api(board_a)
    url = f"/api/orgs/{orgs['a'].pk}/departments/{unit.pk}/"
    assert c.get(url).json()["website"] == ""
    assert c.get(url).json()["website_on_site"] is False

    # Ohne „https://“ eingegeben wird es ergänzt
    resp = c.patch(url, {"website": " www.jaegerzug.example "}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["website"] == "https://www.jaegerzug.example"
    resp = c.patch(url, {"website": "http://alt.example/zug"}, content_type=JSON)
    assert resp.json()["website"] == "http://alt.example/zug"

    # Andere Schemata und Unsinn werden abgelehnt
    for bad in ("javascript:alert(1)", "kein link", "ftp://x.example"):
        resp = c.patch(url, {"website": bad}, content_type=JSON)
        assert resp.status_code == 400, bad
        assert "website" in resp.json()

    resp = c.patch(url, {"website_on_site": True}, content_type=JSON)
    assert resp.json()["website_on_site"] is True
    unit.refresh_from_db()
    assert unit.website == "http://alt.example/zug"
    assert unit.website_on_site is True

    # Leeren geht
    resp = c.patch(url, {"website": ""}, content_type=JSON)
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.website == ""


def test_webseite_zeigt_homepage_nur_mit_schalter(unit):
    detail = "/api/public/site/v1/schluessel-a/units/jaegerzug/"
    assert Client().get(detail).json()["homepage"] is None

    unit.website = "https://www.jaegerzug.example"
    unit.save()
    assert Client().get(detail).json()["homepage"] is None

    unit.website_on_site = True
    unit.save()
    assert Client().get(detail).json()["homepage"] == "https://www.jaegerzug.example"

    # Schalter an, aber keine Adresse: nichts
    unit.website = ""
    unit.save()
    assert Client().get(detail).json()["homepage"] is None
