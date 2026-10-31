"""Härtung H7: Schlüsselpaare der App, Erneuerung des Geräteschlüssels, unterschriebene
Vorstandsanfragen, Erkennung von Kopien (erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import base64
import datetime
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from devices import devicekey
from devices.models import Device

from .factories import PASSWORD, give_role
from .test_app_devices import APP, app, pair, pairing_code
from .test_app_verwaltung import fresh_code
from .test_m12_events import JSON, cal, member_with_access  # noqa: F401

pytestmark = pytest.mark.django_db
ADMIN = f"{APP}admin/"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def public(key: ec.EllipticCurvePrivateKey) -> str:
    return b64(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )


def sign(key: ec.EllipticCurvePrivateKey, message: bytes) -> str:
    return b64(key.sign(message, ec.ECDSA(hashes.SHA256())))


@pytest.fixture(autouse=True)
def _frisch():
    cache.clear()


@pytest.fixture
def phone(cal, api):
    """Mitglied mit App und Geräteschlüsselpaar."""
    _, user, _ = member_with_access(cal["a"], "Gerda")
    key = ec.generate_private_key(ec.SECP256R1())
    code = pairing_code(api(user))
    resp = Client().post(
        f"{APP}pair/",
        {"code": code, "name": "Pixel 8", "app_version": "17", "device_key": public(key)},
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    data = resp.json()
    assert data["device"]["key"] is True and data["device"]["renew_due"] is False
    return {"user": user, "key": key, "token": data["token"], "id": data["device"]["id"]}


def renew(token: str, key, device_id: int):
    c = app(token)
    resp = c.post(f"{APP}devices/current/renew/")
    assert resp.status_code == 201, resp.json()
    challenge = resp.json()["challenge"]
    sig = sign(key, devicekey.renew_message(device_id, challenge))
    return c.post(
        f"{APP}devices/current/renew/",
        {"challenge": challenge, "signature": sig},
        content_type=JSON,
    )


def age(device_id: int, days: int) -> None:
    Device.objects.filter(pk=device_id).update(
        token_issued_at=timezone.now() - datetime.timedelta(days=days)
    )


class TestErneuern:
    def test_neuer_schluessel_und_kurze_ueberlappung(
        self, phone, django_capture_on_commit_callbacks
    ):
        old = phone["token"]
        resp = renew(old, phone["key"], phone["id"])
        assert resp.status_code == 201, resp.json()
        new = resp.json()["token"]
        assert new != old
        # Vor der ersten Nutzung des neuen gilt der alte weiter (Antwort könnte verloren sein)
        assert app(old).get(f"{APP}me/").status_code == 200
        assert app(new).get(f"{APP}me/").status_code == 200
        # Laufende Anfragen mit dem alten gehen noch kurz
        assert app(old).get(f"{APP}me/").status_code == 200
        Device.objects.filter(pk=phone["id"]).update(
            previous_until=timezone.now() - datetime.timedelta(seconds=1)
        )
        mail.outbox.clear()
        # Danach: Kopie erkannt, Gerät gesperrt, Mail
        with django_capture_on_commit_callbacks(execute=True):
            assert app(old).get(f"{APP}me/").status_code == 401
        device = Device.objects.get(pk=phone["id"])
        assert device.revoked_at is not None and "Kopie" in device.revoked_reason
        assert app(new).get(f"{APP}me/").status_code == 401
        assert [m.subject for m in mail.outbox] == ["Gerät wegen kopiertem Schlüssel abgemeldet"]

    def test_ausgemusterter_schluessel_ist_kopie(self, phone):
        first = phone["token"]
        second = renew(first, phone["key"], phone["id"]).json()["token"]
        assert app(second).get(f"{APP}me/").status_code == 200
        third = renew(second, phone["key"], phone["id"]).json()["token"]
        assert app(third).get(f"{APP}me/").status_code == 200
        assert app(first).get(f"{APP}me/").status_code == 401
        assert Device.objects.get(pk=phone["id"]).revoked_at is not None

    def test_verlorene_antwort_erneut_mit_altem(self, phone):
        old = phone["token"]
        lost = renew(old, phone["key"], phone["id"]).json()["token"]
        again = renew(old, phone["key"], phone["id"])
        assert again.status_code == 201, again.json()
        new = again.json()["token"]
        assert app(new).get(f"{APP}me/").status_code == 200
        # Der nie genutzte Schlüssel gilt nicht mehr, ist aber keine Kopie
        assert app(lost).get(f"{APP}me/").status_code == 401
        assert Device.objects.get(pk=phone["id"]).revoked_at is None

    def test_falsche_unterschrift(self, phone):
        other = ec.generate_private_key(ec.SECP256R1())
        resp = renew(phone["token"], other, phone["id"])
        assert resp.status_code == 403
        assert app(phone["token"]).get(f"{APP}me/").status_code == 200

    def test_aufgabe_nur_einmal(self, phone):
        c = app(phone["token"])
        challenge = c.post(f"{APP}devices/current/renew/").json()["challenge"]
        sig = sign(phone["key"], devicekey.renew_message(phone["id"], challenge))
        body = {"challenge": challenge, "signature": sig}
        assert c.post(f"{APP}devices/current/renew/", body, content_type=JSON).status_code == 201
        assert c.post(f"{APP}devices/current/renew/", body, content_type=JSON).status_code == 400

    def test_nach_7_tagen_faellig_nach_14_nur_noch_erneuern(self, phone):
        age(phone["id"], 8)
        me = app(phone["token"]).get(f"{APP}me/")
        assert me.status_code == 200 and me.json()["device"]["renew_due"] is True
        age(phone["id"], 15)
        resp = app(phone["token"]).get(f"{APP}me/")
        assert resp.status_code == 401 and resp.json()["code"] == "device_renew"
        new = renew(phone["token"], phone["key"], phone["id"])
        assert new.status_code == 201
        assert app(new.json()["token"]).get(f"{APP}me/").status_code == 200

    def test_aeltere_app_ohne_schluesselpaar(self, cal, api):
        _, user, _ = member_with_access(cal["a"], "Otto")
        token = pair(pairing_code(api(user))).json()["token"]
        device = Device.objects.get(user=user)
        age(device.pk, 59)
        assert app(token).get(f"{APP}me/").status_code == 200
        assert app(token).post(f"{APP}devices/current/renew/").status_code == 400
        # Fachfrage 3 (31.10.b): ohne Schlüsselpaar nach 60 Tagen neu verbinden
        age(device.pk, 61)
        assert app(token).get(f"{APP}me/").status_code == 401

    def test_verwaltung_nur_mit_schluesselpaar(self, cal, api):
        from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret

        _, user, _ = member_with_access(cal["a"], "Otto")
        give_role(user, cal["a"], ["members.view"], name="Schriftführung")
        secret = generate_totp_secret()
        TOTP.activate(user, secret)
        token = pair(pairing_code(api(user))).json()["token"]
        resp = Client(HTTP_AUTHORIZATION=f"Bearer {token}").post(
            f"{ADMIN}unlock/",
            {"password": PASSWORD, "code": fresh_code(secret)},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "aktualisieren" in resp.json()["detail"]
        # Alte Freischaltung ohne Schlüsselpaar gilt nicht mehr
        device = Device.objects.get(user=user)
        from devices.models import hash_token

        Device.objects.filter(pk=device.pk).update(
            admin_token_hash=hash_token("hpa_alt"),
            admin_until=timezone.now() + datetime.timedelta(days=1),
        )
        old = Client(HTTP_AUTHORIZATION="Bearer hpa_alt", HTTP_X_HUBIPLAN_DEVICE=token)
        resp = old.get(f"{ADMIN}u/{cal['a'].pk}/tasks/")
        assert resp.status_code == 401 and "gesperrt" in resp.json()["detail"]

    def test_schluesselpaar_nachmelden_nur_einmal(self, cal, api):
        _, user, _ = member_with_access(cal["a"], "Otto")
        token = pair(pairing_code(api(user))).json()["token"]
        key = public(ec.generate_private_key(ec.SECP256R1()))
        url = f"{APP}devices/current/key/"
        resp = app(token).put(url, {"device_key": key}, content_type=JSON)
        assert resp.status_code == 200 and resp.json()["key"] is True
        assert app(token).put(url, {"device_key": key}, content_type=JSON).status_code == 200
        other = public(ec.generate_private_key(ec.SECP256R1()))
        assert app(token).put(url, {"device_key": other}, content_type=JSON).status_code == 409
        assert app(token).put(url, {"device_key": "kaputt"}, content_type=JSON).status_code == 400


@pytest.fixture
def board(cal, api):
    from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret

    m, user, _ = member_with_access(cal["a"], "Vera")
    give_role(user, cal["a"], ["members.view", "members.edit"], name="Schriftführung")
    secret = generate_totp_secret()
    TOTP.activate(user, secret)
    device_key = ec.generate_private_key(ec.SECP256R1())
    admin_key = ec.generate_private_key(ec.SECP256R1())
    resp = Client().post(
        f"{APP}pair/",
        {
            "code": pairing_code(api(user)),
            "name": "Pixel 8",
            "device_key": public(device_key),
        },
        content_type=JSON,
    )
    token = resp.json()["token"]
    unlocked = app(token).post(
        f"{ADMIN}unlock/",
        {"password": PASSWORD, "code": fresh_code(secret), "admin_key": public(admin_key)},
        content_type=JSON,
    )
    assert unlocked.status_code == 201, unlocked.json()
    assert unlocked.json()["signed"] is True
    return {
        "org": cal["a"],
        "device": token,
        "admin": unlocked.json()["token"],
        "key": admin_key,
    }


def signed(board, method: str, path: str, body: bytes = b"", *, key=None, ts=None, sig=None):
    ts = str(int(ts if ts is not None else time.time()))
    signature = sig or sign(key or board["key"], devicekey.admin_message(method, path, ts, body))
    c = Client(
        HTTP_AUTHORIZATION=f"Bearer {board['admin']}",
        HTTP_X_HUBIPLAN_DEVICE=board["device"],
        HTTP_X_HUBIPLAN_TIME=ts,
        HTTP_X_HUBIPLAN_SIGNATURE=signature,
    )
    return c.generic(method, path, body, content_type=JSON), signature


class TestVorstandsanfragen:
    def path(self, board, query=""):
        return f"{ADMIN}u/{board['org'].pk}/tasks/{query}"

    def test_unterschrieben_geht(self, board):
        resp, _ = signed(board, "GET", self.path(board))
        assert resp.status_code == 200, resp.json()

    def test_mit_abfrage_und_umlaut(self, board):
        resp, _ = signed(board, "GET", self.path(board, "?q=M%C3%BCller&x=1"))
        assert resp.status_code == 200, resp.json()

    def test_ohne_unterschrift_wertlos(self, board):
        c = Client(
            HTTP_AUTHORIZATION=f"Bearer {board['admin']}", HTTP_X_HUBIPLAN_DEVICE=board["device"]
        )
        resp = c.get(self.path(board))
        assert resp.status_code == 401 and resp.json()["code"] == "admin_signature"

    def test_fremder_schluessel(self, board):
        other = ec.generate_private_key(ec.SECP256R1())
        resp, _ = signed(board, "GET", self.path(board), key=other)
        assert resp.status_code == 401

    def test_alte_zeit(self, board):
        resp, _ = signed(board, "GET", self.path(board), ts=time.time() - 3600)
        assert resp.status_code == 401

    def test_wiederholung_abgelehnt(self, board):
        ts = time.time()
        first, sig = signed(board, "GET", self.path(board), ts=ts)
        assert first.status_code == 200
        again, _ = signed(board, "GET", self.path(board), ts=ts, sig=sig)
        assert again.status_code == 401

    def test_wiederholung_in_anderer_schreibweise(self, board):
        # Gesamtaudit 30.10. (BSEC-02): base64 mit Füllzeichen und (r, n−s) sind dieselbe
        # Unterschrift und gelten nicht als neue Anfrage
        from cryptography.hazmat.primitives.asymmetric.utils import (
            decode_dss_signature,
            encode_dss_signature,
        )

        ts = time.time()
        first, sig = signed(board, "GET", self.path(board), ts=ts)
        assert first.status_code == 200
        raw = devicekey.unb64(sig)
        padded = base64.urlsafe_b64encode(raw).decode()
        if padded != sig:  # bei Länge durch 3 teilbar gibt es keine Füllzeichen
            again, _ = signed(board, "GET", self.path(board), ts=ts, sig=padded)
            assert again.status_code == 401
        r, s_ = decode_dss_signature(raw)
        flipped = b64(encode_dss_signature(r, devicekey.P256_ORDER - s_))
        again, _ = signed(board, "GET", self.path(board), ts=ts, sig=flipped)
        assert again.status_code == 401

    def test_format_2_mit_kennung(self, board):
        path = self.path(board)
        ts = str(int(time.time()))

        def send(nonce, idem, signed_idem=None):
            message = devicekey.admin_message(
                "GET", path, ts, b"", nonce=nonce, idempotency=signed_idem or idem
            )
            c = Client(
                HTTP_AUTHORIZATION=f"Bearer {board['admin']}",
                HTTP_X_HUBIPLAN_DEVICE=board["device"],
                HTTP_X_HUBIPLAN_TIME=ts,
                HTTP_X_HUBIPLAN_SIGNATURE=sign(board["key"], message),
                HTTP_X_HUBIPLAN_NONCE=nonce,
                HTTP_IDEMPOTENCY_KEY=idem,
            )
            return c.get(path)

        first = send("a" * 22, "k1")
        assert first.status_code == 200
        assert first["X-Hubiplan-Signature-Format"] == "2"
        # Gleiche Kennung, neue Unterschrift: trotzdem Wiederholung
        assert send("a" * 22, "k1").status_code == 401
        # Idempotency-Key ist mit unterschrieben
        assert send("b" * 22, "k2", signed_idem="k3").status_code == 401
        assert send("c" * 22, "k2").status_code == 200
        assert send("kurz", "k4").status_code == 401

    def test_anderer_pfad_oder_inhalt(self, board):
        ts = str(int(time.time()))
        sig = sign(board["key"], devicekey.admin_message("GET", self.path(board), ts, b""))
        resp, _ = signed(board, "GET", self.path(board, "?x=1"), sig=sig, ts=int(ts))
        assert resp.status_code == 401
        body = json.dumps({"a": 1}).encode()
        sig = sign(board["key"], devicekey.admin_message("POST", self.path(board), ts, b"{}"))
        resp, _ = signed(board, "POST", self.path(board), body, sig=sig, ts=int(ts))
        assert resp.status_code == 401

    def test_sperren_loescht_schluesselpaar(self, board):
        assert app(board["device"]).delete(f"{ADMIN}unlock/").status_code == 200
        device = Device.objects.get(admin_key="", device_key__gt="")
        assert device.admin_token_hash == ""
