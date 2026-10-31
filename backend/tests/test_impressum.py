"""Impressum und Datenschutzhinweise: Pflege, Vererbung, öffentliche Abrufe, Mails."""

import datetime

import pytest
from django.core import mail as djmail
from django.test import Client

from access.catalog import MEMBERS_VIEW
from access.models import Role, RoleAssignment
from core.tenancy import rls_bypass, tenant_context
from organizations.imprint import ensure, missing, owner_of
from organizations.models import Department, Imprint, Organization
from outbox.mail import send

from .factories import give_role, make_user
from .test_datatransfer import _eager, _on_commit_now, as_doc, export, upload  # noqa: F401

JSON = "application/json"


@pytest.fixture
def platform_admin(db):
    user = make_user("plattform@example.org")
    give_role(user, Organization.platform())
    return user


@pytest.fixture
def zug(orgs):
    with tenant_context(orgs["a"].pk):
        return Department.objects.create(
            organization=orgs["a"], name="Jägerzug", founding_year=1950
        )


def public(path: str):
    return Client().get(path)


class TestVererbung:
    def test_standard(self, orgs, zug):
        assert ensure(orgs["a"]).mode == Imprint.Mode.OWN
        assert ensure(zug).mode == Imprint.Mode.INHERIT
        assert ensure(Organization.platform()).mode == Imprint.Mode.OWN
        owner, _ = owner_of(zug)
        assert owner == orgs["a"]

    def test_verein_uebernimmt_vom_dachverband(self, orgs):
        imprint = ensure(orgs["a"])
        imprint.mode = Imprint.Mode.INHERIT
        imprint.save()
        owner, _ = owner_of(orgs["a"])
        assert owner == orgs["federation"]

    def test_ohne_eigenes_bis_zur_plattform(self, orgs):
        for key in ("federation", "a"):
            imprint = ensure(orgs[key])
            imprint.mode = Imprint.Mode.INHERIT
            imprint.save()
        owner, _ = owner_of(orgs["a"])
        assert owner.type == Organization.Type.PLATFORM

    def test_schluessel_bleibt(self, orgs):
        key = ensure(orgs["a"]).public_key
        assert ensure(orgs["a"]).public_key == key
        assert len(key) >= 8


