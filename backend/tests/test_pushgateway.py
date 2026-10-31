"""Android-App, Schritt A6: Push-Gateway für die Play-Fassung (FCM) und Google-Push in HUBIplan."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import base64
import io
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from devices import webpush
from devices.models import Device
from pushgateway import app as gw

from .test_app_devices import APP, app
from .test_app_push import (  # noqa: F401  (Fixtures)
    Receiver,
    allow_endpoint,
    anna,
    b64,
    push_outbox,
)
from .test_m12_events import JSON, cal  # noqa: F401

GATEWAY = "https://push.hubiplan.example"
TOKEN = "fcm-token_" + "x" * 40
ENDPOINT = f"{GATEWAY}/fcm/{TOKEN}"


def rsa_credentials() -> dict:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {
        "project_id": "hubiplan-test",
        "client_email": "gateway@hubiplan-test.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.example/token",
        "_key": key,
    }


class GoogleFake:
    """Ersetzt http_post: Anmeldung und FCM-Versand."""

    def __init__(self):
        self.calls = []
        self.fcm_answer = (200, {"name": "projects/x/messages/1"})

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": body})
        if url.endswith("/token"):
            return 200, {"access_token": "ya29.test", "expires_in": 3600}
        return self.fcm_answer

    @property
    def messages(self):
        return [json.loads(c["body"]) for c in self.calls if "fcm.googleapis.com" in c["url"]]


@pytest.fixture
def google(monkeypatch):
    fake = GoogleFake()
    monkeypatch.setattr(gw, "http_post", fake)
    return fake


@pytest.fixture
def creds():
    return rsa_credentials()


@pytest.fixture
def gateway(google, creds):
    data = {k: v for k, v in creds.items() if not k.startswith("_")}
    return gw.Gateway(GATEWAY, gw.Fcm(data), rate=3)


@pytest.fixture
def vapid(settings, tmp_path):
    settings.PUSH_VAPID_KEY_FILE = str(tmp_path / "vapid.json")
    webpush.reset_cache()
    return webpush


def push_request(body=None, *, endpoint=ENDPOINT, urgency="high", auth=None):
    body = body if body is not None else webpush.encrypt(b'{"t":"sync"}', *_receiver_keys())
    return {
        "content-encoding": "aes128gcm",
        "urgency": urgency,
        "ttl": "86400",
        "authorization": auth if auth is not None else webpush.vapid_header(endpoint),
    }, body


def _receiver_keys():
    r = Receiver()
    return r.p256dh, b64(r.auth)


class TestVapidPruefung:
    def test_gueltig(self, vapid):
        key = gw.check_vapid(vapid.vapid_header(ENDPOINT), GATEWAY)
        assert key == vapid.vapid_public_key()

    def test_andere_adresse(self, vapid):
        with pytest.raises(gw.Rejected):
            gw.check_vapid(vapid.vapid_header("https://andere.example/x"), GATEWAY)

    def test_abgelaufen(self, vapid):
        old = vapid.vapid_header(ENDPOINT, now=time.time() - 13 * 3600)
        with pytest.raises(gw.Rejected):
            gw.check_vapid(old, GATEWAY)

    def test_signatur_falsch(self, vapid):
        header = vapid.vapid_header(ENDPOINT)
        token = header.split("t=")[1].split(",")[0]
        head, body, sig = token.split(".")
        forged = header.replace(token, f"{head}.{body}.{b64(b'0' * 64)}")
        with pytest.raises(gw.Rejected):
            gw.check_vapid(forged, GATEWAY)
        with pytest.raises(gw.Rejected):
            gw.check_vapid("Bearer abc", GATEWAY)


class TestGateway:
    def test_reicht_an_fcm_weiter(self, vapid, gateway, google, creds):
        headers, body = push_request()
        status, _ = gateway.handle("POST", f"/fcm/{TOKEN}", headers, body)
        assert status == 201
        token_call, send_call = google.calls
        # Anmeldung mit vom Dienstkonto signiertem JWT (RS256)
        assertion = dict(x.split("=") for x in token_call["body"].decode().split("&"))["assertion"]
        head, claims, sig = assertion.split(".")
        creds["_key"].public_key().verify(
            base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)),
            f"{head}.{claims}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        assert send_call["url"].endswith("/projects/hubiplan-test/messages:send")
        assert send_call["headers"]["Authorization"] == "Bearer ya29.test"
        msg = google.messages[0]["message"]
        assert msg["token"] == TOKEN
        assert base64.b64decode(msg["data"]["b"]) == body
        assert msg["android"] == {"priority": "HIGH", "ttl": "86400s"}
        # Zugriffstoken wird wiederverwendet
        gateway.handle("POST", f"/fcm/{TOKEN}", *push_request(urgency="normal"))
        assert len([c for c in google.calls if c["url"].endswith("/token")]) == 1
        assert google.messages[1]["message"]["android"]["priority"] == "NORMAL"

    def test_unbekanntes_geraet(self, vapid, gateway, google):
        google.fcm_answer = (
            404,
            {"error": {"details": [{"errorCode": "UNREGISTERED"}]}},
        )
        assert gateway.handle("POST", f"/fcm/{TOKEN}", *push_request())[0] == 410

    def test_ablehnungen(self, vapid, gateway, google):
        path = f"/fcm/{TOKEN}"
        headers, body = push_request()
        assert gateway.handle("POST", path, headers, b"x" * (gw.MAX_BODY + 1))[0] == 413
        other = {**headers, "content-encoding": "aesgcm"}
        assert gateway.handle("POST", path, other, body)[0] == 415
        assert gateway.handle("POST", path, {**headers, "authorization": ""}, body)[0] == 401
        assert gateway.handle("POST", "/fcm/kurz", headers, body)[0] == 404
        assert gateway.handle("GET", path, headers, body)[0] == 405
        assert gateway.handle("POST", "/anderes", headers, body)[0] == 404
        assert google.messages == []

    def test_begrenzung_je_absender(self, vapid, gateway):
        statuses = [gateway.handle("POST", f"/fcm/{TOKEN}", *push_request())[0] for _ in range(4)]
        assert statuses == [201, 201, 201, 429]

    def test_ohne_dienstkonto(self, vapid):
        g = gw.Gateway(GATEWAY, None)
        assert g.handle("POST", f"/fcm/{TOKEN}", *push_request())[0] == 503
        assert g.handle("GET", "/health", {}, b"") == (200, {"status": "ok", "fcm": False})

    def test_wsgi(self, vapid, gateway, google):
        headers, body = push_request()
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": f"/fcm/{TOKEN}",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            **{"HTTP_" + k.upper().replace("-", "_"): v for k, v in headers.items()},
        }
        started = []
        out = gateway(environ, lambda status, hdrs: started.append(status))
        assert started == ["201 Created"] and json.loads(b"".join(out)) == {}

    def test_start_braucht_https(self, monkeypatch):
        monkeypatch.setenv("PUSH_GATEWAY_PUBLIC_URL", "http://push.example")
        with pytest.raises(RuntimeError):
            gw.create()


@pytest.mark.django_db
class TestGooglePushInHubiplan:
    def register(self, token, endpoint=ENDPOINT):
        r = Receiver()
        return app(token).put(
            f"{APP}devices/current/push/",
            {"kind": "fcm", "endpoint": endpoint, "p256dh": r.p256dh, "auth": b64(r.auth)},
            content_type=JSON,
        )

    def test_nur_ueber_eingestelltes_gateway(self, anna, settings, allow_endpoint):
        settings.PUSH_GATEWAY_URL = ""
        assert self.register(anna["token"]).status_code == 400
        settings.PUSH_GATEWAY_URL = GATEWAY + "/"
        assert self.register(anna["token"], "https://fremd.example/fcm/" + TOKEN).status_code == 400
        resp = self.register(anna["token"])
        assert resp.status_code == 200, resp.json()
        assert Device.objects.get().push_kind == "fcm"

    def test_instanz_nennt_gateway(self, settings):
        from django.test import Client

        settings.PUSH_GATEWAY_URL = GATEWAY
        ways = Client().get(f"{APP}instance/").json()["push"]
        assert {
            "kind": "fcm",
            "gateway": GATEWAY,
            "vapid_public_key": webpush.vapid_public_key(),
        } in ways

    def test_grosse_nachricht_passt_zu_fcm(self, anna, settings, allow_endpoint, push_outbox):
        from devices.push import send_to_user

        settings.PUSH_GATEWAY_URL = GATEWAY
        assert self.register(anna["token"]).status_code == 200
        text = "ä" * 1400  # gut 2800 Bytes: für FCM zu groß, für UnifiedPush nicht
        assert send_to_user(anna["user"].pk, {"t": "info", "text": text}) == 1
        body = push_outbox[0]["body"]
        assert len(body) <= gw.MAX_BODY
        assert push_outbox[0]["url"] == ENDPOINT


class TestBindung:
    """Härtung H5: Endpunkt an den VAPID-Schlüssel der Instanz gebunden, Grenzen, Auffüllen."""

    def test_nur_mit_dem_schluessel_der_instanz(self, vapid, gateway, google):
        kid = gw.key_id(vapid.vapid_public_key())
        path = f"/fcm/{TOKEN}/{kid}"
        endpoint = f"{GATEWAY}{path}"
        assert gateway.handle("POST", path, *push_request(endpoint=endpoint))[0] == 201
        # Fremde Instanz mit eigenem Schlüssel, die den Endpunkt kennt
        other = gw.Gateway(GATEWAY, gateway.fcm, rate=3)
        vapid.reset_cache()
        vapid.key_path().unlink()
        status, data = other.handle("POST", path, *push_request(endpoint=endpoint))
        assert status == 403 and data["reason"] == "anderer Absender"
        assert len(google.messages) == 1

    def test_ohne_kennung_abschaltbar(self, vapid, google, creds):
        data = {k: v for k, v in creds.items() if not k.startswith("_")}
        strict = gw.Gateway(GATEWAY, gw.Fcm(data), allow_unbound=False)
        assert strict.handle("POST", f"/fcm/{TOKEN}", *push_request())[0] == 404
        assert strict.handle("POST", f"/fcm/{TOKEN}/zzzz", *push_request())[0] == 404

    def test_grenze_je_geraet_und_ip(self, vapid, google, creds):
        data = {k: v for k, v in creds.items() if not k.startswith("_")}
        g = gw.Gateway(GATEWAY, gw.Fcm(data), rate=100, rate_token=2, rate_ip=3)
        path = f"/fcm/{TOKEN}"
        statuses = [g.handle("POST", path, *push_request(), "1.2.3.4")[0] for _ in range(3)]
        assert statuses == [201, 201, 429]
        other = "fcm-token_" + "y" * 40
        assert g.handle("POST", f"/fcm/{other}", *push_request(), "1.2.3.4")[0] == 429
        assert g.handle("POST", f"/fcm/{other}", *push_request(), "5.6.7.8")[0] == 201

    def test_gleiche_groesse_fuer_kurze_nachrichten(self):
        keys = _receiver_keys()
        short = webpush.encrypt(b'{"t":"sync"}', *keys, pad_to=webpush.padded_size(12, 2600))
        longer = b'{"t":"info","text":"' + b"x" * 500 + b'"}'
        medium = webpush.encrypt(longer, *keys, pad_to=webpush.padded_size(len(longer), 2600))
        assert len(short) == len(medium)
        big = b"x" * 2000
        full = webpush.encrypt(big, *keys, pad_to=webpush.padded_size(len(big), 2600))
        assert len(full) <= gw.MAX_BODY
