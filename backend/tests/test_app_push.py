"""Android-App, Schritt A4: Web-Push, Kurzmitteilung und Versandweg „App“ bei Rundschreiben."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import base64
import json
import os
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC
from django.core import mail as djmail

from audit.models import AuditEntry
from circulars.models import Circular, CircularRecipient
from devices import webpush
from devices.models import Device
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user
from .test_app_devices import APP, app, pair, pairing_code
from .test_m12_events import (  # noqa: F401  (Fixtures)
    JSON,
    cal,
    dept_role,
    member_with_access,
    zug,
    zug2,
)
from .test_rundschreiben import base, draft, preview, send, without_email

pytestmark = pytest.mark.django_db
ENDPOINT = "https://push.example.org/up/abc"


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _hmac(key: bytes, data: bytes) -> bytes:
    h = HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


class Receiver:
    """Gegenstelle wie in der App: Schlüsselpaar und auth, entschlüsselt nach RFC 8291."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)

    @property
    def p256dh(self) -> str:
        return b64(
            self.key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )

    def decrypt(self, body: bytes) -> bytes:
        salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
        assert rs == 4096
        as_public = body[21 : 21 + idlen]
        ciphertext = body[21 + idlen :]
        sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
        shared = self.key.exchange(ec.ECDH(), sender)
        ua_public = unb64(self.p256dh)
        prk_key = _hmac(self.auth, shared)
        ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
        prk = _hmac(salt, ikm)
        cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
        nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
        plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
        # Füllbytes (RFC 8188): Nullen nach dem Trennbyte 0x02
        plain = plain.rstrip(b"\x00")
        assert plain.endswith(b"\x02")
        return plain[:-1]


class PushOutbox(list):
    """Gesendete Pushes; ``answer`` stellt die Antwort des Dienstes ein."""

    def __init__(self):
        super().__init__()
        self.answer = {"status": 201}


@pytest.fixture
def push_outbox(monkeypatch):
    """Push-Dienst ersetzen: hält fest, was an welchen Endpunkt ging."""
    sent = PushOutbox()

    def fake_post(url, headers, body):
        sent.append({"url": url, "headers": headers, "body": body})
        return sent.answer["status"]

    monkeypatch.setattr(webpush, "_post", fake_post)
    return sent


@pytest.fixture
def allow_endpoint(monkeypatch):
    monkeypatch.setattr(webpush, "check_endpoint", lambda url: None)


def register(token: str, receiver: Receiver, endpoint: str = ENDPOINT):
    return app(token).put(
        f"{APP}devices/current/push/",
        {
            "kind": "unifiedpush",
            "endpoint": endpoint,
            "p256dh": receiver.p256dh,
            "auth": b64(receiver.auth),
        },
        content_type=JSON,
    )


@pytest.fixture
def anna(cal, api):
    """Mitglied mit App und Push."""
    m, user, access = member_with_access(cal["a"], "Anna")
    resp = pair(pairing_code(api(user)))
    assert resp.status_code == 201, resp.json()
    return {"membership": m, "user": user, "access": access, "token": resp.json()["token"]}


class TestWebPush:
    def test_verschluesselt_nach_rfc8291(self):
        r = Receiver()
        body = webpush.encrypt(b'{"t":"x"}', r.p256dh, b64(r.auth))
        assert r.decrypt(body) == b'{"t":"x"}'
        # Jede Nachricht mit neuem Salz und Schlüssel
        assert webpush.encrypt(b"a", r.p256dh, b64(r.auth))[:16] != body[:16]

    def test_vapid_unterschrift_pruefbar(self, settings):
        settings.FRONTEND_URL = "https://verein.example.org"
        header = webpush.vapid_header(ENDPOINT, now=1_000_000)
        assert header.startswith("vapid t=")
        token, key = header[len("vapid t=") :].split(", k=")
        head, claims, sig = token.split(".")
        data = json.loads(unb64(claims))
        assert data == {
            "aud": "https://push.example.org",
            "exp": 1_000_000 + 12 * 3600,
            "sub": "https://verein.example.org",
        }
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(key))
        raw = unb64(sig)
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
        # Schlüssel bleibt (Datei im privaten Speicher)
        webpush.reset_cache()
        assert webpush.vapid_public_key() == key

    def test_zu_gross_nur_wecksignal(self, push_outbox):
        r = Receiver()
        webpush.send(ENDPOINT, r.p256dh, b64(r.auth), {"text": "x" * 5000})
        assert json.loads(r.decrypt(push_outbox[0]["body"])) == {"v": 1, "t": "sync"}
        assert push_outbox[0]["headers"]["Content-Encoding"] == "aes128gcm"

    def test_keine_internen_adressen(self):
        for url in ("http://push.example.org/x", "https://127.0.0.1/x", "https://10.0.0.1/x"):
            with pytest.raises(webpush.PushError):
                webpush.check_endpoint(url)


