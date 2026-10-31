"""Verbund Schritt 0: feste Kennung, Instanzschlüssel, Selbstauskunft, Verschlüsselung."""

import json
import uuid

import pytest

from organizations.models import Organization
from peering import crypto, identity

from .factories import give_role, make_org, make_user
from .test_datatransfer import upload

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _keys(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.PEERING_KEY_FILE = ""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    identity.reset_cache()
    yield
    identity.reset_cache()


@pytest.fixture(autouse=True)
def _on_commit_now(monkeypatch):
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, *a, **k: func())


def other_identity(tmp_path, name):
    path = tmp_path / name / "instance.json"
    identity._create(path)
    return identity._load(path)


class TestKennung:
    def test_jede_einheit_hat_feste_kennung(self):
        a = make_org("Verein A")
        b = make_org("Verein B")
        assert isinstance(a.uuid, uuid.UUID)
        assert a.uuid != b.uuid
        before = a.uuid
        a.name = "Verein A neu"
        a.save()
        a.refresh_from_db()
        assert a.uuid == before

    def test_export_und_import_behalten_kennung(self, client, settings):
        from django.test import Client

        fed = make_org("Bund", "federation")
        make_org("Verein X", parent=fed)
        admin = make_user("plattform@example.org")
        give_role(admin, Organization.platform())
        c = Client()
        c.force_login(admin)
        resp = c.post(
            "/api/platform/datatransfer/exports/", {"organization": fed.pk}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        content = b"".join(
            c.get(
                f"/api/platform/datatransfer/exports/{resp.json()['id']}/download/"
            ).streaming_content
        )
        doc = json.loads(content)
        assert doc["organization"]["uuid"] == str(fed.uuid)

        # Kennung ist auf dieser Instanz schon vergeben: Kopie bekommt eine neue
        job = upload(c, "/api/platform", content, name="Kopie")
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        copy = Organization.objects.get(pk=job["result_organization"]["id"])
        assert copy.uuid != fed.uuid

        # Umzug: auf der neuen Instanz ist die Kennung frei und bleibt erhalten
        doc["organization"]["uuid"] = str(uuid.uuid4())
        job = upload(c, "/api/platform", json.dumps(doc).encode(), name="Umzug")
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        moved = Organization.objects.get(pk=job["result_organization"]["id"])
        assert str(moved.uuid) == doc["organization"]["uuid"]


class TestIdentitaet:
    def test_schluessel_wird_einmal_erzeugt_und_bleibt(self, settings):
        first = identity.identity()
        identity.reset_cache()
        second = identity.identity()
        assert first.instance_id == second.instance_id
        assert first.public_key == second.public_key
        path = identity.key_path()
        assert path.exists()
        assert oct(path.stat().st_mode & 0o777) == "0o600"

    def test_gleichzeitiges_anlegen_behaelt_erste_datei(self):
        path = identity.key_path()
        identity._create(path)
        first = path.read_text()
        identity._create(path)
        assert path.read_text() == first

    def test_selbstauskunft(self, client, settings):
        settings.PEERING_BASE_URL = "https://verband.example/"
        resp = client.get("/api/peering/v1/instance/")
        assert resp.status_code == 200
        data = resp.json()
        ident = identity.identity()
        assert data["instance_id"] == ident.instance_id
        assert data["public_key"] == ident.public_key
        assert data["enc_public_key"] == ident.enc_public_key
        assert data["fingerprint"] == ident.fingerprint
        assert data["base_url"] == "https://verband.example"
        assert data["versions"] == [1]
        # Kein privater Schlüssel, keine Einheiten
        text = json.dumps(data)
        assert "private" not in text
        assert ident.enc_key is not None


class TestVerschluesselung:
    def test_nur_empfaenger_kann_lesen(self, tmp_path):
        a = other_identity(tmp_path, "a")
        b = other_identity(tmp_path, "b")
        c = other_identity(tmp_path, "c")
        payload = {"kind": "test", "name": "Müller"}
        env = crypto.seal(
            payload,
            sender=a.instance_id,
            recipient=b.instance_id,
            recipient_enc_key=b.enc_public_key,
        )
        assert "Müller" not in json.dumps(env)
        assert crypto.open_sealed(env, b) == payload
        with pytest.raises(crypto.CryptoError):
            crypto.open_sealed(env, c)
        # Umgeleitet: an C adressiert, aber für B verschlüsselt
        with pytest.raises(crypto.CryptoError):
            crypto.open_sealed({**env, "to": c.instance_id}, c)
        # Absender verfälscht
        with pytest.raises(crypto.CryptoError):
            crypto.open_sealed({**env, "from": c.instance_id}, b)
        # Inhalt verändert
        broken = dict(env)
        ct = bytearray(identity.unb64(env["ct"]))
        ct[0] ^= 1
        broken["ct"] = identity.b64(bytes(ct))
        with pytest.raises(crypto.CryptoError):
            crypto.open_sealed(broken, b)

    def test_unterschrift(self, tmp_path):
        a = other_identity(tmp_path, "a")
        b = other_identity(tmp_path, "b")
        body = b'{"x":1}'
        sig = crypto.sign_request(a, "POST", "/api/peering/v1/inbox/", "d", "n", body)
        assert crypto.verify_request(
            a.public_key, "POST", "/api/peering/v1/inbox/", "d", "n", body, sig
        )
        assert not crypto.verify_request(
            b.public_key, "POST", "/api/peering/v1/inbox/", "d", "n", body, sig
        )
        assert not crypto.verify_request(
            a.public_key, "POST", "/api/peering/v1/inbox/", "d", "n", b"{}", sig
        )
        assert not crypto.verify_request(
            a.public_key, "POST", "/api/peering/v1/other/", "d", "n", body, sig
        )

    def test_fingerabdruck_deckt_beide_schluessel_ab(self, tmp_path):
        a = other_identity(tmp_path, "a")
        b = other_identity(tmp_path, "b")
        assert identity.fingerprint(a.public_key, a.enc_public_key) != identity.fingerprint(
            a.public_key, b.enc_public_key
        )
