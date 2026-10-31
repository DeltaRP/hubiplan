"""Verbund Schritt 1: Koppeln über Instanzen, Stammdaten, Postausgang, Abgleich, Lösen."""

import json

import pytest
from django.core import mail
from django.test import Client

from core.tenancy import rls_bypass
from organizations.models import Organization, PlatformSettings
from peering import crypto, identity, services, transport
from peering.models import Coupling, CouplingCode, Message, Peer

from .factories import give_role, make_org, make_user
from .verbund_netz import install

pytestmark = pytest.mark.django_db
JSON = "application/json"
VEREIN = "https://verein.example"
VERBAND = "https://verband.example"


@pytest.fixture(autouse=True)
def _setup(settings, tmp_path, monkeypatch):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, *a, **k: func())
    ps = PlatformSettings.load()
    ps.peering_enabled = True
    ps.save()
    yield
    identity.reset_cache()


@pytest.fixture
def net(monkeypatch, tmp_path):
    n = install(monkeypatch, tmp_path)
    n.add(VEREIN)
    n.add(VERBAND)
    return n


@pytest.fixture
def world(net):
    """Dachverband auf „verband.example“, Verein auf „verein.example“ (erfunden)."""
    with net.on(VERBAND):
        fed = make_org("Bürgerbund Musterstadt", "federation", city="Musterstadt")
        fed_board = make_user("verband@example.org")
        give_role(fed_board, fed)
    with net.on(VEREIN):
        club = make_org(
            "Schützenverein Beispiel", city="Beispielhausen", contact_email="info@verein.example"
        )
        club_board = make_user("verein@example.org")
        give_role(club_board, club)
    return {"fed": fed, "club": club, "fed_board": fed_board, "club_board": club_board}


def api(user) -> Client:
    c = Client()
    c.force_login(user)
    return c


def make_code(net, world) -> str:
    with net.on(VERBAND):
        resp = api(world["fed_board"]).post(f"/api/orgs/{world['fed'].pk}/peering/codes/")
    assert resp.status_code == 201, resp.json()
    return resp.json()["code"]


def couple(net, world, accept=True):
    code = make_code(net, world)
    with net.on(VEREIN):
        resp = api(world["club_board"]).post(
            f"/api/orgs/{world['club'].pk}/peering/couplings/",
            {"code": code, "packets": {"unit": "on", "events": "on", "statute": "on"}},
            content_type=JSON,
        )
    assert resp.status_code == 201, resp.json()
    lower = Coupling.objects.get(local_unit=world["club"])
    upper = Coupling.objects.get(local_unit=world["fed"])
    if accept:
        with net.on(VERBAND):
            resp = api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/accept/"
            )
        assert resp.status_code == 200, resp.json()
        lower.refresh_from_db()
        upper.refresh_from_db()
    return lower, upper


