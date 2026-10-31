"""Webseite: Einrichtung, Zustand, Domains, Vorschau, Einwilligungen (alles erfunden)."""

import pytest
from django.utils import timezone

from access.catalog import DEFAULT_MODULES, SWITCHABLE_MODULES
from audit.models import AuditEntry
from organizations.models import Department
from website import services
from website.models import PreviewLink, PublicationConsent, Website

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db(transaction=True)


def enable(org):
    org.enabled_modules = [*org.enabled_modules, "website"]
    org.save(update_fields=["enabled_modules"])


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/website/{rest}"


def ready(org, site):
    """Prüfliste erfüllen: eigenes Impressum (Link), Datenschutzhinweise, Domain."""
    from organizations import imprint as imprint_service

    imprint = imprint_service.ensure(org)
    imprint.mode = "link"
    imprint.external_url = "https://beispiel.example/impressum"
    imprint.save()
    site.privacy_text = "Datenschutzhinweise (erfunden)"
    site.privacy_published_text = site.privacy_text
    site.save()
    site.domains.create(organization=org, hostname=f"www.verein-{org.pk}.example", is_primary=True)


@pytest.fixture
def site(orgs, board_a, api):
    enable(orgs["a"])
    resp = api(board_a).post(url(orgs["a"]))
    assert resp.status_code == 201, resp.content
    return Website.objects.get(organization=orgs["a"])


class TestModul:
    def test_webseite_nicht_standardmaessig_frei(self):
        assert "website" in SWITCHABLE_MODULES
        assert "website" not in DEFAULT_MODULES

    def test_ohne_modul_keine_einrichtung(self, orgs, board_a, api):
        c = api(board_a)
        data = c.get(url(orgs["a"])).json()
        assert data["module_enabled"] is False and data["website"] is None
        assert c.post(url(orgs["a"])).status_code == 404
        assert not Website.objects.exists()

    def test_einrichten_startet_in_wartung(self, orgs, board_a, api, site):
        data = api(board_a).get(url(orgs["a"])).json()
        assert data["website"]["state"] == "maintenance"
        assert data["website"]["effective_state"] == "maintenance"
        assert data["website"]["blocks"]["events"] is True
        assert AuditEntry.objects.filter(organization=orgs["a"], object_type="Webseite").exists()
        # zweites Mal geht nicht
        assert api(board_a).post(url(orgs["a"])).status_code == 400

    def test_untereinheit_hat_keine_webseite(self, orgs, board_a, api):
        unit = Department.objects.create(organization=orgs["a"], parent=orgs["a"], name="Zug 1")
        user = make_user("zug@example.org")
        give_role(user, unit, permissions=["roles.manage"])
        assert api(user).get(url(unit)).status_code == 404

    def test_ohne_recht_nicht_sichtbar(self, orgs, api, site):
        user = make_user("kassierer@example.org")
        give_role(user, orgs["a"], permissions=["finance.view"], name="Kasse")
        assert api(user).get(url(orgs["a"])).status_code == 404

    def test_redakteur_liest_aber_aendert_nichts(self, orgs, api, site):
        user = make_user("schrift@example.org")
        give_role(user, orgs["a"], permissions=["website.content"], name="Schriftführer")
        c = api(user)
        data = c.get(url(orgs["a"])).json()
        assert data["can_manage"] is False and data["can_edit_content"] is True
        assert c.put(url(orgs["a"]), {"state": "public"}, "application/json").status_code == 403
        # Vorschau öffnen darf er
        assert c.post(url(orgs["a"], "preview/")).status_code == 200

    def test_fremder_verein_sieht_nichts(self, orgs, board_b, api, site):
        assert api(board_b).get(url(orgs["a"])).status_code == 404


