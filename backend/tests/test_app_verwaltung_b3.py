"""Android-App, Schritt B3: Termine der Einheit und Rückmeldungen in der App."""
# ruff: noqa: F811  (Fixtures als Parameter)

import pytest
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret

from audit.models import AuditEntry
from core.tenancy import tenant_context
from events.models import EventResponse

from .factories import PASSWORD, give_role, make_member
from .test_app_devices import APP, app, pair, pairing_code
from .test_app_verwaltung import admin_token, board, fresh_code  # noqa: F401
from .test_m12_events import JSON, cal, member_with_access, zug  # noqa: F401
from .test_m13_rsvp import soon

pytestmark = pytest.mark.django_db
ADMIN = f"{APP}admin/u/"


@pytest.fixture
def base(cal):
    return f"{ADMIN}{cal['a'].pk}/"


@pytest.fixture
def termine(board, cal):
    """Vorstand darf zusätzlich Termine verwalten."""
    give_role(board["user"], cal["a"], ["events.manage"], name="Terminplanung")
    return board


@pytest.fixture
def anna(cal, zug):
    return make_member(cal["a"], "Anna", "Beispiel", departments=[zug])


def anlegen(c, base, **data):
    payload = {
        "title": "Königsschießen",
        "starts_at": soon(14),
        "ends_at": soon(18),
        "visibility": "members",
        "rsvp_enabled": True,
        **data,
    }
    resp = c.post(f"{base}events/", payload, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp


class TestTermine:
    def test_anlegen_liste_und_absagen(self, termine, admin_token, base, cal):
        c = app(admin_token)
        resp = anlegen(c, base)
        event = resp.json()
        assert resp["X-Change-Undoable"] == "1"
        listing = c.get(f"{base}events/?upcoming=1").json()
        assert listing["can_manage"] and listing["rsvp_allowed"]
        assert [i["event_id"] for i in listing["items"]] == [event["id"]]
        cancel = c.patch(
            f"{base}events/{event['id']}/",
            {"is_cancelled": True, "cancel_note": "Regen"},
            content_type=JSON,
        )
        assert cancel.status_code == 200, cancel.json()
        assert cancel.json()["is_cancelled"] is True
        with tenant_context(cal["a"].pk):
            entry = AuditEntry.objects.filter(organization=cal["a"]).latest("id")
        assert entry.via == "App (Pixel 8)"
        # Absage rückgängig
        undo = c.post(f"{base}changes/{cancel['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert c.get(f"{base}events/{event['id']}/").json()["is_cancelled"] is False

    def test_anlegen_rueckgaengig(self, termine, admin_token, base):
        c = app(admin_token)
        resp = anlegen(c, base)
        undo = c.post(f"{base}changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert c.get(f"{base}events/{resp.json()['id']}/").status_code == 404

    def test_ohne_terminrecht_nur_lesen(self, termine, admin_token, base, cal, api):
        event = anlegen(app(admin_token), base).json()
        # Zweiter Vorstand ohne events.manage
        _, user, _ = member_with_access(cal["a"], "Paul")
        give_role(user, cal["a"], ["members.view"], name="Beisitz")
        secret = generate_totp_secret()
        TOTP.activate(user, secret)
        token = pair(pairing_code(api(user))).json()["token"]
        resp = app(token).post(
            f"{APP}admin/unlock/",
            {"password": PASSWORD, "code": fresh_code(secret)},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        c = app(resp.json()["token"])
        listing = c.get(f"{base}events/")
        assert listing.status_code == 200 and listing.json()["can_manage"] is False
        assert c.post(f"{base}events/", {"title": "X"}, content_type=JSON).status_code == 403
        resp = c.patch(f"{base}events/{event['id']}/", {"is_cancelled": True}, content_type=JSON)
        assert resp.status_code == 403
        assert c.get(f"{base}events/{event['id']}/responses/").status_code == 403

    def test_nur_mit_vorstandsschluessel(self, termine, base):
        assert app(termine["token"]).get(f"{base}events/").status_code == 401


class TestRueckmeldungen:
    def test_eintragen_zaehlen_und_rueckgaengig(self, termine, admin_token, base, anna):
        c = app(admin_token)
        event = anlegen(c, base, rsvp_guests=True).json()
        url = f"{base}events/{event['id']}/responses/"
        before = c.get(url).json()
        assert before["summary"]["yes"] == 0
        assert anna.pk in [o["membership_id"] for o in before["open"]]
        resp = c.put(
            url, {"membership_id": anna.pk, "status": "yes", "guests": 2}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["source"] == "board"
        summary = c.get(url).json()["summary"]
        assert summary["yes"] == 1 and summary["persons"] == 3
        undo = c.post(f"{base}changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert not EventResponse.objects.filter(event_id=event["id"], membership=anna).exists()

    def test_entfernen(self, termine, admin_token, base, anna):
        c = app(admin_token)
        event = anlegen(c, base).json()
        url = f"{base}events/{event['id']}/responses/"
        c.put(url, {"membership_id": anna.pk, "status": "no"}, content_type=JSON)
        assert c.delete(f"{url}{anna.pk}/").status_code == 204
        assert c.get(url).json()["summary"]["no"] == 0

    def test_fremdes_mitglied(self, termine, admin_token, base, cal):
        c = app(admin_token)
        event = anlegen(c, base).json()
        fremd = make_member(cal["b"], "Fremd", "Andere")
        resp = c.put(
            f"{base}events/{event['id']}/responses/",
            {"membership_id": fremd.pk, "status": "yes"},
            content_type=JSON,
        )
        assert resp.status_code == 400


def test_aufgabe_rueckmeldungen_mit_termin(termine, admin_token, base):
    c = app(admin_token)
    # Aufgabe nur für Termine der nächsten Tage
    event = anlegen(c, base, starts_at=soon(14, days=-15), ends_at=soon(18, days=-15)).json()
    tasks = c.get(f"{base}tasks/").json()["items"]
    task = next(t for t in tasks if t["kind"] == "event")
    assert task["ref"] == event["id"]