class TestKoppeln:
    def test_vorschau_zeigt_gegenseite_und_datenfluss(self, net, world):
        code = make_code(net, world)
        assert code.startswith("HUBIPLAN1-")
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/inspect/", {"code": code}, content_type=JSON
            )
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["remote"]["name"] == "Bürgerbund Musterstadt"
        assert data["remote"]["base_url"] == VERBAND
        with net.on(VERBAND):
            assert data["remote"]["fingerprint"] == identity.identity().fingerprint
        assert "unit" in [p["key"] for p in data["send"]]
        # Vorschau verbraucht den Code nicht
        assert CouplingCode.objects.get().used_at is None

    def test_ablauf_bis_aktiv_und_stammdaten(self, net, world):
        lower, upper = couple(net, world, accept=False)
        assert lower.state == "requested"
        assert upper.state == "pending"
        # Platzhalter: Verein hängt beim Dachverband unten, Dachverband beim Verein nicht darüber
        club_ph = upper.remote_unit
        assert club_ph.is_remote and club_ph.parent_id == world["fed"].pk
        assert club_ph.type == "club"
        fed_ph = lower.remote_unit
        assert fed_ph.is_remote and fed_ph.type == "federation"
        world["club"].refresh_from_db()
        assert world["club"].parent.type == "platform"  # nicht umgehängt
        assert CouplingCode.objects.get().used_at is not None
        # Vorstand des Dachverbands bekommt eine Mail
        assert any("Kopplungsanfrage" in m.subject for m in mail.outbox)

        with net.on(VERBAND):
            resp = api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/accept/"
            )
        assert resp.status_code == 200
        lower.refresh_from_db()
        upper.refresh_from_db()
        assert lower.state == upper.state == "active"
        club_ph.refresh_from_db()
        fed_ph.refresh_from_db()
        assert club_ph.city == "Beispielhausen"
        assert club_ph.contact_email == "info@verein.example"
        assert fed_ph.name == "Bürgerbund Musterstadt"
        assert fed_ph.city == "Musterstadt"
        # Alle Pakete zugestellt, Inhalte danach geleert
        assert not Message.objects.filter(state="queued").exists()
        assert not Message.objects.exclude(payload=None).exists()

    def test_aenderung_wird_nachgereicht(self, net, world):
        lower, upper = couple(net, world)
        club = world["club"]
        club.name = "Schützenverein Beispiel 1920"
        club.save()
        with net.on(VEREIN):
            assert services.sync(lower) == 1
            assert services.sync(lower) == 0  # unverändert: nichts Neues
        upper.remote_unit.refresh_from_db()
        assert upper.remote_unit.name == "Schützenverein Beispiel 1920"

    def test_code_nur_einmal(self, net, world):
        code = make_code(net, world)
        with net.on(VEREIN):
            ok = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/couplings/",
                {"code": code},
                content_type=JSON,
            )
            assert ok.status_code == 201
            other = make_org("Zweiter Verein")
            give_role(world["club_board"], other)
            again = api(world["club_board"]).post(
                f"/api/orgs/{other.pk}/peering/couplings/", {"code": code}, content_type=JSON
            )
        assert again.status_code == 400
        assert "ungültig" in again.json()["detail"] or "benutzt" in again.json()["detail"]

    def test_falscher_fingerabdruck(self, net, world):
        code = make_code(net, world)
        data = json.loads(identity.unb64(code[len(services.CODE_PREFIX) :]))
        data["f"] = "0" * 24
        forged = services.CODE_PREFIX + identity.b64(json.dumps(data).encode())
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/couplings/",
                {"code": forged},
                content_type=JSON,
            )
        assert resp.status_code == 400
        assert "Fingerabdruck" in resp.json()["detail"]
        assert not Coupling.objects.exists()

    def test_nur_eine_einheit_darueber(self, net, world):
        couple(net, world)
        code = make_code(net, world)
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/couplings/",
                {"code": code},
                content_type=JSON,
            )
        assert resp.status_code == 400

    def test_verein_mit_lokalem_dachverband_kann_nicht(self, net, world):
        with net.on(VEREIN):
            local_fed = make_org("Lokaler Bund", "federation")
            club = make_org("Verein im lokalen Bund", parent=local_fed)
            assert not services.can_join(club)
            assert services.can_join(world["club"])
            assert services.can_offer(world["club"])  # ferne Untereinheiten (Schritt 8)

    def test_ohne_recht_und_ohne_verbund(self, net, world):
        with net.on(VERBAND):
            nobody = make_user("kassierer@example.org")
            give_role(nobody, world["fed"], permissions=["finance.view"], name="Kasse")
            assert (
                api(nobody).post(f"/api/orgs/{world['fed'].pk}/peering/codes/").status_code == 403
            )
        ps = PlatformSettings.load()
        ps.peering_enabled = False
        ps.save()
        with net.on(VERBAND):
            resp = api(world["fed_board"]).post(f"/api/orgs/{world['fed'].pk}/peering/codes/")
            assert resp.status_code == 400
            assert (
                Client().post("/api/peering/v1/inbox/", "{}", content_type=JSON).status_code == 404
            )

    def test_platzhalter_ist_nicht_bearbeitbar(self, net, world):
        lower, upper = couple(net, world)
        ph = upper.remote_unit
        with net.on(VERBAND):
            c = api(world["fed_board"])
            resp = c.patch(
                f"/api/orgs/{world['fed'].pk}/clubs/{ph.pk}/", {"name": "X"}, content_type=JSON
            )
            assert resp.status_code == 400
            clubs = c.get(f"/api/orgs/{world['fed'].pk}/clubs/").json()
            listed = clubs["results"] if isinstance(clubs, dict) else clubs
            assert [x["is_remote"] for x in listed if x["id"] == ph.pk] == [True]
            # Im Platzhalter selbst arbeitet niemand
            give_role(world["fed_board"], ph)
            assert c.get(f"/api/orgs/{ph.pk}/").status_code == 404


