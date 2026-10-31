# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Regressionstests zum Audit vom 29.10.2026: Webseite und Chronik (S29-02 bis S29-05)."""

import uuid

import pytest
from django.core import mail

from honors.models import Reign
from website import contact
from website.models import HeldMessage, WebsiteImage, WebsiteRevision

from . import test_webseite_schnittstelle as schnittstelle
from .test_webseite_inhalte import editor, png, site  # noqa: F401
from .test_webseite_inhalte import url as wurl
from .test_webseite_schnittstelle import setup  # noqa: F401
from .test_wuerden import koenig, people, xlsx  # noqa: F401
from .test_wuerden import url as hurl

pytestmark = pytest.mark.django_db(transaction=True)
JSON = "application/json"


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


class TestKontaktVersandfehler:
    """S29-04: Scheitert der Versand, wird nichts bestätigt und nichts gelöscht."""

    form = schnittstelle.TestKontakt.form
    post = schnittstelle.TestKontakt.post

    def test_versandfehler_ohne_bestaetigung_und_zur_freigabe(self, setup, monkeypatch):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        monkeypatch.setattr(contact, "deliver", lambda *a, **k: False)
        resp = self.post(self.form("allgemein", copy=True))
        assert resp.status_code == 200
        assert mail.outbox == []  # keine Bestätigung „angekommen“
        held = HeldMessage.objects.get()
        assert held.reason == contact.HOLD_FAILED
        assert held.body == "Wann ist das nächste Schützenfest?"

    def test_freigabe_mit_versandfehler_behaelt_nachricht(self, setup, monkeypatch, board_a, api):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        body = self.form("allgemein", message="Cheap viagra at http://a.example and more")
        assert self.post(body).status_code == 200
        held = HeldMessage.objects.get()
        monkeypatch.setattr(contact, "deliver", lambda *a, **k: False)
        url = f"/api/orgs/{setup['org'].pk}/website/held/{held.pk}/"
        resp = api(board_a).post(url)
        assert resp.status_code == 409
        assert "bleibt in der Liste" in resp.json()["detail"]
        assert HeldMessage.objects.filter(pk=held.pk).exists()


class TestFruehereFassungen:
    """S29-05: Bilder früherer Fassungen nur nach ausdrücklicher Rückfrage löschen."""

    def test_bild_einer_frueheren_fassung(self, orgs, editor, api, site):
        c = api(editor)
        image = c.post(wurl(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        text = c.post(
            wurl(orgs["a"], "texts/"),
            {"slug": "fahne", "title": "Fahne", "body": image["markdown"]},
            JSON,
        ).json()
        c.post(wurl(orgs["a"], f"texts/{text['id']}/publish/"))
        c.put(wurl(orgs["a"], f"texts/{text['id']}/"), {"body": "ohne Bild"}, JSON)
        c.post(wurl(orgs["a"], f"texts/{text['id']}/publish/"))
        # Aktuell unbenutzt, aber Fassung 1 zeigt es noch: erst nachfragen
        resp = c.delete(wurl(orgs["a"], f"images/{image['id']}/"))
        assert resp.status_code == 409
        assert "Fahne" in resp.json()["detail"] and len(resp.json()["revisions"]) == 1
        assert WebsiteImage.objects.filter(pk=image["id"]).exists()
        resp = c.delete(wurl(orgs["a"], f"images/{image['id']}/?fruehere_fassungen=1"))
        assert resp.status_code == 204
        assert not WebsiteImage.objects.exists()
        assert WebsiteRevision.objects.count() == 2

    def test_nie_benutztes_bild_ohne_rueckfrage(self, orgs, editor, api, site):
        c = api(editor)
        image = c.post(wurl(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        assert c.delete(wurl(orgs["a"], f"images/{image['id']}/")).status_code == 204


class TestChronikImport:
    def rows(self, people):
        return {
            "rows": [
                {
                    "year": 2023,
                    "dignity": "König",
                    "name": "Muster, Otto",
                    "person_id": people["otto"].person_id,
                }
            ]
        }

    def test_s29_02_wiederholte_uebernahme_legt_nichts_doppelt_an(
        self, orgs, board_a, api, people, koenig
    ):
        c = api(board_a)
        key = str(uuid.uuid4())
        data = self.rows(people)
        first = c.post(hurl(orgs["a"], "import/"), data, JSON, HTTP_IDEMPOTENCY_KEY=key)
        again = c.post(hurl(orgs["a"], "import/"), data, JSON, HTTP_IDEMPOTENCY_KEY=key)
        assert first.status_code == 201 and again.status_code == 200
        assert again.json() == first.json()
        assert Reign.objects.count() == 1
        # Derselbe Schlüssel mit anderer Auswahl: Konflikt statt stiller Erfolgsmeldung
        data["rows"][0]["year"] = 2024
        other = c.post(hurl(orgs["a"], "import/"), data, JSON, HTTP_IDEMPOTENCY_KEY=key)
        assert other.status_code == 409
        assert Reign.objects.count() == 1

    def test_s29_03_lange_texte_werden_gemeldet_nicht_gekuerzt(self, orgs, board_a, api):
        long_name = "N" * 201
        file = xlsx(
            [
                ["Jahr", "Würde", "Name", "Begleitung", "Bemerkung"],
                [2023, "W" * 101, long_name, "B" * 61 + ": Erika", "x" * 201],
                [2024, "König", "Otto Muster", "", ""],
            ]
        )
        resp = api(board_a).post(hurl(orgs["a"], "import/preview/"), {"file": file})
        assert resp.status_code == 200, resp.content
        rows = resp.json()["rows"]
        errors = " ".join(rows[0]["errors"])
        assert "Würde ist zu lang (101 Zeichen" in errors
        assert "Name ist zu lang (201 Zeichen" in errors
        assert "Bemerkung ist zu lang" in errors
        assert "Begleitung (Bezeichnung) ist zu lang" in errors
        assert rows[0]["name"] == long_name  # ungekürzt angezeigt
        assert rows[1]["errors"] == []
