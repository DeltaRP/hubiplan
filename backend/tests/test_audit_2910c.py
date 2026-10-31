# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""UI-/UX-Audit 29.10.2026 Teil c: Serverseite (NMF-06, NMF-11, NAF-02, NAF-06)."""

import pytest

from honors.models import Dignity
from organizations.imprint import ensure, public_data
from organizations.models import Organization

from .factories import make_user
from .test_impressum import platform_admin  # noqa: F401
from .test_m9_billing import _private, base, c, club, members, setup, start_run, zug  # noqa: F401
from .test_m12_events import (  # noqa: F401
    JSON,
    cal,
    private_root,
    zug2,  # noqa: F401
)
from .test_m12_events import zug as cal_zug  # noqa: F401
from .test_rundschreiben import base as cbase
from .test_rundschreiben import draft, preview
from .test_rundschreiben import members as cmembers  # noqa: F401
from .test_wuerden import koenig, people  # noqa: F401
from .test_wuerden import url as hurl

pytestmark = pytest.mark.django_db


class TestNurAusgewaehlte:
    """NMF-06: „nur ausgewählte“ ohne Häkchen heißt niemand, nie still alle."""

    def test_leere_auswahl_heisst_niemand(self, cal, board_a, cmembers, api):
        c = api(board_a)
        url = cbase(cal["a"])
        alle = draft(c, url)
        assert preview(c, url, alle["id"])["counts"]["mail"] >= 1
        leer = draft(c, url, filters={"departments": [], "selected": ["departments"]})
        assert leer["filters"]["selected"] == ["departments"]
        counts = preview(c, url, leer["id"])["counts"]
        assert counts["mail"] + counts["letter"] == 0

    def test_unbekannte_listen_werden_verworfen(self, cal, board_a, api):
        c = api(board_a)
        data = draft(c, cbase(cal["a"]), filters={"selected": ["departments", "passwort"]})
        assert data["filters"]["selected"] == ["departments"]


class TestChronikImport:
    """NMF-11: neue Würden aus dem Import sind erst intern."""

    def test_neue_wuerde_intern(self, orgs, board_a, api, people, koenig):
        rows = {
            "rows": [
                {"year": 2020, "dignity": "König", "name": "Otto Muster"},
                {"year": 1961, "dignity": "Kaiser", "name": "Wilhelm Vorzeit"},
            ]
        }
        resp = api(board_a).post(hurl(orgs["a"], "import/"), rows, JSON)
        assert resp.status_code == 201, resp.json()
        assert resp.json()["dignities_created"] == ["Kaiser"]
        assert Dignity.objects.get(name="Kaiser").is_public is False
        assert Dignity.objects.get(name="König").is_public is True


class TestPostversand:
    """NAF-06: Postversand als erledigt vermerken und zurücknehmen."""

    def test_vermerken_und_zuruecknehmen(self, c, base, members):
        run = start_run(c, base).json()
        c.post(f"{base}/runs/{run['id']}/finalize/")
        resp = c.post(f"{base}/runs/{run['id']}/postversand/", {"done": True}, JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["post_done_at"]
        assert resp.json()["summary"]["without_email"] == 1
        resp = c.post(f"{base}/runs/{run['id']}/postversand/", {"done": False}, JSON)
        assert resp.json()["post_done_at"] is None


class TestDatenschutzEntwurf:
    """NAF-02: Erzeugen und Bearbeiten ändern nur den Entwurf."""

    def test_entwurf_erst_nach_veroeffentlichen_oeffentlich(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/imprint/"
        old = ensure(orgs["a"])
        old.privacy_published_text = "Alte Fassung (erfunden)"
        old.save()
        resp = c.patch(url, {"privacy_text": "Neuer Entwurf [Hosting-Anbieter]"}, JSON)
        assert resp.status_code == 200
        assert public_data(orgs["a"])["privacy"]["text"] == "Alte Fassung (erfunden)"
        resp = c.post(url, {"action": "publish_privacy"}, JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["imprint"]["privacy_published_at"]
        assert public_data(orgs["a"])["privacy"]["text"] == "Neuer Entwurf [Hosting-Anbieter]"

    def test_leerer_entwurf_wird_nicht_veroeffentlicht(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/imprint/"
        c.patch(url, {"privacy_text": ""}, JSON)
        assert c.post(url, {"action": "publish_privacy"}, JSON).status_code == 400
        assert c.post(url, {"action": "anderes"}, JSON).status_code == 400

    def test_nur_mit_recht(self, api, orgs):
        user = make_user("ohne@example.org")
        resp = api(user).post(
            f"/api/orgs/{orgs['a'].pk}/imprint/", {"action": "publish_privacy"}, JSON
        )
        assert resp.status_code in (403, 404)

    def test_plattform(self, api, platform_admin):
        c = api(platform_admin)
        c.patch("/api/platform/imprint/", {"privacy_text": "Plattform (erfunden)"}, JSON)
        resp = c.post("/api/platform/imprint/", {"action": "publish_privacy"}, JSON)
        assert resp.status_code == 200, resp.json()
        assert public_data(Organization.platform())["privacy"]["text"] == "Plattform (erfunden)"
