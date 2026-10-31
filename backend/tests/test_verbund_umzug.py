# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 6: Umzug einer Einheit auf eine andere Instanz (erfundene Daten).

Alle Instanzen teilen sich im Test eine Datenbank. Die feste Kennung der Einheit
muss dort eindeutig sein; darum bekommt die alte Einheit nach dem Export eine
andere Kennung, so als läge sie auf einem anderen Server.
"""

import datetime
import json
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.tenancy import rls_bypass
from organizations.models import Organization
from peering import identity, services
from peering.models import Coupling, RemoteMember

from .factories import give_role, make_member, make_user
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .verbund_netz import release

pytestmark = pytest.mark.django_db
JSON = "application/json"
NEU = "https://neu.example"


@pytest.fixture
def moved_world(net, world, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    net.add(NEU)
    with net.on(VEREIN):
        make_member(world["club"], "Anna", "Aktiv", birth_date=datetime.date(1980, 5, 17))
    lower, upper = couple(net, world)
    with net.on(VEREIN):
        release(lower, {"unit": "on", "events": "on", "members": "b"})
    upper.refresh_from_db()
    return {"lower": lower, "upper": upper}


def export_club(world) -> bytes:
    club = world["club"]
    c = api(world["club_board"])
    resp = c.post(f"/api/orgs/{club.pk}/datatransfer/exports/", {}, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    job = resp.json()
    resp = c.get(f"/api/orgs/{club.pk}/datatransfer/exports/{job['id']}/download/")
    return b"".join(resp.streaming_content)


def import_on(net, content: bytes) -> Organization:
    admin = make_user(f"admin-{uuid.uuid4().hex[:6]}@neu.example")
    give_role(admin, Organization.platform())
    c = api(admin)
    resp = c.post(
        "/api/platform/datatransfer/imports/",
        {"file": SimpleUploadedFile("export.json", content)},
    )
    assert resp.status_code == 201, resp.json()
    job_id = resp.json()["id"]
    resp = c.post(f"/api/platform/datatransfer/imports/{job_id}/run/")
    job = c.get(f"/api/platform/datatransfer/imports/{job_id}/").json()
    assert job["status"] == "done", job
    return Organization.objects.get(pk=job["result_organization"]["id"])


VERBAND_SICHT_ALT = VEREIN  # Gegenstelle des Dachverbands vor dem Umzug


class TestUmzug:
    def test_export_enthaelt_kopplung_ohne_schluessel(self, net, world, moved_world):
        with net.on(VEREIN):
            doc = json.loads(export_club(world))
        couplings = doc["organization"]["peering"]
        assert couplings[0]["direction"] == "parent"
        assert couplings[0]["peer"]["base_url"] == VERBAND
        assert "private" not in json.dumps(couplings).lower()

    def test_umzug_und_weiterarbeit(self, net, world, moved_world):
        old_club = world["club"]
        with net.on(VEREIN):
            content = export_club(world)
        with net.on(NEU):
            fingerprint = identity.identity().fingerprint
        # Alte Instanz meldet den Umzug (hier vor dem Einlesen; die Gegenstelle
        # versucht es bis dahin später erneut)
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{old_club.pk}/peering/move/",
                {"base_url": NEU, "fingerprint": fingerprint},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["done"] == 1, resp.json()
        # Alte Einheit „auf einem anderen Server“: im Test eigene Kennung
        unit_uuid = old_club.uuid
        Organization.objects.filter(pk=old_club.pk).update(uuid=uuid.uuid4())
        with net.on(NEU):
            new_club = import_on(net, content)
        assert new_club.uuid == unit_uuid
        new_coupling = Coupling.objects.get(local_unit=new_club)
        assert new_coupling.direction == "parent" and new_coupling.peer.base_url == VERBAND
        lower = moved_world["lower"]
        lower.refresh_from_db()
        assert lower.state == "moved"
        upper = moved_world["upper"]
        upper.refresh_from_db()
        # Der Dachverband stellt nichts still um: Kopplung ruht bis zur Bestätigung
        assert upper.peer.base_url == VERBAND_SICHT_ALT and upper.state == "moving"
        board = api(world["fed_board"])
        url = f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/"
        with net.on(VERBAND):
            data = board.get(url).json()
            assert data["move"]["base_url"] == NEU
            assert data["move"]["fingerprint"] == fingerprint
            resp = board.post(url + "move-confirm/", {"fingerprint": "AAAA"}, content_type=JSON)
            assert resp.status_code == 400
            resp = board.post(
                url + "move-confirm/", {"fingerprint": fingerprint}, content_type=JSON
            )
            assert resp.status_code == 200, resp.json()
        upper.refresh_from_db()
        assert upper.peer.base_url == NEU and upper.state == "active"
        # Die neue Instanz schickt ihre Stände, der Dachverband erkennt die Personen wieder
        before = set(
            RemoteMember.objects.filter(coupling=upper).values_list("membership", flat=True)
        )
        with net.on(NEU):
            services.sync(new_coupling)
        upper.refresh_from_db()
        assert upper.last_error == ""
        with rls_bypass():
            members = RemoteMember.objects.filter(coupling=upper, status="active")
            assert set(members.values_list("membership", flat=True)) == before
            # Alte Zuordnung still abgelöst: Zeitraum bleibt offen, nichts gelöscht
            for rm in members:
                assert rm.membership.purged_at is None
                assert rm.membership.periods.filter(exit_date__isnull=True).exists()
        # Pakete des Dachverbands erreichen die neue Instanz
        with net.on(VERBAND):
            release(upper, {"unit": "on", "events": "on", "statute": "on"})
        new_coupling.refresh_from_db()
        assert new_coupling.remote_packets.get("statute") == "on"
        # Die alte Instanz nimmt nichts mehr an
        assert lower.messages.filter(direction="in", created_at__gt=lower.ended_at).count() == 0

    def test_falscher_fingerabdruck(self, net, world, moved_world):
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/move/",
                {"base_url": NEU, "fingerprint": "AAAA BBBB"},
                content_type=JSON,
            )
        assert resp.status_code == 400
        moved_world["lower"].refresh_from_db()
        assert moved_world["lower"].state == "active"

    def test_umzug_ablehnen(self, net, world, moved_world):
        with net.on(NEU):
            fingerprint = identity.identity().fingerprint
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/move/",
                {"base_url": NEU, "fingerprint": fingerprint},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        upper = moved_world["upper"]
        upper.refresh_from_db()
        assert upper.state == "moving"
        # Solange nichts bestätigt ist, geht nichts hinaus
        with net.on(VERBAND):
            assert services.sync(upper) == 0
            url = f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/move-decline/"
            resp = api(world["fed_board"]).post(url, {}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        upper.refresh_from_db()
        assert upper.state == "ended" and upper.peer.base_url == VEREIN