class TestAnmeldungPush:
    def test_instanz_nennt_vapid_schluessel(self):
        from django.test import Client

        ways = Client().get(f"{APP}instance/").json()["push"]
        assert ways[0]["kind"] == "unifiedpush"
        assert len(unb64(ways[0]["vapid_public_key"])) == 65

    def test_endpunkt_melden_und_abmelden(self, anna, allow_endpoint):
        r = Receiver()
        resp = register(anna["token"], r)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["push"] == "unifiedpush"
        device = Device.objects.get()
        assert device.push_endpoint == ENDPOINT and device.push_auth == b64(r.auth)
        resp = app(anna["token"]).delete(f"{APP}devices/current/push/")
        assert resp.json()["push"] == "none"
        assert Device.objects.get().push_endpoint == ""

    def test_ungueltige_angaben(self, anna):
        r = Receiver()
        assert register(anna["token"], r, "https://127.0.0.1/x").status_code == 400
        bad = app(anna["token"]).put(
            f"{APP}devices/current/push/",
            {"kind": "unifiedpush", "endpoint": ENDPOINT, "p256dh": "abc", "auth": "abc"},
            content_type=JSON,
        )
        assert bad.status_code == 400
        assert set(bad.json()) >= {"p256dh", "auth"}

    def test_nur_mit_geraeteschluessel(self, anna, api):
        resp = api(anna["user"]).put(f"{APP}devices/current/push/", {}, content_type=JSON)
        assert resp.status_code in (401, 403)


