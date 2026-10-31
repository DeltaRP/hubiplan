"""Webseite: Datenschutzhinweise, Prüfliste vor „öffentlich“, öffentliches Impressum.

Alle Daten erfunden.
"""

import pytest

from organizations import imprint as imprint_service
from organizations.imprint_generator import unit_privacy
from website import privacy
from website.models import Website

from .test_webseite_verwaltung import enable, ready, url

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def site(orgs, board_a, api):
    enable(orgs["a"])
    assert api(board_a).post(url(orgs["a"])).status_code == 201
    return Website.objects.get(organization=orgs["a"])


def check(data, key):
    return next(c for c in data["website"]["checks"] if c["key"] == key)


class TestPruefliste:
    def test_neue_webseite_nicht_bereit(self, orgs, board_a, api, site):
        data = api(board_a).get(url(orgs["a"])).json()
        for key in ("imprint", "privacy", "domain"):
            assert check(data, key)["ok"] is False, key
            assert check(data, key)["blocking"] is True

    def test_oeffentlich_erst_wenn_bereit(self, orgs, board_a, api, site):
        c = api(board_a)
        resp = c.put(url(orgs["a"]), {"state": "public"}, "application/json")
        assert resp.status_code == 400
        assert "Datenschutzhinweise" in str(resp.json())
        site.refresh_from_db()
        assert site.state == "maintenance"
        ready(orgs["a"], site)
        resp = c.put(url(orgs["a"]), {"state": "public"}, "application/json")
        assert resp.status_code == 200, resp.content

    def test_geerbtes_impressum_reicht_nicht(self, orgs, site):
        imprint = imprint_service.ensure(orgs["a"])
        imprint.mode = "inherit"
        imprint.save()
        item = next(c for c in privacy.checks(site) if c["key"] == "imprint")
        assert item["ok"] is False and "eigenes Impressum" in item["hint"]

    def test_ev_braucht_registernummer(self, orgs, site):
        imprint = imprint_service.ensure(orgs["a"])
        imprint.mode = "own"
        imprint.name = "Testverein Beispielhausen e.V."
        imprint.street = "Erfundene Straße 1"
        imprint.postal_code = "41468"
        imprint.city = "Beispielstadt"
        imprint.representatives = "Erika Muster (Vorsitzende)"
        imprint.email = "info@beispiel.example"
        imprint.phone = "0000 123456"
        imprint.save()
        item = next(c for c in privacy.checks(site) if c["key"] == "imprint")
        assert item["ok"] is True  # nicht eingetragen: keine Registerangaben nötig
        imprint.registered = True
        imprint.save()
        item = next(c for c in privacy.checks(site) if c["key"] == "imprint")
        assert "Registergericht" in item["hint"] and "Registernummer" in item["hint"]
        imprint.register_court = "Amtsgericht Beispielstadt (erfunden)"
        imprint.register_number = "VR 0000"
        imprint.save()
        item = next(c for c in privacy.checks(site) if c["key"] == "imprint")
        assert item["ok"] is True

    def test_oeffentlich_ohne_datenschutz_nicht_moeglich(self, orgs, board_a, api, site):
        ready(orgs["a"], site)
        c = api(board_a)
        assert c.put(url(orgs["a"]), {"state": "public"}, "application/json").status_code == 200
        # Den Entwurf zu leeren ändert nichts Öffentliches (UI-Audit NAF-02)
        resp = c.put(url(orgs["a"]), {"privacy_text": ""}, "application/json")
        assert resp.status_code == 200
        assert check(resp.json(), "privacy")["ok"] is True
        # andere Änderungen gehen weiter, auch wenn z. B. die Domain fehlt
        site.domains.all().delete()
        resp = c.put(url(orgs["a"]), {"show_vacant": True}, "application/json")
        assert resp.status_code == 200


class TestErzeugen:
    def test_text_passt_zu_den_bausteinen(self, orgs, board_a, api, site):
        c = api(board_a)
        resp = c.post(url(orgs["a"], "privacy/generate/"))
        assert resp.status_code == 200, resp.content
        text = resp.json()["website"]["privacy_text"]
        assert "Kontaktformular" in text and "Würdenträger" in text
        assert "Art. 21" in text and "keine Cookies" in text
        # Markdown mit Zwischenüberschriften (Webseite und Editor zeigen sie als solche)
        assert "\n\n## 1. Verantwortlich\n\n" in text
        assert "\n\n## 2. Hosting\n\nDie Webseite" in text
        assert resp.json()["website"]["privacy_generated_at"]
        # Erzeugen schreibt nur den Entwurf; öffentlich erst nach „Veröffentlichen“
        assert check(resp.json(), "privacy")["ok"] is False
        resp = c.post(url(orgs["a"], "privacy/publish/"))
        assert resp.status_code == 200, resp.content
        assert check(resp.json(), "privacy")["ok"] is True
        assert resp.json()["website"]["privacy_published_text"] == text
        # Kontaktformular aus: Abschnitt fällt weg, alter Text gilt als veraltet
        c.put(url(orgs["a"]), {"blocks": {"contact": False}}, "application/json")
        site.refresh_from_db()
        assert privacy.is_outdated(site)
        data = c.get(url(orgs["a"])).json()
        assert check(data, "privacy_outdated")["blocking"] is False
        text = c.post(url(orgs["a"], "privacy/generate/")).json()["website"]["privacy_text"]
        assert "Kontaktformular" not in text
        site.refresh_from_db()
        assert not privacy.is_outdated(site)

    def test_aufsichtsbehoerde_nach_plz(self, orgs, site):
        imprint = imprint_service.ensure(orgs["a"])
        imprint.mode = "own"
        imprint.postal_code = "41468"
        imprint.save()
        assert "LDI NRW" in privacy.website_privacy(site)
        imprint.postal_code = "80331"
        imprint.save()
        assert "[zuständige Aufsichtsbehörde" in privacy.website_privacy(site)

    def test_nur_verwalter_erzeugt(self, orgs, api, site):
        from .factories import give_role, make_user

        user = make_user("schrift@example.org")
        give_role(user, orgs["a"], permissions=["website.content"], name="Schriftführer")
        assert api(user).post(url(orgs["a"], "privacy/generate/")).status_code == 403

    def test_link_statt_text(self, orgs, board_a, api, site):
        c = api(board_a)
        resp = c.put(
            url(orgs["a"]),
            {"privacy_mode": "link", "privacy_url": "https://beispiel.example/datenschutz"},
            "application/json",
        )
        assert resp.status_code == 200
        assert check(resp.json(), "privacy")["ok"] is True


class TestOeffentlich:
    def test_impressum_mit_webseiten_datenschutz(self, orgs, client, site):
        site.privacy_text = "Entwurf, noch nicht öffentlich"
        site.privacy_published_text = "Datenschutz der Webseite (erfunden)"
        site.state = "public"
        site.save()
        imprint = imprint_service.ensure(orgs["a"])
        imprint.privacy_text = "Datenschutz für Mitglieder (erfunden)"
        imprint.save()
        resp = client.get(f"/api/public/site/v1/{site.public_key}/imprint/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["privacy"]["text"] == "Datenschutz der Webseite (erfunden)"
        assert "Mitglieder" not in str(data["privacy"])

    def test_mitglieder_hinweise_nennen_webseite(self, orgs, site):
        assert "Veröffentlichung auf unserer Webseite" in unit_privacy(orgs["a"])
        site.delete()
        assert "Veröffentlichung auf unserer Webseite" not in unit_privacy(orgs["a"])