class TestZustellung:
    def test_ausfall_staut_und_wird_nachgeholt(self, net, world):
        lower, upper = couple(net, world)
        net.down.add(VERBAND)
        world["club"].city = "Neustadt"
        world["club"].save()
        with net.on(VEREIN):
            services.sync(lower)
        msg = Message.objects.get(coupling=lower, state="queued")
        assert msg.attempts == 1 and msg.last_error
        lower.refresh_from_db()
        assert lower.error_since is not None
        # Nach einem Tag: Hinweis an den Vorstand
        Coupling.objects.filter(pk=lower.pk).update(
            error_since=lower.error_since - services.WARN_AFTER
        )
        with net.on(VEREIN):
            services.warn_stuck()
        assert any("nicht erreichbar" in m.subject for m in mail.outbox)
        net.down.clear()
        Message.objects.filter(pk=msg.pk).update(next_try_at=msg.created_at)
        with net.on(VEREIN):
            services.deliver_due()
        msg.refresh_from_db()
        assert msg.state == "done" and msg.payload is None
        upper.remote_unit.refresh_from_db()
        assert upper.remote_unit.city == "Neustadt"
        lower.refresh_from_db()
        assert lower.error_since is None

    def test_doppelt_und_veraltet_wird_ignoriert(self, net, world):
        lower, upper = couple(net, world)
        with net.on(VEREIN):
            env = services._envelope(lower, "packet.unit", {"level": "on", "name": "Alt"}, seq=1)
            # seq 1 ist längst verarbeitet: wird angenommen, aber nicht angewendet
            answer = transport.call(services.keys_of(lower.peer), "/api/peering/v1/inbox/", env)
            assert answer["ok"]
            again = transport.call(services.keys_of(lower.peer), "/api/peering/v1/inbox/", env)
            assert again.get("duplicate")
        upper.remote_unit.refresh_from_db()
        assert upper.remote_unit.name == "Schützenverein Beispiel"

    def test_pause_haelt_pakete_zurueck(self, net, world):
        lower, upper = couple(net, world)
        with net.on(VERBAND):
            resp = api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/pause/"
            )
            assert resp.json()["state"] == "paused"
        world["club"].city = "Pausenhausen"
        world["club"].save()
        with net.on(VEREIN):
            services.sync(lower)
        assert Message.objects.filter(coupling=lower, state="queued").exists()
        with net.on(VERBAND):
            api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/resume/"
            )
        Message.objects.filter(coupling=lower).update(next_try_at=None)
        with net.on(VEREIN):
            services.deliver(lower.pk)
        upper.remote_unit.refresh_from_db()
        assert upper.remote_unit.city == "Pausenhausen"

    def test_abgleich_heilt_verlorenen_stand(self, net, world):
        lower, upper = couple(net, world)
        # Dachverband hat seinen Stand verloren (z. B. Rücksicherung)
        Coupling.objects.filter(pk=upper.pk).update(received_hashes={})
        ph = upper.remote_unit
        ph.city = "falsch"
        ph.save()
        with net.on(VEREIN):
            assert "unit" in services.reconcile(lower)
        ph.refresh_from_db()
        assert ph.city == "Beispielhausen"
        with net.on(VEREIN):
            assert services.reconcile(Coupling.objects.get(pk=lower.pk)) == []

    def test_freigabe_entziehen(self, net, world):
        lower, upper = couple(net, world)
        with net.on(VEREIN):
            resp = api(world["club_board"]).patch(
                f"/api/orgs/{world['club'].pk}/peering/couplings/{lower.pk}/",
                {"packets": {}},
                content_type=JSON,
            )
        assert resp.status_code == 200
        upper.refresh_from_db()
        assert upper.remote_packets == {}