class TestRundschreibenPerApp:
    @pytest.fixture
    def setup(self, cal, anna, allow_endpoint, board_a, api):
        receiver = Receiver()
        assert register(anna["token"], receiver).status_code == 200
        bernd = make_member(cal["a"], "Bernd", "Berg")
        return {"receiver": receiver, "bernd": bernd, "c": api(board_a), "url": base(cal["a"])}

    def test_vorschau_zaehlt_app(self, setup):
        c, url = setup["c"], setup["url"]
        data = draft(c, url)
        assert data["via_app"] is True
        result = preview(c, url, data["id"])
        rows = {i["first_name"]: i for i in result["items"]}
        assert rows["Anna"]["channel"] == "app" and rows["Bernd"]["channel"] == "mail"
        assert result["counts"]["app"] == 1
        # ohne App: alle per Mail
        c.patch(f"{url}{data['id']}/", {"via_app": False}, content_type=JSON)
        rows = {i["first_name"]: i for i in preview(c, url, data["id"])["items"]}
        assert rows["Anna"]["channel"] == "mail"

    def test_versand_per_push(
        self, setup, anna, push_outbox, django_capture_on_commit_callbacks, settings
    ):
        c, url = setup["c"], setup["url"]
        data = draft(c, url, body="Hallo {Vorname},\n\n**Antreten** um 18 Uhr.")
        result = send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        assert result["sent"]["app"] == 1
        assert len(push_outbox) == 1 and push_outbox[0]["url"] == ENDPOINT
        msg = json.loads(setup["receiver"].decrypt(push_outbox[0]["body"]))
        assert msg["t"] == "circular" and msg["id"] == data["id"]
        assert msg["access"] == anna["access"].pk
        assert msg["title"] == "Einladung" and msg["text"] == "Hallo Anna,\n\nAntreten um 18 Uhr."
        assert msg["from"] == "Verein A"
        row = CircularRecipient.objects.get(membership=anna["membership"])
        assert row.channel == "app" and row.status == "sent"
        # keine Mail an Anna, aber an Bernd
        assert [m.to for m in djmail.outbox if "Einladung" in m.subject] == [["bernd@example.org"]]
        # im Mitgliederbereich sichtbar, mit Weg „app“
        items = app(anna["token"]).get(f"/api/portal/{anna['access'].pk}/circulars/").json()
        assert items[0]["channel"] == "app"

    def test_app_und_zusaetzlich_mail(
        self, setup, anna, push_outbox, django_capture_on_commit_callbacks, settings
    ):
        c, url = setup["c"], setup["url"]
        data = draft(c, url)
        assert data["also_mail"] is False
        c.patch(f"{url}{data['id']}/", {"also_mail": True}, content_type=JSON)
        rows = {i["first_name"]: i for i in preview(c, url, data["id"])["items"]}
        assert rows["Anna"]["channel"] == "app"
        assert rows["Anna"]["note"] == "per App und E-Mail"
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        assert len(push_outbox) == 1
        row = CircularRecipient.objects.get(membership=anna["membership"])
        assert row.channel == "app" and row.status == "sent" and row.error == ""
        to = sorted(m.to[0] for m in djmail.outbox if "Einladung" in m.subject)
        assert to == ["anna@example.org", "bernd@example.org"]

    def test_push_scheitert_dann_mail(
        self, setup, anna, push_outbox, django_capture_on_commit_callbacks, settings
    ):
        push_outbox.answer["status"] = 410
        c, url = setup["c"], setup["url"]
        data = draft(c, url)
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        row = CircularRecipient.objects.get(membership=anna["membership"])
        assert row.channel == "mail" and row.status == "sent"
        assert any(m.to == ["anna@example.org"] for m in djmail.outbox)
        # Endpunkt gibt es nicht mehr: Gerät wieder nur mit Abruf
        assert Device.objects.get().push_kind == "none"

    def test_kurzmitteilung(
        self, setup, anna, push_outbox, django_capture_on_commit_callbacks, settings
    ):
        c, url = setup["c"], setup["url"]
        without_email(setup["bernd"])
        resp = c.post(
            url, {"kind": "short", "subject": "Antreten", "body": "x" * 501}, content_type=JSON
        )
        assert resp.status_code == 400 and "body" in resp.json()
        data = draft(c, url, kind="short", subject="Antreten", body="Heute 18 Uhr am Zelt")
        from django.core.files.uploadedfile import SimpleUploadedFile

        up = c.post(
            f"{url}{data['id']}/attachments/",
            {"file": SimpleUploadedFile("a.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert up.status_code == 400
        rows = {i["first_name"]: i for i in preview(c, url, data["id"])["items"]}
        # Bernd ohne App und Mail: kein Brief, nur im Mitgliederbereich
        assert rows["Bernd"]["channel"] == "portal"
        result = send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        assert result["sent"] == {"app": 1, "mail": 0, "letter": 0, "portal": 1}
        assert CircularRecipient.objects.get(membership=setup["bernd"]).status == "portal"
        assert Circular.objects.get(pk=data["id"]).status == "sent"

    def test_hoechstens_zehn_kurzmitteilungen_am_tag(
        self, setup, push_outbox, django_capture_on_commit_callbacks, settings
    ):
        c, url = setup["c"], setup["url"]
        for n in range(10):
            data = draft(c, url, kind="short", subject=f"Nr. {n}", body="kurz")
            send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        data = draft(c, url, kind="short", subject="zu viel", body="kurz")
        resp = c.post(f"{url}{data['id']}/send/", content_type=JSON)
        assert resp.status_code == 400
        # Andere Arten zählen nicht mit
        data = draft(c, url)
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)

    def test_widerrufenes_geraet_bekommt_nichts(self, setup, anna, push_outbox):
        Device.objects.update(revoked_at="2026-01-01T00:00:00Z")
        c, url = setup["c"], setup["url"]
        data = draft(c, url)
        rows = {i["first_name"]: i for i in preview(c, url, data["id"])["items"]}
        assert rows["Anna"]["channel"] == "mail"


class TestSendenAusDerApp:
    @pytest.fixture
    def vorstand(self, cal, api):
        """Vorstand mit eigener Mitgliedschaft und App."""
        m, user, access = member_with_access(cal["a"], "Vera")
        give_role(user, cal["a"])
        resp = pair(pairing_code(api(user)))
        assert resp.status_code == 201, resp.json()
        return {"user": user, "token": resp.json()["token"], "membership": m}

    def test_einheiten_und_vorschau(self, cal, vorstand, anna, allow_endpoint):
        register(anna["token"], Receiver())
        make_member(cal["a"], "Bernd", "Berg")
        data = app(vorstand["token"]).get(f"{APP}send/").json()
        assert [s["key"] for s in data["senders"]] == [f"org-{cal['a'].pk}"]
        assert data["max_body"] == 500
        resp = app(vorstand["token"]).post(
            f"{APP}send/org/{cal['a'].pk}/",
            {"subject": "Antreten", "body": "Heute 18 Uhr am Zelt"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        counts = resp.json()["counts"]
        assert counts["app"] == 1 and counts["mail"] == 2  # Anna per App; Bernd und Vera per Mail
        assert not Circular.objects.exists()

    def test_senden(
        self,
        cal,
        vorstand,
        anna,
        allow_endpoint,
        push_outbox,
        django_capture_on_commit_callbacks,
        settings,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        receiver = Receiver()
        register(anna["token"], receiver)
        with django_capture_on_commit_callbacks(execute=True):
            resp = app(vorstand["token"]).post(
                f"{APP}send/org/{cal['a'].pk}/",
                {"subject": "Antreten", "body": "Heute 18 Uhr am Zelt", "confirm": True},
                content_type=JSON,
            )
        assert resp.status_code == 201, resp.json()
        circular = Circular.objects.get()
        assert circular.kind == "short" and circular.status == "sent"
        assert circular.sent_by == vorstand["user"]
        msg = json.loads(receiver.decrypt(push_outbox[0]["body"]))
        assert msg["title"] == "Antreten" and msg["kind"] == "short"
        assert AuditEntry.objects.filter(organization=cal["a"]).exists()

    def test_zug_nur_eigene_mitglieder(self, cal, zug, zug2, api):
        leader = make_member(cal["a"], "Leo", "Leiter", departments=[zug])
        make_member(cal["a"], "Gerd", "Grenadier", departments=[zug2])
        user = make_user("leo@example.org")
        PortalAccess.objects.create(organization=cal["a"], membership=leader, user=user)
        dept_role(zug, leader, ["dept.circulars.send"])
        token = pair(pairing_code(api(user))).json()["token"]
        senders = app(token).get(f"{APP}send/").json()["senders"]
        assert [s["key"] for s in senders] == [f"dept-{zug.pk}"]
        resp = app(token).post(
            f"{APP}send/dept/{zug.pk}/", {"subject": "Zug", "body": "Probe"}, content_type=JSON
        )
        assert resp.json()["counts"]["total"] == 1  # nur Leo selbst, nicht Gerd
        assert (
            app(token)
            .post(f"{APP}send/dept/{zug2.pk}/", {"subject": "x", "body": "y"}, content_type=JSON)
            .status_code
            == 404
        )
        assert (
            app(token)
            .post(f"{APP}send/org/{cal['a'].pk}/", {"subject": "x", "body": "y"}, content_type=JSON)
            .status_code
            == 404
        )

    def test_mitglied_ohne_recht(self, cal, anna):
        assert app(anna["token"]).get(f"{APP}send/").json()["senders"] == []
        resp = app(anna["token"]).post(
            f"{APP}send/org/{cal['a'].pk}/", {"subject": "x", "body": "y"}, content_type=JSON
        )
        assert resp.status_code == 404

    def test_zu_lang(self, cal, vorstand):
        resp = app(vorstand["token"]).post(
            f"{APP}send/org/{cal['a'].pk}/", {"subject": "x", "body": "y" * 501}, content_type=JSON
        )
        assert resp.status_code == 400
