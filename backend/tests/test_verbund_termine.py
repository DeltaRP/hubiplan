# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 2: Termine, Vorstand und Satzung über Instanzen (erfundene Daten)."""

import datetime

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from core.tenancy import tenant_context
from events.models import Event
from events.services import Viewer
from peering import services
from peering.models import RemoteState

from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .verbund_netz import release

pytestmark = pytest.mark.django_db
JSON = "application/json"


def event(org, title, **extra):
    start = timezone.now() + datetime.timedelta(days=10)
    values = {
        "organization": org,
        "title": title,
        "starts_at": start,
        "ends_at": start + datetime.timedelta(hours=2),
        "visibility": "members",
    }
    values.update(extra)
    return Event.objects.create(**values)


def titles(org, **viewer):
    with tenant_context(org.pk):
        return sorted(e.title for e in Viewer(org=org, **viewer).events())


def enable(net, world, lower, upper, packets_lower=None, packets_upper=None):
    if packets_lower is not None:
        with net.on(VEREIN):
            release(lower, packets_lower)
    if packets_upper is not None:
        with net.on(VERBAND):
            release(upper, packets_upper)


def sync(net, lower, upper):
    with net.on(VEREIN):
        services.sync(lower)
    with net.on(VERBAND):
        services.sync(upper)


class TestTermine:
    def test_nach_unten_und_oben(self, net, world):
        fed, club = world["fed"], world["club"]
        with net.on(VERBAND):
            event(fed, "Schützenfest des Bundes")
            event(fed, "Vorstandssitzung Bund", visibility="board")
            event(fed, "Nur intern weiter", share_down=False)
        with net.on(VEREIN):
            event(club, "Vereinsabend", share_up=True)
            event(club, "Nicht nach oben", share_up=False)
        lower, upper = couple(net, world)
        assert titles(club) == ["Nicht nach oben", "Schützenfest des Bundes", "Vereinsabend"]
        assert titles(fed, sees_board=True) == [
            "Nur intern weiter",
            "Schützenfest des Bundes",
            "Vereinsabend",
            "Vorstandssitzung Bund",
        ]
        # Die übermittelten Termine gehören dem Platzhalter
        copy = Event.objects.get(title="Schützenfest des Bundes", organization=lower.remote_unit)
        assert copy.remote_uid

    def test_aenderung_und_loeschen(self, net, world):
        fed, club = world["fed"], world["club"]
        with net.on(VERBAND):
            e = event(fed, "Königsschießen")
        lower, upper = couple(net, world)
        e.title = "Königsschießen 2027"
        e.save()
        sync(net, lower, upper)
        assert "Königsschießen 2027" in titles(club)
        e.delete()
        sync(net, lower, upper)
        assert titles(club) == []

    def test_ohne_freigabe_keine_termine(self, net, world):
        fed, club = world["fed"], world["club"]
        with net.on(VERBAND):
            event(fed, "Schützenfest des Bundes")
        lower, upper = couple(net, world)
        enable(net, world, lower, upper, packets_upper={"unit": "on"})
        assert titles(club) == []

    def test_loesen_entfernt_kopien(self, net, world):
        with net.on(VERBAND):
            event(world["fed"], "Schützenfest des Bundes")
        lower, upper = couple(net, world)
        assert titles(world["club"]) == ["Schützenfest des Bundes"]
        with net.on(VEREIN):
            services.end(lower, None)
        assert titles(world["club"]) == []
        assert not Event.objects.filter(organization=lower.remote_unit).exists()

    def test_mitgliederbereich_sieht_termine_von_oben(self, net, world):
        with net.on(VERBAND):
            event(world["fed"], "Schützenfest des Bundes")
        couple(net, world)
        assert titles(world["club"], kind="member") == ["Schützenfest des Bundes"]


class TestVorstandUndSatzung:
    def test_satzung_nur_wenn_oeffentlich(self, net, world):
        from statutes.models import StatuteVersion
        from statutes.services import publication

        fed = world["fed"]
        with net.on(VERBAND):
            with tenant_context(fed.pk):
                v = StatuteVersion(
                    organization=fed,
                    name="Satzung-Bund.pdf",
                    valid_from=datetime.date(2019, 11, 8),
                    note="Neufassung",
                )
                v.file.save("s.pdf", ContentFile(b"%PDF-1.4 erfunden"), save=True)
        lower, upper = couple(net, world)
        assert not RemoteState.objects.filter(coupling=lower, key="statute").exists()
        with net.on(VERBAND):
            with tenant_context(fed.pk):
                pub = publication(fed, create=True)
                pub.is_public = True
                pub.save()
        sync(net, lower, upper)
        state = RemoteState.objects.get(coupling=lower, key="statute")
        assert state.data["valid_from"] == "2019-11-08"
        with net.on(VEREIN):
            c = api(world["club_board"])
            data = c.get(f"/api/orgs/{world['club'].pk}/peering/couplings/{lower.pk}/").json()
            url = data["received"]["statute"]["download_url"]
            resp = c.get(url)
        assert resp.status_code == 200
        assert b"".join(resp.streaming_content).startswith(b"%PDF")

    def test_vorstand_nur_mit_freigabe(self, net, world):
        from access.models import Role

        fed = world["fed"]
        with net.on(VERBAND):
            with tenant_context(fed.pk):
                Role.objects.create(
                    organization=fed,
                    name="Präsident",
                    permissions=[],
                    on_website=True,
                    contact_email="praesident@verband.example",
                )
        lower, upper = couple(net, world)
        assert not RemoteState.objects.filter(coupling=lower, key="board").exists()
        enable(net, world, lower, upper, packets_upper={"unit": "on", "board": "on"})
        board = RemoteState.objects.get(coupling=lower, key="board").data
        assert board["roles"] == [
            {"role": "Präsident", "email": "praesident@verband.example", "holders": []}
        ]
        enable(net, world, lower, upper, packets_upper={"unit": "on"})
        assert not RemoteState.objects.filter(coupling=lower, key="board").exists()