class TestPflege:
    def test_vorstand_pflegt_und_sieht_fehlende_angaben(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/imprint/"
        data = c.get(url).json()
        # Anschrift kommt aus den Stammdaten, Vertretung und Kontakt fehlen noch
        assert data["preview"]["address"]["street"] == "Hauptstraße 1"
        assert "Anschrift" not in data["missing"]
        assert "Vertretungsberechtigte" in data["missing"]
        assert "E-Mail" in data["missing"]
        assert "Datenschutzhinweise" in data["missing"]
        assert "Datenschutzhinweise für Mitglieder von Verein A" in data["template"]

        resp = c.patch(
            url,
            {
                "legal_form": "eingetragener Verein",
                "register_court": "Amtsgericht Musterstadt",
                "register_number": "VR 1234",
                "email": "info@verein-a.example",
                "phone": "0123 456",
                "privacy_text": "Wir schützen Ihre Daten.",
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        # Der Text ist erst ein Entwurf (UI-Audit NAF-02)
        assert resp.json()["missing"] == ["Vertretungsberechtigte", "Datenschutzhinweise"]
        resp = c.post(url, {"action": "publish_privacy"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["missing"] == ["Vertretungsberechtigte"]
        assert resp.json()["imprint"]["privacy_published_at"]

    def test_vertretung_aus_rollen(self, api, orgs, board_a):
        vera = make_user("vera@example.org", first_name="Vera", last_name="Vorsitz")
        give_role(vera, orgs["a"], permissions=[], name="1. Vorsitzende")
        role = Role.objects.get(organization=orgs["a"], name="1. Vorsitzende")
        role.represents = True
        role.save()
        data = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/imprint/").json()
        assert data["preview"]["representatives"] == [
            {"name": "Vera Vorsitz", "role": "1. Vorsitzende"}
        ]
        assert "Vertretungsberechtigte" not in data["missing"]

        # Beendete Rollen erscheinen nicht mehr
        with rls_bypass():
            RoleAssignment.objects.filter(role=role).update(valid_until=datetime.date(2021, 1, 1))
        data = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/imprint/").json()
        assert data["preview"]["representatives"] == []

    def test_rollen_kennzeichen_ueber_api(self, api, orgs, board_a):
        role = Role.objects.get(organization=orgs["a"], name="Vorstand")
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/roles/{role.pk}/",
            {"represents": True},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["represents"] is True

    def test_link_braucht_adresse(self, api, orgs, board_a):
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/imprint/", {"mode": "link"}, content_type=JSON
        )
        assert resp.status_code == 400
        assert "external_url" in resp.json()

    def test_ohne_recht_nur_lesen(self, api, orgs):
        user = make_user("leser@example.org")
        give_role(user, orgs["a"], permissions=[MEMBERS_VIEW], name="Beisitz")
        c = api(user)
        assert c.get(f"/api/orgs/{orgs['a'].pk}/imprint/").status_code == 200
        resp = c.patch(f"/api/orgs/{orgs['a'].pk}/imprint/", {"phone": "1"}, content_type=JSON)
        assert resp.status_code == 403

    def test_fremder_verein_nicht_sichtbar(self, api, orgs, board_a):
        assert api(board_a).get(f"/api/orgs/{orgs['b'].pk}/imprint/").status_code == 404

    def test_untereinheit(self, api, orgs, board_a, zug):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/imprint/units/{zug.pk}/"
        data = c.get(url).json()
        assert data["imprint"]["mode"] == "inherit"
        assert data["owner"]["is_self"] is False
        resp = c.patch(url, {"mode": "own", "name": "Jägerzug GbR"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["owner"]["is_self"] is True
        assert resp.json()["preview"]["name"] == "Jägerzug GbR"

    def test_untereinheit_eines_anderen_vereins(self, api, orgs, board_a):
        with tenant_context(orgs["b"].pk):
            fremd = Department.objects.create(organization=orgs["b"], name="X", founding_year=1990)
        resp = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/imprint/units/{fremd.pk}/")
        assert resp.status_code == 404

    def test_plattform(self, api, platform_admin, board_a):
        c = api(platform_admin)
        resp = c.patch(
            "/api/platform/imprint/",
            {"name": "Max Betreiber", "street": "Weg 2", "postal_code": "11111", "city": "Ort"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["preview"]["name"] == "Max Betreiber"
        resp = c.patch("/api/platform/imprint/", {"mode": "inherit"}, content_type=JSON)
        assert resp.status_code == 400
        assert api(board_a).get("/api/platform/imprint/").status_code == 403


class TestOeffentlich:
    def test_plattform_ohne_anmeldung(self, db):
        imprint = ensure(Organization.platform())
        imprint.name = "Max Betreiber"
        imprint.privacy_text = "Datenschutz der Plattform"
        imprint.privacy_published_text = imprint.privacy_text
        imprint.save()
        resp = public("/api/public/imprint/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_platform"] is True
        assert data["details"]["name"] == "Max Betreiber"
        assert data["privacy"]["text"] == "Datenschutz der Plattform"

    def test_einheit_ohne_anmeldung(self, orgs, zug):
        imprint = ensure(orgs["a"])
        imprint.registered = True
        imprint.register_number = "VR 1"
        imprint.save()
        data = public(f"/api/public/imprint/{ensure(zug).public_key}/").json()
        assert data["unit"] == "Jägerzug"
        assert data["owner"] == "Verein A"
        assert data["inherited"] is True
        assert data["details"]["register_number"] == "VR 1"
        assert data["platform"]["imprint"].endswith("/impressum")

    def test_verlinkt(self, orgs):
        imprint = ensure(orgs["a"])
        imprint.mode = Imprint.Mode.LINK
        imprint.external_url = "https://verein-a.example/impressum"
        imprint.save()
        data = public(f"/api/public/imprint/{imprint.public_key}/").json()
        assert data["details"] is None
        assert data["external_url"] == "https://verein-a.example/impressum"

    def test_unbekannt(self, db):
        assert public("/api/public/imprint/gibtsnicht/").status_code == 404

    def test_keine_privaten_daten(self, orgs, board_a):
        """Nur Name und Funktion der Vertretung, keine Kontodaten der Benutzer."""
        role = Role.objects.get(organization=orgs["a"], name="Vorstand")
        role.represents = True
        role.save()
        imprint = ensure(orgs["a"])
        text = public(f"/api/public/imprint/{imprint.public_key}/").content.decode()
        assert "vorstand-a@example.org" not in text


class TestMails:
    def test_fusszeile_mit_einheit(self, orgs, settings):
        settings.FRONTEND_URL = "https://hubiplan.example"
        send("x@example.org", "Betreff", "Hallo", organization=orgs["a"], html="<p>Hallo</p>")
        message = djmail.outbox[-1]
        key = ensure(orgs["a"]).public_key
        assert "im Auftrag von Verein A" in message.body
        assert f"https://hubiplan.example/impressum/{key}" in message.body
        assert f"https://hubiplan.example/datenschutz/{key}" in message.body
        html = message.alternatives[0][0]
        assert f'href="https://hubiplan.example/impressum/{key}"' in html

    def test_fusszeile_ohne_einheit(self, db, settings):
        settings.FRONTEND_URL = "https://hubiplan.example"
        send("x@example.org", "Betreff", "Hallo")
        assert "Impressum: https://hubiplan.example/impressum\n" in djmail.outbox[-1].body


class TestOeffentlicheSeiten:
    def test_kalender_abo_mit_impressum(self, orgs):
        from events.ical import calendar

        body = calendar("Verein A", [], "example.org", description="Impressum: https://x/1")
        assert b"X-WR-CALDESC:Impressum: https://x/1" in body


class TestDatenuebernahme:
    def test_impressum_wandert_mit(self, api, orgs, board_a, platform_admin):
        club = orgs["a"]
        imprint = ensure(club)
        imprint.register_number = "VR 77"
        imprint.privacy_text = "Unsere Hinweise"
        imprint.save()
        role = Role.objects.get(organization=club, name="Vorstand")
        role.represents = True
        role.save()
        content, _ = export(api(board_a), f"/api/orgs/{club.pk}")
        doc = as_doc(content)
        assert doc["organization"]["imprint"]["register_number"] == "VR 77"

        c = api(platform_admin)
        job = upload(c, "/api/platform", content)
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new = Organization.objects.get(pk=job["result_organization"]["id"])
            copy = Imprint.objects.get(organization=new)
            assert copy.register_number == "VR 77"
            assert copy.privacy_text == "Unsere Hinweise"
            assert copy.public_key != imprint.public_key
            assert Role.objects.get(organization=new, name="Vorstand").represents is True


class TestTexteErzeugen:
    def test_datenschutzhinweise_aus_einstellungen(self, orgs, zug):
        from billing.models import BillingSettings
        from members.models import MemberType
        from organizations.imprint_generator import unit_privacy

        club = orgs["a"]
        club.enabled_modules = ["members", "billing", "events"]
        club.member_portal_enabled = True
        club.save()
        orgs["federation"].federation_member_access = "read"
        orgs["federation"].save()
        with tenant_context(club.pk):
            BillingSettings.objects.update_or_create(
                organization=club, defaults={"sepa_enabled": True}
            )
            MemberType.objects.create(organization=club, name="aktiv", active=True, reported=True)
        imprint = ensure(club)
        imprint.email = "info@verein-a.example"
        imprint.save()

        text = unit_privacy(club)
        assert text.startswith("Datenschutzhinweise für Mitglieder von Verein A")
        assert "Hauptstraße 1, 12345 Musterstadt" in text
        assert "info@verein-a.example" in text
        assert "SEPA-Lastschriftmandat" in text
        assert "Zu- und Absagen" in text
        assert "Mitgliederbereich" in text
        assert "Testbund: Name, Geburtsdatum" in text
        assert "Testbund kann die Mitgliedsdaten in HUBIplan außerdem einsehen" in text
        assert "nach 24 Monaten" in text
        assert "Kassenführung" not in text  # Kasse nicht eingeschaltet
        assert "Verantwortliche der Untereinheiten (Abteilungen)" in text

    def test_ohne_meldung_und_lastschrift(self, orgs):
        from organizations.imprint_generator import unit_privacy

        text = unit_privacy(orgs["c"])
        assert "SEPA" not in text
        assert "Verbandsbeitrag" not in text
        assert "[Vorstand nach § 26 BGB]" in text

    def test_plattform(self, db, settings):
        from organizations.imprint_generator import platform_privacy

        settings.FRONTEND_URL = "https://hubiplan.example"
        settings.EMAIL_HOST = ""
        imprint = ensure(Organization.platform())
        imprint.name = "Max Betreiber"
        imprint.street = "Weg 2"
        imprint.postal_code = "11111"
        imprint.city = "Ort"
        imprint.save()
        text = platform_privacy()
        assert text.startswith("Datenschutzerklärung für hubiplan.example")
        assert "Max Betreiber, Weg 2, 11111 Ort" in text
        assert "keine Analyse- oder Werbe-Cookies" in text
        assert "Local und Session Storage" in text
        assert "nicht nach außen versandt" in text

    def test_registerangaben_nur_bei_eingetragenen(self, orgs):
        imprint = ensure(orgs["a"])
        imprint.mode = "own"
        imprint.register_court = "Amtsgericht Musterstadt"
        imprint.register_number = "VR 9"
        imprint.save()
        data = public(f"/api/public/imprint/{imprint.public_key}/").json()["details"]
        assert data["registered"] is False
        assert data["register_court"] == "" and data["register_number"] == ""
        assert data["legal_form"] == ""
        assert not {"Registergericht", "Registernummer"} & set(missing(orgs["a"], imprint))
        imprint.registered = True
        imprint.register_number = ""
        imprint.save()
        data = public(f"/api/public/imprint/{imprint.public_key}/").json()["details"]
        assert data["register_court"] == "Amtsgericht Musterstadt"
        assert data["legal_form"] == "eingetragener Verein"
        assert "Registernummer" in missing(orgs["a"], imprint)
        assert "Registergericht" not in missing(orgs["a"], imprint)

    def test_rechtsform_aus_dem_namen(self, orgs):
        orgs["federation"].name = "Testbund e.V."
        orgs["federation"].save()
        data = public(f"/api/public/imprint/{ensure(orgs['federation']).public_key}/").json()
        assert data["details"]["legal_form"] == "eingetragener Verein"


def test_demodaten_fuellen_nur_leere_impressen(orgs):
    from organizations.imprint_seed import seed_imprints

    platform = Organization.platform()
    Role.objects.create(organization=orgs["a"], name="Vorstand")
    gepflegt = ensure(orgs["federation"])
    gepflegt.phone = "echt gepflegt"
    gepflegt.save()
    seed_imprints({"platform": platform, "federation": orgs["federation"], "club": orgs["a"]})
    assert "erfunden" in ensure(platform).name
    assert ensure(orgs["a"]).register_number == "VR 0002"
    assert ensure(orgs["a"]).privacy_text.startswith("Datenschutzhinweise für Mitglieder")
    assert ensure(orgs["federation"]).phone == "echt gepflegt"
    assert ensure(orgs["federation"]).register_number == ""
    assert Role.objects.get(organization=orgs["a"], name="Vorstand").represents is True


def test_briefbogen_registerangaben_nur_bei_eingetragenen(orgs):
    from letterhead.data import register_lines

    imprint = ensure(orgs["a"])
    imprint.mode = "own"
    imprint.register_court = "Amtsgericht Musterstadt (erfunden)"
    imprint.register_number = "VR 5"
    imprint.vat_id = "DE000000000"
    imprint.save()
    assert register_lines(orgs["a"]) == ["USt-IdNr. DE000000000"]
    imprint.registered = True
    imprint.save()
    assert register_lines(orgs["a"])[0] == "Amtsgericht Musterstadt (erfunden), VR 5"


def test_neues_impressum_mit_ev_im_namen_ist_eingetragen(orgs):
    orgs["b"].name = "Beispielverein e.V."
    orgs["b"].save()
    Imprint.objects.filter(organization=orgs["b"]).delete()
    assert ensure(orgs["b"]).registered is True
    assert ensure(orgs["federation"]).registered is False