class TestSicherheit:
    def test_fremde_unterschrift_abgelehnt(self, net, world, tmp_path):
        lower, upper = couple(net, world)
        intruder = tmp_path / "boese" / "instance.json"
        identity._create(intruder)
        evil = identity._load(intruder)
        with net.on(VEREIN):
            ident = identity.identity()
            env = services._envelope(
                lower, "packet.unit", {"level": "on", "name": "Gehackt"}, seq=99
            )
        with net.on(VERBAND):
            target = identity.identity()
        sealed = crypto.seal(
            env,
            sender=ident.instance_id,
            recipient=target.instance_id,
            recipient_enc_key=target.enc_public_key,
        )
        body = json.dumps(sealed).encode()
        from django.utils import timezone

        date = timezone.now().isoformat()
        headers = {
            transport.H_INSTANCE: ident.instance_id,
            transport.H_DATE: date,
            transport.H_NONCE: "abc",
            # mit dem falschen Schlüssel unterschrieben
            transport.H_SIGNATURE: crypto.sign_request(
                evil, "POST", "/api/peering/v1/inbox/", date, "abc", body
            ),
        }
        status, _, _ = net.send(f"{VERBAND}/api/peering/v1/inbox/", headers, body)
        assert status == 403
        upper.remote_unit.refresh_from_db()
        assert upper.remote_unit.name == "Schützenverein Beispiel"

    def test_wiederholte_anfrage_abgelehnt(self, net, world, monkeypatch):
        lower, upper = couple(net, world)
        captured = {}
        original = net.send

        def spy(url, headers, body):
            captured["args"] = (url, dict(headers), body)
            return original(url, headers, body)

        monkeypatch.setattr(transport, "_send", spy)
        with net.on(VEREIN):
            transport.call(
                services.keys_of(lower.peer),
                "/api/peering/v1/status/",
                {"from_unit": str(world["club"].uuid), "to_unit": str(lower.remote_uuid)},
            )
        status, _, _ = original(*captured["args"])
        assert status == 409

    def test_unbekannte_instanz_abgelehnt(self, net, world, tmp_path):
        couple(net, world)
        stranger = tmp_path / "fremd" / "instance.json"
        identity._create(stranger)
        net.instances["https://fremd.example"] = str(stranger)
        with net.on("https://fremd.example"):
            with net.on(VERBAND):
                target = identity.identity()
            keys = transport.PeerKeys(
                target.instance_id, VERBAND, target.public_key, target.enc_public_key
            )
            with pytest.raises(transport.PeerError):
                transport.call(keys, "/api/peering/v1/inbox/", {"kind": "packet.unit"})

    def test_inhalt_unterwegs_verschluesselt(self, net, world, monkeypatch):
        seen = []
        original = net.send

        def spy(url, headers, body):
            seen.append(body)
            status, h, content = original(url, headers, body)
            seen.append(content)
            return status, h, content

        monkeypatch.setattr(transport, "_send", spy)
        couple(net, world)
        assert seen
        for raw in seen:
            assert b"Beispielhausen" not in raw and "Bürgerbund".encode() not in raw

    def test_nur_https(self, settings):
        settings.PEERING_ALLOW_INSECURE = False
        with pytest.raises(transport.PeerError):
            transport.normalize_url("http://verband.example")
        assert transport.normalize_url("https://Verband.example/") == "https://verband.example"
        with pytest.raises(transport.PeerError):
            transport.normalize_url("https://user:pw@verband.example")

    def test_keine_internen_adressen(self, settings, monkeypatch):
        settings.PEERING_ALLOW_INSECURE = False
        monkeypatch.setattr(
            "socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("10.0.0.5", 443))]
        )
        with pytest.raises(transport.PeerError, match="interne"):
            transport._get("https://verband.example/api/peering/v1/instance/")
        ps = PlatformSettings.load()
        ps.peering_allowed_hosts = "andere.example"
        ps.save()
        with pytest.raises(transport.PeerError, match="Liste"):
            transport.check_host("https://verband.example")

    def test_schluesselwechsel_ohne_neuen_code_abgelehnt(self, net, world):
        lower, upper = couple(net, world)
        peer = Peer.objects.get(pk=upper.peer_id)
        with pytest.raises(Exception, match="anderen Schlüssel"):
            services._store_peer(
                {
                    "instance_id": str(peer.instance_id),
                    "base_url": peer.base_url,
                    "public_key": identity.b64(b"x" * 32),
                    "enc_public_key": peer.enc_public_key,
                    "fingerprint": "",
                }
            )


class TestLoesen:
    def test_loesen_beidseitig(self, net, world):
        lower, upper = couple(net, world)
        with net.on(VEREIN):
            resp = api(world["club_board"]).delete(
                f"/api/orgs/{world['club'].pk}/peering/couplings/{lower.pk}/"
            )
        assert resp.status_code == 204
        lower.refresh_from_db()
        upper.refresh_from_db()
        assert lower.state == upper.state == "ended"
        assert not upper.remote_unit.is_active
        # Danach kann der Verein neu koppeln
        with net.on(VEREIN):
            assert services.can_join(world["club"])

    def test_ablehnen(self, net, world):
        lower, upper = couple(net, world, accept=False)
        with net.on(VERBAND):
            api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/decline/"
            )
        lower.refresh_from_db()
        assert lower.state == "ended"

    def test_uebersicht_und_protokoll(self, net, world):
        lower, upper = couple(net, world)
        with net.on(VEREIN):
            data = api(world["club_board"]).get(f"/api/orgs/{world['club'].pk}/peering/").json()
            assert data["enabled"] and not data["can_join"]
            assert data["couplings"][0]["state"] == "active"
            detail = (
                api(world["club_board"])
                .get(f"/api/orgs/{world['club'].pk}/peering/couplings/{lower.pk}/")
                .json()
            )
        kinds = {m["kind"] for m in detail["messages"]}
        assert {"coupling.accept", "packet.unit"} <= kinds
        from audit.models import AuditEntry

        with rls_bypass():
            assert AuditEntry.objects.filter(organization=world["club"]).exists()
        assert Organization.objects.filter(is_remote=True).count() == 2
