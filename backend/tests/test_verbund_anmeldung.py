# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 7: Anmelden über eine gekoppelte Instanz (erfundene Daten).

Der Vorstand des Vereins (verein.example) hat auch einen Zugang beim Dachverband
(verband.example). Er verknüpft beide einmal und meldet sich danach beim Verein mit
dem Zugang des Dachverbands an.
"""

import json
import urllib.parse

import pytest
from django.test import Client

from organizations.models import Organization, PlatformSettings
from peering import identity
from peering.models import LoginLink, RemoteAccount

from .factories import PASSWORD, give_role, make_user
from .test_auth import totp_code
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def coupled(net, world):
    ps = PlatformSettings.load()
    ps.peering_login = True
    ps.save()
    couple(net, world)
    # Mitglied ohne Rollen beim Verein (Konten mit Rollen brauchen hier zusätzlich 2FA)
    world["club_user"] = make_user("verein@example.org".replace("verein@", "mitglied@verein."))
    with net.on(VERBAND):
        verband_id = identity.identity().instance_id
    with net.on(VEREIN):
        verein_id = identity.identity().instance_id
    return {"verband": verband_id, "verein": verein_id}


def start(net, client, idp, purpose="login", next_path="/"):
    with net.on(VEREIN):
        resp = client.post(
            "/api/peering/sso/start/",
            {"idp": idp, "purpose": purpose, "next": next_path},
            content_type=JSON,
        )
    return resp


def confirm(net, home_client, url, code=None):
    """Auf der Heimat-Instanz bestätigen; liefert die Bestätigung aus dem Rücksprung."""
    parts = urllib.parse.urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == VERBAND and parts.path == "/verbund/anmelden"
    query = dict(urllib.parse.parse_qsl(parts.query))
    with net.on(VERBAND):
        info = home_client.get("/api/peering/sso/describe/", {"rp": query["rp"]})
        assert info.status_code == 200, info.json()
        assert info.json()["base_url"] == VEREIN
        resp = home_client.post("/api/peering/sso/issue/", query, content_type=JSON)
        # Testanmeldung ohne Anmeldeweg: zu alt, also Passwort (und Code) bestätigen
        assert resp.status_code == 409 and resp.json()["reauth"], resp.json()
        extra = {"password": PASSWORD, **({"code": code} if code else {})}
        resp = home_client.post("/api/peering/sso/issue/", {**query, **extra}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    back = resp.json()["url"]
    assert back.startswith(f"{VEREIN}/verbund/angemeldet#")
    return back.split("#", 1)[1]


def finish(net, client, token):
    with net.on(VEREIN):
        return client.post("/api/peering/sso/finish/", {"token": token}, content_type=JSON)


def link(net, world, coupled, local_user=None):
    local = api(local_user or world["club_user"])
    resp = start(net, local, coupled["verband"], purpose="link")
    assert resp.status_code == 200, resp.json()
    token = confirm(net, api(world["fed_board"]), resp.json()["url"])
    resp = finish(net, local, token)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["purpose"] == "link"


def session_user(net, client):
    with net.on(VEREIN):
        resp = client.get("/_allauth/browser/v1/auth/session")
    return resp.status_code, resp.json()


class TestAnmeldung:
    def test_verknuepfen_und_anmelden(self, net, world, coupled):
        link(net, world, coupled)
        rl = LoginLink.objects.get(user=world["club_user"])
        assert rl.subject == str(world["fed_board"].pk) and rl.email == "verband@example.org"
        assert RemoteAccount.objects.filter(user=world["fed_board"]).exists()
        browser = Client()
        resp = start(net, browser, coupled["verband"], next_path="/termine")
        assert resp.status_code == 200, resp.json()
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        resp = finish(net, browser, token)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["next"] == "/termine"
        status, body = session_user(net, browser)
        assert status == 200 and body["data"]["user"]["email"] == "mitglied@verein.example.org"
        # Nur einmal nutzbar
        other = Client()
        start(net, other, coupled["verband"])
        assert finish(net, other, token).status_code == 400

    def test_wechsel_aus_der_einheitenauswahl(self, net, world, coupled):
        link(net, world, coupled)
        with net.on(VERBAND):
            data = api(world["fed_board"]).get("/api/peering/sso/account/").json()
        assert data["accounts"][0]["base_url"] == VEREIN
        url = data["accounts"][0]["url"]
        assert url == f"{VEREIN}/verbund/start?idp={coupled['verband']}"

    def test_ohne_verknuepfung_keine_anmeldung(self, net, world, coupled):
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        resp = finish(net, browser, token)
        assert resp.status_code == 400
        assert "keinem Konto verknüpft" in resp.json()["detail"]
        assert session_user(net, browser)[0] == 401

    def test_bestaetigung_nur_fuer_die_eigene_sitzung(self, net, world, coupled):
        link(net, world, coupled)
        attacker, victim = Client(), Client()
        resp = start(net, attacker, coupled["verband"])
        start(net, victim, coupled["verband"])
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        assert finish(net, victim, token).status_code == 400
        assert session_user(net, victim)[0] == 401

    def test_veraenderte_bestaetigung(self, net, world, coupled):
        link(net, world, coupled)
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        outer = json.loads(identity.unb64(token))
        outer["env"]["nonce"] = identity.b64(b"\0" * 12)
        forged = identity.b64(json.dumps(outer).encode())
        resp = finish(net, browser, forged)
        assert resp.status_code == 400 and "Unterschrift" in resp.json()["detail"]

    def test_2fa_hier_verlangt_2fa_dort(self, net, world, coupled):
        from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret

        link(net, world, coupled)
        TOTP.activate(world["club_user"], generate_totp_secret())
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        resp = finish(net, browser, token)
        assert resp.status_code == 403
        secret = generate_totp_secret()
        TOTP.activate(world["fed_board"], secret)
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        # Konto dort hat 2FA: ohne Code keine Bestätigung
        parts = urllib.parse.urlsplit(resp.json()["url"])
        query = dict(urllib.parse.parse_qsl(parts.query))
        with net.on(VERBAND):
            bad = api(world["fed_board"]).post(
                "/api/peering/sso/issue/", {**query, "password": PASSWORD}, content_type=JSON
            )
        assert bad.status_code == 403
        token = confirm(net, api(world["fed_board"]), resp.json()["url"], code=totp_code(secret))
        assert finish(net, browser, token).status_code == 200

    def test_ausgeschaltet(self, net, world, coupled):
        ps = PlatformSettings.load()
        ps.peering_login = False
        ps.save()
        resp = start(net, Client(), coupled["verband"])
        assert resp.status_code == 400
        with net.on(VEREIN):
            assert Client().get("/api/peering/sso/choices/").json() == []

    def test_plattformverwaltung_nie(self, net, world, coupled):
        admin = make_user("admin@verband.example")
        give_role(admin, Organization.platform())
        resp = start(net, Client(), coupled["verband"])
        parts = urllib.parse.urlsplit(resp.json()["url"])
        query = dict(urllib.parse.parse_qsl(parts.query))
        with net.on(VERBAND):
            resp = api(admin).post("/api/peering/sso/issue/", query, content_type=JSON)
        assert resp.status_code == 403

    def test_pausierte_kopplung_keine_anmeldung(self, net, world, coupled):
        from peering.models import Coupling

        link(net, world, coupled)
        Coupling.objects.filter(local_unit=world["club"]).update(state="paused")
        resp = start(net, Client(), coupled["verband"])
        assert resp.status_code == 400

    def test_unbekannte_instanz(self, net, world, coupled):
        resp = start(net, Client(), "00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 400

    def test_verknuepfung_loesen(self, net, world, coupled):
        link(net, world, coupled)
        with net.on(VEREIN):
            c = api(world["club_user"])
            data = c.get("/api/peering/sso/account/").json()
            assert data["links"][0]["base_url"] == VERBAND
            assert c.delete(f"/api/peering/sso/links/{data['links'][0]['id']}/").status_code == 204
        assert not LoginLink.objects.exists()


def test_csrf_beim_start(net, world, coupled):
    with net.on(VEREIN):
        resp = Client(enforce_csrf_checks=True).post(
            "/api/peering/sso/start/", {"idp": coupled["verband"]}, content_type=JSON
        )
    assert resp.status_code == 403


class TestHaertung:
    """Härtung S1/S2 (konzepte/haertung-austausch.md)."""

    def test_keine_kette(self, net, world, coupled):
        from django.contrib.auth import SESSION_KEY  # noqa: F401

        link(net, world, coupled)
        resp = start(net, Client(), coupled["verband"])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(resp.json()["url"]).query))
        home = api(world["fed_board"])
        with net.on(VERBAND):
            session = home.session
            session["account_authentication_methods"] = [
                {"method": "peering", "at": __import__("time").time()}
            ]
            session.save()
            resp = home.post(
                "/api/peering/sso/issue/", {**query, "password": PASSWORD}, content_type=JSON
            )
        assert resp.status_code == 403
        assert (
            "andere Instanz" in resp.json()["detail"] or "anderen Instanz" in resp.json()["detail"]
        )

    def test_frische_anmeldung_ohne_passwort(self, net, world, coupled):
        import time

        link(net, world, coupled)
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(resp.json()["url"]).query))
        home = api(world["fed_board"])
        with net.on(VERBAND):
            session = home.session
            session["account_authentication_methods"] = [
                {"method": "password", "at": time.time() - 60}
            ]
            session.save()
            resp = home.post("/api/peering/sso/issue/", query, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        token = resp.json()["url"].split("#", 1)[1]
        assert finish(net, browser, token).status_code == 200

    def test_veraltete_bestaetigung_abgelehnt(self, net, world, coupled):
        import time

        from peering import crypto

        link(net, world, coupled)
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(resp.json()["url"]).query))
        now = int(time.time())
        with net.on(VERBAND):
            ident = identity.identity()
            from peering.models import Peer

            peer = Peer.objects.get(instance_id=coupled["verein"])
            env = crypto.seal(
                {
                    "v": 1,
                    "iss": ident.instance_id,
                    "aud": coupled["verein"],
                    "sub": str(world["fed_board"].pk),
                    "mfa": True,
                    "state": query["state"],
                    "purpose": "login",
                    "iat": now,
                    "exp": now + 60,
                    "jti": "alt-1",
                },
                sender=ident.instance_id,
                recipient=coupled["verein"],
                recipient_enc_key=peer.enc_public_key,
            )
            canon = json.dumps(env, separators=(",", ":"), sort_keys=True).encode()
            outer = {"env": env, "sig": ident.sign(canon)}
            token = identity.b64(json.dumps(outer, separators=(",", ":"), sort_keys=True).encode())
        resp = finish(net, browser, token)
        assert resp.status_code == 400 and "nicht ausreichend" in resp.json()["detail"]

    def test_einmalig_auch_ohne_cache(self, net, world, coupled):
        from django.core.cache import cache

        link(net, world, coupled)
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        assert finish(net, browser, token).status_code == 200
        cache.clear()
        other = Client()
        start(net, other, coupled["verband"])
        assert finish(net, other, token).status_code == 400

    def test_vorstand_braucht_eigene_2fa(self, net, world, coupled):
        from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
        from django.core import mail

        link(net, world, coupled, local_user=world["club_board"])
        # Ohne eigene 2FA keine Anmeldung über die andere Instanz
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        token = confirm(net, api(world["fed_board"]), resp.json()["url"])
        resp = finish(net, browser, token)
        assert resp.status_code == 403 and "Zwei-Faktor" in resp.json()["detail"]
        secret = generate_totp_secret()
        TOTP.activate(world["club_board"], secret)
        home_secret = generate_totp_secret()
        TOTP.activate(world["fed_board"], home_secret)
        browser = Client()
        resp = start(net, browser, coupled["verband"])
        token = confirm(
            net, api(world["fed_board"]), resp.json()["url"], code=totp_code(home_secret)
        )
        resp = finish(net, browser, token)
        assert resp.status_code == 200 and resp.json()["mfa_required"], resp.json()
        assert session_user(net, browser)[0] == 401
        mail.outbox.clear()
        with net.on(VEREIN):
            resp = browser.post(
                "/api/peering/sso/finish/", {"code": totp_code(secret)}, content_type=JSON
            )
        assert resp.status_code == 200, resp.json()
        status, body = session_user(net, browser)
        assert status == 200 and body["data"]["user"]["email"] == "verein@example.org"
        assert browser.session.get_expiry_age() <= 12 * 60 * 60
        # Neuer Browser: Hinweis-Mail an das Konto
        assert [m.subject for m in mail.outbox] == ["Anmeldung über eine andere Instanz"]
        assert mail.outbox[0].to == ["verein@example.org"]


class TestLokalerFaktor:
    """Gesamtaudit 30.10.a (BSEC-V01): auch Rollen nur in einer Untereinheit."""

    def test_ohne_rolle_kein_eigener_faktor(self, net, world, coupled):
        from peering import sso

        with net.on(VEREIN):
            assert sso.needs_local_factor(world["club_user"]) is False

    def test_rolle_im_verein(self, net, world, coupled):
        from peering import sso

        with net.on(VEREIN):
            assert sso.needs_local_factor(world["club_board"]) is True

    def test_rolle_nur_in_einer_untereinheit(self, net, world, coupled, monkeypatch):
        from peering import sso
        from portal import services

        user = world["club_user"]
        monkeypatch.setattr(
            services, "department_contexts", lambda u: {1: object()} if u == user else {}
        )
        with net.on(VEREIN):
            assert sso.needs_local_factor(user) is True
