# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Härtung H6: Schlüsselwechsel der Instanz, geplant und im Notfall (erfundene Daten)."""

import datetime
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from django.core import mail
from django.utils import timezone

from organizations.models import Organization
from peering import crypto, identity, keys, services, transport
from peering.models import Message, Peer

from .factories import give_role, make_user
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def alarms(monkeypatch):
    sent = []
    monkeypatch.setattr("core.alarm.send_alert", lambda subject, lines: sent.append(subject))
    monkeypatch.setattr("peering.keys.send_alert", lambda subject, lines: sent.append(subject))
    return sent


@pytest.fixture
def coupled(net, world):
    lower, upper = couple(net, world)
    with net.on(VEREIN):
        verein_id = identity.identity().instance_id
    with net.on(VERBAND):
        verband_id = identity.identity().instance_id
    return {
        "lower": lower,
        "upper": upper,
        # Sicht des Dachverbands auf den Verein und umgekehrt
        "verein_at_verband": Peer.objects.get(instance_id=verein_id),
        "verband_at_verein": Peer.objects.get(instance_id=verband_id),
    }


def _raw_pub(key) -> str:
    return identity.b64(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def deliver_ok(net, base, coupling) -> bool:
    """Neuen Stand senden; True, wenn er angekommen ist."""
    with net.on(base):
        services.enqueue(coupling, "coupling.config", {"packets": coupling.packets or {}})
        services.deliver(coupling.pk)
    return not Message.objects.filter(
        coupling=coupling, direction=Message.Direction.OUT, state=Message.State.QUEUED
    ).exists()


def _key_file(net, base) -> dict:
    return json.loads(open(net.instances[base]).read())


def _write_key_file(net, base, data) -> None:
    with open(net.instances[base], "w") as fh:
        json.dump(data, fh)
    identity.reset_cache()


class TestGeplant:
    def test_wechsel_wird_uebernommen_und_alter_gilt_weiter(self, net, world, coupled, alarms):
        with net.on(VEREIN):
            old = identity.identity()
            mail.outbox.clear()
            new = keys.rotate(None)
        assert new.fingerprint != old.fingerprint
        assert new.previous_public_key == old.public_key
        peer = coupled["verein_at_verband"]
        peer.refresh_from_db()
        assert peer.public_key == new.public_key and peer.fingerprint == new.fingerprint
        assert peer.valid_previous_key == old.public_key
        # Wir wissen, dass der Dachverband den neuen Schlüssel kennt
        coupled["verband_at_verein"].refresh_from_db()
        assert coupled["verband_at_verein"].our_fingerprint == new.fingerprint
        assert "Verbund: Instanzschlüssel gewechselt" in alarms
        assert any("hat die Schlüssel gewechselt" in m.subject for m in mail.outbox)
        # Austausch läuft in beide Richtungen weiter
        assert deliver_ok(net, VEREIN, coupled["lower"])
        assert deliver_ok(net, VERBAND, coupled["upper"])

    def test_paket_an_alten_schluessel_in_der_uebergangszeit(self, net, world, coupled):
        with net.on(VEREIN):
            old = identity.identity()
            keys.rotate(None)
            ident = identity.identity()
            sealed = crypto.seal(
                {"x": 1},
                sender="a",
                recipient=ident.instance_id,
                recipient_enc_key=old.enc_public_key,
            )
            assert crypto.open_sealed(sealed, ident) == {"x": 1}

    def test_gegenstelle_ohne_ankuendigung_bleibt_in_der_uebergangszeit_erreichbar(
        self, net, world, coupled
    ):
        # Dachverband nicht erreichbar: Ankündigung geht verloren
        net.down.add(VERBAND)
        with net.on(VEREIN):
            keys.rotate(None)
        net.down.clear()
        peer = coupled["verein_at_verband"]
        peer.refresh_from_db()
        with net.on(VEREIN):
            assert peer.public_key != identity.identity().public_key
        # Zweite Unterschrift mit dem alten Schlüssel: Pakete kommen trotzdem an
        assert deliver_ok(net, VEREIN, coupled["lower"])
        # Täglicher Lauf holt die Ankündigung nach
        with net.on(VEREIN):
            keys.daily()
            current = identity.identity().public_key
        peer.refresh_from_db()
        assert peer.public_key == current

    def test_alter_schluessel_wird_nach_30_tagen_geloescht(self, net, world, coupled):
        with net.on(VEREIN):
            keys.rotate(None)
            data = _key_file(net, VEREIN)
            data["previous"]["until"] = (timezone.now() - datetime.timedelta(days=1)).isoformat()
            _write_key_file(net, VEREIN, data)
            ident = identity.identity()
            assert not ident.has_previous and len(ident.decryption_keys) == 1
            assert identity.drop_expired()
            assert "previous" not in _key_file(net, VEREIN)

    def test_jaehrlicher_wechsel(self, net, world, coupled):
        with net.on(VEREIN):
            before = identity.identity().fingerprint
            data = _key_file(net, VEREIN)
            data["created"] = (timezone.now() - datetime.timedelta(days=400)).isoformat()
            _write_key_file(net, VEREIN, data)
            keys.daily()
            assert identity.identity().fingerprint != before
            keys.daily()  # danach nicht gleich wieder
            assert identity.identity().rotated_at


class TestNotfall:
    def test_erst_nach_bestaetigung_des_fingerabdrucks(self, net, world, coupled, alarms):
        with net.on(VEREIN):
            new = keys.rotate(None, emergency=True)
            assert not new.has_previous  # alter Schlüssel unterschreibt keine Pakete mehr
        peer = coupled["verein_at_verband"]
        peer.refresh_from_db()
        assert peer.pending_keys["fingerprint"] == new.fingerprint
        assert peer.public_key != new.public_key
        assert "Verbund: Notfallwechsel einer Gegenstelle" in alarms
        # Bis zur Bestätigung kommt nichts an
        assert not deliver_ok(net, VEREIN, coupled["lower"])
        upper = coupled["upper"]
        base = f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/"
        with net.on(VERBAND):
            c = api(world["fed_board"])
            assert c.get(base).json()["keys"]["fingerprint"] == new.fingerprint
            # Frage 11: die Einheit sieht den Wechsel, bestätigt aber nicht selbst
            denied = c.post(
                f"{base}keys-confirm/", {"fingerprint": new.fingerprint}, content_type=JSON
            )
            assert denied.status_code == 403
            admin = make_user("plattform@verband.example")
            give_role(admin, Organization.platform())
            p = api(admin)
            pending = p.get("/api/platform/peering/").json()["pending_keys"]
            assert [x["fingerprint"] for x in pending] == [new.fingerprint]
            assert pending[0]["units"] == [world["fed"].name]
            url = f"/api/platform/peering/peers/{pending[0]['id']}/keys/"
            wrong = p.post(url, {"action": "confirm", "fingerprint": "AAAA"}, content_type=JSON)
            assert wrong.status_code == 400
            mail.outbox.clear()
            resp = p.post(
                url, {"action": "confirm", "fingerprint": new.fingerprint}, content_type=JSON
            )
            assert resp.status_code == 200, resp.json()
            assert resp.json()["pending_keys"] == []
            assert c.get(base).json()["keys"] is None
            assert any("bestätigt" in m.subject for m in mail.outbox)
        peer.refresh_from_db()
        assert peer.public_key == new.public_key and not peer.valid_previous_key
        # Der Verein versucht es nach seiner Wartezeit erneut
        Message.objects.filter(coupling=coupled["lower"]).update(next_try_at=timezone.now())
        with net.on(VEREIN):
            services.deliver(coupled["lower"].pk)
        assert not Message.objects.filter(
            coupling=coupled["lower"], state=Message.State.QUEUED
        ).exists()
        assert deliver_ok(net, VERBAND, upper)

    def test_ablehnen_behaelt_alte_schluessel(self, net, world, coupled):
        peer = coupled["verein_at_verband"]
        before = peer.public_key
        with net.on(VEREIN):
            keys.rotate(None, emergency=True)
        with net.on(VERBAND):
            admin = make_user("plattform@verband.example")
            give_role(admin, Organization.platform())
            peer_id = Peer.objects.get(pk=peer.pk).pk
            resp = api(admin).post(
                f"/api/platform/peering/peers/{peer_id}/keys/",
                {"action": "decline"},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        peer.refresh_from_db()
        assert peer.pending_keys == {} and peer.public_key == before

    def test_geplanter_wechsel_waehrend_notfall_abgelehnt(self, net, world, coupled):
        with net.on(VEREIN):
            keys.rotate(None, emergency=True)
        peer = coupled["verein_at_verband"]
        peer.refresh_from_db()
        # Jemand mit dem alten Schlüssel versucht einen „geplanten“ Wechsel auf eigene Schlüssel
        sign, enc = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
        pk, epk, at = _raw_pub(sign), _raw_pub(enc), timezone.now().isoformat()
        proof = identity.b64(sign.sign(identity.key_statement(str(peer.instance_id), pk, epk, at)))
        payload = {"public_key": pk, "enc_public_key": epk, "at": at, "proof": proof}
        with pytest.raises(services.Refused) as exc:
            keys.receive(peer, payload)
        assert exc.value.status == 409

    def test_ohne_nachweis_des_neuen_schluessels(self, coupled):
        peer = coupled["verein_at_verband"]
        sign, enc = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
        payload = {
            "public_key": _raw_pub(sign),
            "enc_public_key": _raw_pub(enc),
            "at": timezone.now().isoformat(),
            "proof": identity.b64(b"0" * 64),
        }
        with pytest.raises(services.Refused) as exc:
            keys.receive(peer, payload)
        assert exc.value.status == 422

    def test_fremde_ankuendigung_ohne_alten_schluessel(self, net, world, coupled):
        """Wer den alten Schlüssel nicht hat, kann keinen Wechsel ankündigen."""
        net.down.add(VERBAND)
        with net.on(VEREIN):
            keys.rotate(None, emergency=True)
        net.down.clear()
        with net.on(VEREIN):
            data = _key_file(net, VEREIN)
            data.pop("previous")  # ohne alten Schlüssel
            _write_key_file(net, VEREIN, data)
            result = keys.announce(coupled["verband_at_verein"])
        assert "Unterschrift" in result
        coupled["verein_at_verband"].refresh_from_db()
        assert coupled["verein_at_verband"].pending_keys == {}


class TestPlattform:
    def test_knopf_mit_bestaetigungswort(self, net, world, coupled, alarms):
        with net.on(VEREIN):
            admin = make_user("plattform@verein.example")
            give_role(admin, Organization.platform())
            c = api(admin)
            before = identity.identity().fingerprint
            assert c.post("/api/platform/peering/keys/", {}, content_type=JSON).status_code == 400
            resp = c.post("/api/platform/peering/keys/", {"confirm": "wechseln"}, content_type=JSON)
            assert resp.status_code == 200, resp.json()
            assert resp.json()["fingerprint"] != before
            assert resp.json()["peers"] == [{"base_url": VERBAND, "knows_current": True}]
            info = c.get("/api/platform/peering/").json()
            assert info["keys"]["previous_until"]
            notfall = c.post(
                "/api/platform/peering/keys/",
                {"mode": "emergency", "confirm": "WECHSELN"},
                content_type=JSON,
            )
            assert notfall.status_code == 400

    def test_nur_plattform(self, net, world):
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                "/api/platform/peering/keys/", {"confirm": "WECHSELN"}, content_type=JSON
            )
        assert resp.status_code == 403


class TestAlarm:
    def test_gehaeuft_falsche_unterschriften(self, net, world, coupled, alarms):
        from django.core.cache import cache

        cache.clear()
        peer = coupled["verband_at_verein"]
        with net.on(VERBAND):
            ident = identity.identity()
        envelope = crypto.seal(
            {"kind": "x"},
            sender=ident.instance_id,
            recipient=str(coupled["verein_at_verband"].instance_id),
            recipient_enc_key=coupled["verein_at_verband"].enc_public_key,
        )
        body = json.dumps(envelope).encode()
        for i in range(7):
            headers = {
                transport.H_INSTANCE: ident.instance_id,
                transport.H_DATE: timezone.now().isoformat(),
                transport.H_NONCE: f"n{i}",
                transport.H_SIGNATURE: identity.b64(b"1" * 64),
            }
            with net.on(VERBAND):
                status, _, _ = net.send(f"{VEREIN}/api/peering/v1/inbox/", headers, body)
            assert status == 403
        assert alarms.count("Verbund: ungültige Unterschriften einer Gegenstelle") == 1
        assert peer.base_url == VERBAND

    def test_anderer_schluessel_beim_koppeln(self, net, world, coupled, alarms):
        info = {
            "instance_id": str(coupled["verein_at_verband"].instance_id),
            "base_url": VEREIN,
            "public_key": _raw_pub(Ed25519PrivateKey.generate()),
            "enc_public_key": _raw_pub(X25519PrivateKey.generate()),
            "fingerprint": "X",
        }
        with pytest.raises(Exception):  # noqa: B017
            services._store_peer(info)
        assert "Verbund: Gegenstelle meldet einen anderen Schlüssel" in alarms


class TestBefehle:
    def test_notfallwechsel_per_befehl(self, net, world, coupled, alarms):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with net.on(VEREIN):
            call_command("verbund_schluessel_wechseln", "--notfall", stdout=out)
            fingerprint = identity.identity().fingerprint
        assert fingerprint in out.getvalue()
        assert f"{VERBAND}: wartet auf Bestätigung dort" in out.getvalue()

    def test_geraete_abmelden(self, net, settings, tmp_path):
        from io import StringIO

        from django.core.management import call_command

        from devices import webpush
        from devices.models import Device

        from .factories import make_user

        user = make_user("geraet@example.org")
        Device.objects.create(user=user, name="Telefon", token_hash="x" * 64, admin_token_hash="y")
        settings.PUSH_VAPID_KEY_FILE = str(tmp_path / "vapid.json")
        webpush.vapid_public_key()
        out = StringIO()
        call_command("geraete_abmelden", "--push-schluessel", stdout=out)
        device = Device.objects.get()
        assert device.revoked_at is not None and device.admin_token_hash == ""
        assert not (tmp_path / "vapid.json").exists()
