# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Regressionstests zum Gesamtaudit vom 29.10.2026, Teil b (G08, B-V05, W-S01, W-V01,
H-F01, R-V01). B-V04 steht in test_audit_2910b_versand.py."""

import datetime
import io

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from PIL import Image

from accounts.validators import ContextWordValidator, LeakedPasswordValidator
from events.models import CalendarPublication
from honors.importer import _plain
from statutes.models import StatutePublication
from website import contact
from website import services as website_services
from website.models import PreviewLink, Website

from .factories import give_role, make_user
from .test_cards import card_url, club, erika, scan, token_of, zug  # noqa: F401
from .test_m12_events import cal, private_root  # noqa: F401
from .test_statutes import upload
from .test_webseite_schnittstelle import TestKontakt, setup  # noqa: F401

KONTAKT = TestKontakt()

pytestmark = pytest.mark.django_db
JSON = "application/json"


class TestPasswortregeln:
    """G08: naheliegende Wörter und geleakte Passwörter."""

    def test_feste_woerter(self):
        v = ContextWordValidator()
        for pw in ("Schuetzen2024!", "HUBIplan-1234", "Schützenverein99"):
            with pytest.raises(ValidationError):
                v.validate(pw, None)
        v.validate("Kaffeetasse-Wolke-17", None)
        v.validate("7x#K9!pQ2@4z", None)  # zufällig, ohne naheliegendes Wort

    def test_vereinsname_und_ort(self, orgs):
        org = orgs["a"]
        org.name = "Hubertus-Schützen Grimlinghausen"
        org.city = "Neuss"
        org.save()
        user = make_user("vorstand-g08@example.org")
        give_role(user, org)
        v = ContextWordValidator()
        with pytest.raises(ValidationError):
            v.validate("Grimlinghausen1920", user)
        with pytest.raises(ValidationError):
            v.validate("Hubertus!Neuss2026", user)
        v.validate("Hubertus-Gartenzaun-Laterne", user)

    def test_geleakte_liste(self):
        v = LeakedPasswordValidator()
        assert len(v.passwords) > 10_000
        with pytest.raises(ValidationError):
            v.validate("password123", None)
        v.validate("Kaffeetasse-Wolke-17", None)


class TestDeaktivierteOrganisation:
    """B-V05: öffentliche Links einer deaktivierten Organisation sind gesperrt."""

    def test_ausweis(self, club, erika, api, board_a):
        api(board_a).post(card_url(club, erika), {"action": "create"}, content_type=JSON)
        token = token_of(erika)
        assert scan(token).status_code == 200
        club.is_active = False
        club.save(update_fields=["is_active"])
        resp = scan(token)
        assert resp.status_code == 404
        assert b"Erika" not in resp.content

    def test_satzung(self, orgs, board_a, api, private_root):
        c = api(board_a)
        upload(c, orgs["a"])
        c.put(
            f"/api/orgs/{orgs['a'].pk}/statutes/publication/",
            {"is_public": True},
            content_type=JSON,
        )
        key = StatutePublication.objects.get(organization=orgs["a"]).public_key
        assert Client().get(f"/api/public/statutes/{key}/").status_code == 200
        orgs["a"].is_active = False
        orgs["a"].save(update_fields=["is_active"])
        assert Client().get(f"/api/public/statutes/{key}/").status_code == 404
        assert Client().get(f"/api/public/statutes/{key}/info/").status_code == 404

    def test_kalender(self, cal, board_a, api):
        base_url = f"/api/orgs/{cal['a'].pk}/"
        api(board_a).put(f"{base_url}events/publication/", {"is_public": True}, content_type=JSON)
        key = CalendarPublication.objects.get().public_key
        assert Client().get(f"/api/public/calendar/{key}/").status_code == 200
        cal["a"].is_active = False
        cal["a"].save(update_fields=["is_active"])
        assert Client().get(f"/api/public/calendar/{key}/").status_code == 404
        assert Client().get(f"/api/public/calendar/{key}/termine.ics").status_code == 404


class TestVorschauWiderruf:
    """W-S01: Widerruf beendet auch schon eingetauschte Vorschau-Sitzungen."""

    def test_widerruf_beendet_sitzung(self, orgs):
        site = Website.objects.create(organization=orgs["a"], public_key=Website.new_key())
        link, token = PreviewLink.create(site, 3, "Vorstand", None)
        session, _ = website_services.exchange(site, token)
        assert website_services.valid_session(site, session)
        link.revoked_at = timezone.now()
        link.save(update_fields=["revoked_at"])
        assert not website_services.valid_session(site, session)

    def test_abgelaufener_link_beendet_sitzung(self, orgs):
        site = Website.objects.create(organization=orgs["a"], public_key=Website.new_key())
        link, token = PreviewLink.create(site, 3, "", None)
        session, _ = website_services.exchange(site, token)
        link.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        link.save(update_fields=["expires_at"])
        assert not website_services.valid_session(site, session)


def test_kontakt_fehler_vor_annahme_verbraucht_aufgabe_nicht(
    setup, monkeypatch, django_capture_on_commit_callbacks
):
    """W-V01: Ein Fehler vor der Annahme verbraucht die Aufgabe nicht."""
    monkeypatch.setattr(contact, "MIN_SECONDS", 0)
    body = KONTAKT.form("gibt-es-nicht")
    assert KONTAKT.post(body).status_code == 400
    body["recipient"] = "allgemein"
    # „verbraucht“ gilt erst nach dem Commit (Audit 31.10. R-CL-02)
    with django_capture_on_commit_callbacks(execute=True):
        assert KONTAKT.post(body).status_code == 200
    # Danach ist sie verbraucht
    assert KONTAKT.post(body).status_code == 400


class TestEhrungsimport:
    """H-F01: Namen in anderer Schrift bleiben erhalten."""

    def test_andere_schrift(self):
        assert _plain("Müller") == "mueller"
        assert _plain("José") == "jose"
        assert _plain("Παπαδόπουλος") == "παπαδοπουλος"
        assert _plain("Иванов") == "иванов"


class TestPixelgrenzen:
    """R-V01: keine prozessweite Abschaltung, Grenze auch für Briefbogenbilder."""

    def png(self, size):
        buf = io.BytesIO()
        Image.new("RGB", size, "white").save(buf, "PNG")
        return buf.getvalue()

    def test_logo_laesst_pillow_grenze_stehen(self):
        from core.filecheck import clean_logo

        before = Image.MAX_IMAGE_PIXELS
        clean_logo(self.png((20, 20)))
        assert Image.MAX_IMAGE_PIXELS == before is not None

    def test_briefbogenbild_zu_gross(self, monkeypatch):
        from letterhead import docx

        assert docx.load_picture(self.png((20, 20)), "a.png") is not None
        monkeypatch.setattr(docx, "MAX_PICTURE_PIXELS", 100)
        assert docx.load_picture(self.png((20, 20)), "a.png") is None