class TestEinstellungen:
    def test_zustand_und_bausteine(self, orgs, board_a, api, site):
        c = api(board_a)
        ready(orgs["a"], site)
        unit = Department.objects.create(organization=orgs["a"], parent=orgs["a"], name="Zug 1")
        resp = c.put(
            url(orgs["a"]),
            {
                "state": "public",
                "blocks": {"contact": False},
                "units_mode": "selected",
                "unit_ids": [unit.pk],
                "name_format": "initial",
            },
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        site.refresh_from_db()
        assert site.state == "public" and site.unit_ids == [unit.pk]
        assert site.block_on("contact") is False and site.block_on("board") is True
        entry = AuditEntry.objects.filter(organization=orgs["a"], action="update").latest("pk")
        assert "state" in str(entry.changes) or "Zustand" in str(entry.changes)

    def test_fremde_untereinheit_abgelehnt(self, orgs, board_a, api, site):
        other = Department.objects.create(organization=orgs["b"], parent=orgs["b"], name="Zug B")
        resp = api(board_a).put(url(orgs["a"]), {"unit_ids": [other.pk]}, "application/json")
        assert resp.status_code == 400

    def test_unbekannter_baustein_wird_ignoriert(self, orgs, board_a, api, site):
        resp = api(board_a).put(url(orgs["a"]), {"blocks": {"galerie": True}}, "application/json")
        assert resp.status_code == 200
        site.refresh_from_db()
        assert "galerie" not in site.blocks

    def test_startseite_reihenfolge(self, orgs, board_a, api, site):
        data = api(board_a).get(url(orgs["a"])).json()
        keys = [s["key"] for s in data["website"]["home_sections"]]
        assert keys[:5] == ["carousel", "greeting", "events", "honors", "units"]
        assert data["home_labels"]["greeting"] == "Willkommenstext"
        resp = api(board_a).put(
            url(orgs["a"]),
            {
                "home_sections": [
                    {"key": "events", "on": True},
                    {"key": "greeting", "on": True},
                    {"key": "carousel", "on": False},
                    {"key": "events", "on": False},
                ]
            },
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        site.refresh_from_db()
        # Doppelte fallen weg, fehlende kommen in Standardreihenfolge hinten dazu
        assert site.home() == ["events", "greeting", "honors", "units"]
        keys = [s["key"] for s in resp.json()["website"]["home_sections"]]
        assert keys[:4] == ["events", "greeting", "carousel", "honors"]

    def test_startseite_unbekannter_baustein(self, orgs, board_a, api, site):
        resp = api(board_a).put(
            url(orgs["a"]), {"home_sections": [{"key": "galerie", "on": True}]}, "application/json"
        )
        assert resp.status_code == 400
        resp = api(board_a).put(url(orgs["a"]), {"home_sections": "events"}, "application/json")
        assert resp.status_code == 400

    def test_testserver_nur_vorschau(self, orgs, board_a, api, site, settings):
        settings.WEBSITE_PREVIEW_ONLY = True
        ready(orgs["a"], site)
        api(board_a).put(url(orgs["a"]), {"state": "public"}, "application/json")
        data = api(board_a).get(url(orgs["a"])).json()
        assert data["website"]["state"] == "public"
        assert data["website"]["effective_state"] == "maintenance"
        assert data["preview_only"] is True

    def test_modul_aus_heisst_webseite_aus(self, orgs, site):
        site.state = "public"
        site.save()
        orgs["a"].enabled_modules = ["members"]
        orgs["a"].save()
        site.refresh_from_db()
        assert services.effective_state(site) == "off"

    def test_entfernen(self, orgs, board_a, api, site):
        assert api(board_a).delete(url(orgs["a"])).status_code == 200
        assert not Website.objects.exists()


class TestDomains:
    def test_domain_anlegen_und_hauptadresse(self, orgs, board_a, api, site):
        c = api(board_a)
        resp = c.post(url(orgs["a"], "domains/"), {"hostname": "https://WWW.Beispiel-Verein.de/"})
        assert resp.status_code == 201, resp.content
        assert resp.json() == {
            "id": resp.json()["id"],
            "hostname": "www.beispiel-verein.de",
            "is_primary": True,
        }
        second = c.post(url(orgs["a"], "domains/"), {"hostname": "beispiel-verein.de"}).json()
        assert second["is_primary"] is False
        assert c.put(url(orgs["a"], f"domains/{second['id']}/")).json()["is_primary"] is True
        data = c.get(url(orgs["a"])).json()["website"]
        assert data["url"] == "https://beispiel-verein.de/"
        assert c.delete(url(orgs["a"], f"domains/{second['id']}/")).status_code == 204
        assert c.get(url(orgs["a"])).json()["website"]["domains"][0]["is_primary"] is True

    def test_domain_nur_einmal_und_gueltig(self, orgs, board_a, board_b, api, site):
        c = api(board_a)
        assert c.post(url(orgs["a"], "domains/"), {"hostname": "a.example.org"}).status_code == 201
        assert c.post(url(orgs["a"], "domains/"), {"hostname": "a.example.org"}).status_code == 400
        assert c.post(url(orgs["a"], "domains/"), {"hostname": "kein host"}).status_code == 400
        # auch ein anderer Verein bekommt sie nicht
        enable(orgs["b"])
        api(board_b).post(url(orgs["b"]))
        resp = api(board_b).post(url(orgs["b"], "domains/"), {"hostname": "a.example.org"})
        assert resp.status_code == 400


class TestVorschau:
    def test_knopf_schluessel_eintauschen(self, orgs, board_a, api, site):
        token = api(board_a).post(url(orgs["a"], "preview/")).json()["token"]
        session, until = services.exchange(site, token)
        assert services.valid_session(site, session)
        assert until > timezone.now()
        # Schlüssel gilt nur für diese Webseite
        other = Website.objects.create(organization=orgs["b"], public_key=Website.new_key())
        assert services.exchange(other, token) is None
        assert not services.valid_session(other, session)
        assert not services.valid_session(site, "gefaelscht")

    def test_link_befristet_und_widerrufbar(self, orgs, board_a, api, site):
        c = api(board_a)
        api(board_a).post(url(orgs["a"], "domains/"), {"hostname": "www.example.org"})
        resp = c.post(url(orgs["a"], "preview-links/"), {"label": "Vorstand", "days": 3})
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"].startswith("https://www.example.org/vorschau?schluessel=")
        link = PreviewLink.objects.get(pk=data["id"])
        assert link.token_hash != data["token"]
        assert services.exchange(site, data["token"]) is not None
        # zu lang geht nicht
        assert c.post(url(orgs["a"], "preview-links/"), {"days": 30}).status_code == 400
        assert c.delete(url(orgs["a"], f"preview-links/{link.pk}/")).status_code == 204
        assert services.exchange(site, data["token"]) is None
        assert c.get(url(orgs["a"])).json()["website"]["preview_links"] == []

    def test_abgelaufener_link(self, orgs, site):
        link, token = PreviewLink.create(site, 1, "", None)
        link.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        link.save()
        assert services.exchange(site, token) is None


class TestEinwilligungen:
    def test_grundregeln(self):
        assert services.allowed("name", set()) is True
        assert services.allowed("name", {"name"}) is False
        assert services.allowed("photo", set()) is False
        assert services.allowed("photo", {"photo"}) is True

    def test_setzen_widerrufen_verlauf(self, orgs, board_a, api):
        m = make_member(orgs["a"], "Erika", "Beispiel")
        c = api(board_a)
        path = f"/api/orgs/{orgs['a'].pk}/members/{m.pk}/publication/"
        cats = {x["category"]: x for x in c.get(path).json()["categories"]}
        assert cats["name"]["published"] is True and cats["name"]["kind"] == "objection"
        assert cats["photo"]["published"] is False
        resp = c.put(
            path, {"category": "photo", "active": True, "source": "paper"}, "application/json"
        )
        assert resp.status_code == 200
        cats = {x["category"]: x for x in resp.json()["categories"]}
        assert cats["photo"]["published"] is True and cats["photo"]["source"] == "paper"
        c.put(path, {"category": "photo", "active": False}, "application/json")
        c.put(path, {"category": "name", "active": True}, "application/json")
        cats = {x["category"]: x for x in c.get(path).json()["categories"]}
        assert cats["photo"]["published"] is False
        assert len(cats["photo"]["history"]) == 1 and cats["photo"]["history"][0]["ended_at"]
        assert cats["name"]["published"] is False
        assert PublicationConsent.objects.filter(membership=m).count() == 2
        assert AuditEntry.objects.filter(organization=orgs["a"], person_id=m.person_id).exists()

    def test_kein_datum_in_der_zukunft(self, orgs, board_a, api):
        m = make_member(orgs["a"], "Erika", "Beispiel")
        path = f"/api/orgs/{orgs['a'].pk}/members/{m.pk}/publication/"
        resp = api(board_a).put(
            path, {"category": "email", "active": True, "on": "2999-01-01"}, "application/json"
        )
        assert resp.status_code == 400

    def test_nur_mit_mitglieder_bearbeiten(self, orgs, api):
        m = make_member(orgs["a"], "Erika", "Beispiel")
        user = make_user("leser@example.org")
        give_role(user, orgs["a"], permissions=["members.view"], name="Leser")
        path = f"/api/orgs/{orgs['a'].pk}/members/{m.pk}/publication/"
        assert api(user).get(path).status_code == 200
        assert (
            api(user)
            .put(path, {"category": "email", "active": True}, "application/json")
            .status_code
            == 403
        )

    def test_fremdes_mitglied(self, orgs, board_b, api):
        m = make_member(orgs["a"], "Erika", "Beispiel")
        path = f"/api/orgs/{orgs['b'].pk}/members/{m.pk}/publication/"
        assert api(board_b).get(path).status_code == 404


def test_feste_adresse_auf_dem_testserver(orgs, board_a, api, site, settings):
    settings.WEBSITE_PUBLIC_URL = "https://test.example/webseite"
    data = api(board_a).get(url(orgs["a"])).json()
    assert data["website"]["url"] == "https://test.example/webseite/"
