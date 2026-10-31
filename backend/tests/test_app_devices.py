"""Android-App, Schritt A1: Geräte verbinden und mit dem Geräteschlüssel arbeiten."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import datetime

import pytest
from django.test import Client
from django.utils import timezone

from devices.models import Device, PairingCode
from portal import services as portal_services
from portal.models import PortalAccess

from .factories import PASSWORD, give_role, make_user
from .test_m12_events import (  # noqa: F401  (Fixtures)
    JSON,
    cal,
    member_with_access,
    org_base,
)
from .test_m13_rsvp import SOON, respond, rsvp_event

pytestmark = pytest.mark.django_db
APP = "/api/app/v1/"


def pairing_code(client) -> str:
    resp = client.post(f"{APP}pairing/")
    assert resp.status_code == 201, resp.json()
    url = resp.json()["url"]
    assert "#code=" in url
    return url.split("#code=")[1]


def pair(code="", login_link="", name="Pixel 8"):
    return Client().post(
        f"{APP}pair/",
        {"code": code, "login_link": login_link, "name": name, "app_version": "1"},
        content_type=JSON,
    )


# Vorstandsschlüssel → Geräteschlüssel desselben Geräts (der Vorstandsschlüssel gilt nur mit ihm)
DEVICE_OF_ADMIN: dict[str, str] = {}
# Vorstandsschlüssel → privater Vorstands-Schlüssel (jede Vorstandsanfrage ist unterschrieben)
ADMIN_KEYS: dict[str, object] = {}


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _public(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return _b64(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )


class _AppClient(Client):
    """Wie die App: Geräteschlüssel, beim Freischalten Schlüsselpaare (Fachfrage 3) und
    unterschriebene Vorstandsanfragen."""

    def __init__(self, token: str):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        if token in DEVICE_OF_ADMIN:
            headers["HTTP_X_HUBIPLAN_DEVICE"] = DEVICE_OF_ADMIN[token]
        super().__init__(**headers)
        self.token = token

    def post(self, path, data=None, *args, **kwargs):
        key = None
        if path.endswith("/admin/unlock/") and isinstance(data, dict) and "admin_key" not in data:
            from cryptography.hazmat.primitives.asymmetric import ec

            # Geräteschlüsselpaar nachmelden (wie die App) und Vorstands-Schlüsselpaar mitgeben
            device_key = _public(ec.generate_private_key(ec.SECP256R1()))
            super().put(f"{APP}devices/current/key/", {"device_key": device_key}, content_type=JSON)
            key = ec.generate_private_key(ec.SECP256R1())
            data = {**data, "admin_key": _public(key)}
        resp = super().post(path, data, *args, **kwargs)
        if path.endswith("/admin/unlock/") and resp.status_code == 201:
            DEVICE_OF_ADMIN[resp.json()["token"]] = self.token
            if key is not None:
                ADMIN_KEYS[resp.json()["token"]] = key
        return resp

    def generic(self, method, path, data="", content_type="application/octet-stream", **extra):
        key = ADMIN_KEYS.get(self.token)
        if key is not None and "HTTP_X_HUBIPLAN_SIGNATURE" not in extra:
            import secrets
            import time
            from urllib.parse import urlsplit

            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec

            from devices import devicekey

            body = data.encode() if isinstance(data, str) else (data or b"")
            parts = urlsplit(path)
            query = extra.get("QUERY_STRING") or parts.query
            if extra.get("query_params"):
                from urllib.parse import urlencode

                query = urlencode(extra["query_params"], doseq=True)
            headers = {k.lower(): v for k, v in (extra.get("headers") or {}).items()}
            full = parts.path + (f"?{query}" if query else "")
            ts = str(int(time.time()))
            nonce = secrets.token_urlsafe(16)
            message = devicekey.admin_message(
                method,
                full,
                ts,
                body,
                nonce=nonce,
                idempotency=extra.get("HTTP_IDEMPOTENCY_KEY") or headers.get("idempotency-key", ""),
            )
            extra.update(
                HTTP_X_HUBIPLAN_TIME=ts,
                HTTP_X_HUBIPLAN_NONCE=nonce,
                HTTP_X_HUBIPLAN_SIGNATURE=_b64(key.sign(message, ec.ECDSA(hashes.SHA256()))),
            )
        return super().generic(method, path, data, content_type, **extra)


def app(token: str, *, with_device: bool = True) -> Client:
    """Client der App; zum Vorstandsschlüssel kommt der Geräteschlüssel automatisch dazu."""
    if not with_device:
        return Client(HTTP_AUTHORIZATION=f"Bearer {token}")
    return _AppClient(token)


@pytest.fixture
def member(cal):
    _, user, access = member_with_access(cal["a"], "Erika")
    return user, access


@pytest.fixture
def token(member, api):
    user, _ = member
    resp = pair(pairing_code(api(user)))
    assert resp.status_code == 201, resp.json()
    return resp.json()["token"]


class TestVerbinden:
    def test_instanz_ohne_anmeldung(self):
        data = Client().get(f"{APP}instance/").json()
        assert data["product"] == "HUBIplan" and data["api_version"] == 1

    def test_qr_code_einmal_nutzbar(self, member, api):
        user, _ = member
        code = pairing_code(api(user))
        resp = pair(code)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["token"].startswith("hpd_")
        assert data["user"]["email"] == user.email
        device = Device.objects.get()
        # nur die Prüfsumme liegt in der Datenbank
        assert data["token"] not in device.token_hash
        assert pair(code).status_code == 404

    def test_qr_code_laeuft_ab_und_neuer_ersetzt_alten(self, member, api):
        user, _ = member
        old = pairing_code(api(user))
        new = pairing_code(api(user))
        assert pair(old).status_code == 404
        PairingCode.objects.filter(used_at__isnull=True).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1)
        )
        assert pair(new).status_code == 404

    def test_qr_code_nur_mit_mitgliederbereich(self, cal, api, board_a):
        resp = api(board_a).post(f"{APP}pairing/")
        assert resp.status_code == 400

    def test_qr_code_nur_im_browser(self, token):
        # Mit dem Geräteschlüssel lässt sich kein weiterer Code erzeugen
        assert app(token).post(f"{APP}pairing/").status_code in (401, 403)

    def test_mit_anmeldelink(self, member):
        user, _ = member
        link = portal_services.create_login_link(user).rsplit("/", 1)[1]
        resp = pair(login_link=link)
        assert resp.status_code == 201, resp.json()
        assert pair(login_link=link).status_code == 404

    def test_anmeldelink_nicht_fuer_vorstand(self, cal, member):
        user, _ = member
        give_role(user, cal["a"])
        link = portal_services.create_login_link(user).rsplit("/", 1)[1]
        assert pair(login_link=link).status_code == 403

    def test_mit_passwort_ueber_allauth_app(self, member):
        user, _ = member
        c = Client()
        resp = c.post(
            "/_allauth/app/v1/auth/login",
            {"email": user.email, "password": PASSWORD},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        session_token = resp.json()["meta"]["session_token"]
        resp = Client().post(
            f"{APP}devices/",
            {"name": "Tablet"},
            content_type=JSON,
            HTTP_X_SESSION_TOKEN=session_token,
        )
        assert resp.status_code == 201, resp.json()
        token = resp.json()["token"]
        assert app(token).get(f"{APP}me/").status_code == 200
        # Die Sitzung der Anmeldung ist danach verbraucht
        resp = Client().post(
            f"{APP}devices/",
            {"name": "Zweites"},
            content_type=JSON,
            HTTP_X_SESSION_TOKEN=session_token,
        )
        assert resp.status_code in (401, 403)

    def test_geraet_nicht_aus_dem_browser(self, member, api):
        user, _ = member
        resp = api(user).post(f"{APP}devices/", {"name": "x"}, content_type=JSON)
        assert resp.status_code == 403


class TestGeraeteschluessel:
    def test_uebersicht(self, token, member):
        _, access = member
        data = app(token).get(f"{APP}me/").json()
        assert data["device"]["name"] == "Pixel 8" and data["device"]["current"]
        assert [p["id"] for p in data["portal"]] == [access.pk]

    def test_termine_und_rueckmeldung(self, cal, board_a, api, token, member):
        _, access = member
        event = rsvp_event(api(board_a), org_base(cal["a"]))
        c = app(token)
        listed = c.get(f"/api/portal/{access.pk}/events/?from={SOON}&to={SOON}").json()["items"]
        assert [i["title"] for i in listed] == ["Königsschießen"]
        # ohne CSRF-Token, weil keine Sitzung im Spiel ist
        resp = respond(c, access, event["id"])
        assert resp.status_code == 200, resp.json()
        assert resp.json()["rsvp"]["mine"]["status"] == "yes"
        assert c.get("/api/me/contexts/").status_code == 200

    def test_nicht_fuer_vorstandsfunktionen(self, cal, member, api):
        user, _ = member
        give_role(user, cal["a"])
        token = pair(pairing_code(api(user))).json()["token"]
        resp = app(token).get(f"{org_base(cal['a'])}events/")
        assert resp.status_code == 401
        assert app(token).get("/api/me/account/").status_code == 401

    def test_falscher_schluessel(self, member):
        _, access = member
        assert app("hpd_falsch").get(f"/api/portal/{access.pk}/").status_code == 401

    def test_abmelden(self, token, member, api):
        user, access = member
        device = Device.objects.get()
        listed = api(user).get(f"{APP}devices/").json()
        assert [d["id"] for d in listed] == [device.pk] and not listed[0]["current"]
        assert app(token).get(f"{APP}devices/").json()[0]["current"]
        assert api(user).delete(f"{APP}devices/{device.pk}/").status_code == 204
        assert app(token).get(f"/api/portal/{access.pk}/").status_code == 401

    def test_fremdes_geraet_nicht_abmelden(self, token, cal, api):
        other = make_user("fremd@example.org")
        device = Device.objects.get()
        assert api(other).delete(f"{APP}devices/{device.pk}/").status_code == 404

    def test_lange_ungenutzt(self, token, member):
        _, access = member
        Device.objects.update(last_seen_at=timezone.now() - datetime.timedelta(days=181))
        assert app(token).get(f"/api/portal/{access.pk}/").status_code == 401

    def test_passwort_geaendert(self, token, member):
        from allauth.account import signals

        user, access = member
        signals.password_changed.send(sender=type(user), request=None, user=user)
        assert app(token).get(f"/api/portal/{access.pk}/").status_code == 401

    def test_zugang_entfernt(self, token, member):
        _, access = member
        PortalAccess.objects.filter(pk=access.pk).delete()
        assert Device.objects.get().revoked_at is not None

    def test_hoechstens_zehn_geraete(self, member):
        user, _ = member
        from devices.views import _create_device

        for i in range(11):
            _create_device(user, {"name": f"Gerät {i}", "platform": "android"})
        assert Device.objects.filter(revoked_at__isnull=True).count() == 10


def test_passwort_mit_2fa(member):
    from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret

    from .test_auth import totp_code

    user, _ = member
    secret = generate_totp_secret()
    TOTP.activate(user, secret)
    resp = Client().post(
        "/_allauth/app/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type=JSON,
    )
    assert resp.status_code == 401
    body = resp.json()
    assert any(f["id"] == "mfa_authenticate" and f.get("is_pending") for f in body["data"]["flows"])
    session_token = body["meta"]["session_token"]
    # vor der 2FA gibt es keinen Geräteschlüssel
    resp = Client().post(
        f"{APP}devices/", {"name": "x"}, content_type=JSON, HTTP_X_SESSION_TOKEN=session_token
    )
    assert resp.status_code in (401, 403)
    resp = Client().post(
        "/_allauth/app/v1/auth/2fa/authenticate",
        {"code": totp_code(secret)},
        content_type=JSON,
        HTTP_X_SESSION_TOKEN=session_token,
    )
    assert resp.status_code == 200, resp.json()
    session_token = resp.json()["meta"].get("session_token", session_token)
    resp = Client().post(
        f"{APP}devices/", {"name": "x"}, content_type=JSON, HTTP_X_SESSION_TOKEN=session_token
    )
    assert resp.status_code == 201, resp.json()


def test_anmeldeschluss_in_der_terminliste(cal, board_a, api, token, member):
    _, access = member
    deadline = f"{SOON - datetime.timedelta(days=2)}T18:00:00"
    rsvp_event(api(board_a), org_base(cal["a"]), rsvp_deadline=deadline)
    items = app(token).get(f"/api/portal/{access.pk}/events/?from={SOON}&to={SOON}").json()["items"]
    assert items[0]["rsvp_deadline"].startswith(str(SOON - datetime.timedelta(days=2)))


class TestHinweise:
    """Härtung G2: neues Gerät fällt auf (konzepte/haertung-austausch.md)."""

    def test_mail_und_anzeige_im_browser(self, member, api, django_capture_on_commit_callbacks):
        from django.core import mail

        user, _ = member
        browser = api(user)
        resp = browser.post(f"{APP}pairing/")
        assert resp.status_code == 201
        pk = resp.json()["id"]
        code = resp.json()["url"].split("#code=", 1)[1]
        assert browser.get(f"{APP}pairing/{pk}/").json()["used"] is False
        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            assert pair(code).status_code == 201
        status = browser.get(f"{APP}pairing/{pk}/").json()
        assert status["used"] is True and status["device"] == "Pixel 8"
        assert [m.subject for m in mail.outbox] == ["Neues Gerät mit deinem Zugang verbunden"]
        assert mail.outbox[0].to == [user.email]

    def test_fremder_code_nicht_sichtbar(self, member, api, cal):
        user, _ = member
        pk = api(user).post(f"{APP}pairing/").json()["id"]
        _, other, _ = member_with_access(cal["a"], "Fritz")
        assert api(other).get(f"{APP}pairing/{pk}/").status_code == 404


class TestKontosicherheit:
    """Gesamtaudit 30.10. (BSEC-01, BSEC-03): eigener Passwortwechsel meldet Geräte ab,
    offene QR-Codes verfallen bei Sicherheitsänderungen."""

    def test_eigener_passwortwechsel_meldet_geraete_ab(self, member, token, api):
        member, _ = member
        assert app(token).get(f"{APP}me/").status_code == 200
        open_code = pairing_code(api(member))
        resp = api(member).post(
            "/api/me/password/",
            {"current_password": PASSWORD, "new_password": "Ganz-Neues-Passwort-42"},
            content_type=JSON,
        )
        assert resp.status_code == 200
        assert app(token).get(f"{APP}me/").status_code == 401
        assert not Device.objects.filter(user=member, revoked_at__isnull=True).exists()
        # Vorher erzeugter QR-Code gilt nicht mehr
        assert pair(code=open_code).status_code in (400, 404)

    def test_erstes_passwort_laesst_geraete(self, member, token, api):
        member, _ = member
        member.set_unusable_password()
        member.save()
        open_code = pairing_code(api(member))
        resp = api(member).post(
            "/api/me/password/", {"new_password": "Ganz-Neues-Passwort-42"}, content_type=JSON
        )
        assert resp.status_code == 200
        assert app(token).get(f"{APP}me/").status_code == 200
        assert pair(code=open_code).status_code in (400, 404)
