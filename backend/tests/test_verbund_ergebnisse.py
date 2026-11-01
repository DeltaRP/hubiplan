# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Wettbewerbe Schritt 7: Paket „Wettbewerbsergebnisse“ im Verbund (erfundene Daten)."""

import datetime

import pytest
from django.utils import timezone

from competitions import services as comp_services
from competitions.models import Competition
from core.tenancy import tenant_context
from peering import packet_results
from peering.models import RemoteState

from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .test_verbund_termine import enable, sync

pytestmark = pytest.mark.django_db


def _standings(competition):
    """Erfundene Ranglisten: zwei Vereine, je zwei Starter."""
    return {
        "scorings": [
            {
                "name": "Einzel",
                "kind": "einzel",
                "rows": [
                    {
                        "place": 1,
                        "name": "Fremde Person",
                        "club": "Anderer Verein",
                        "unit": None,
                        "value_text": "98",
                    },
                    {
                        "place": 2,
                        "name": "Max Muster",
                        "club": "schützenverein  beispiel",
                        "unit": None,
                        "value_text": "95",
                    },
                    {
                        "place": 3,
                        "name": "Erika Muster",
                        "club": "",
                        "unit": None,
                        "value_text": "90",
                    },
                    {
                        "place": None,
                        "name": "Ohne Wert",
                        "club": "Schützenverein Beispiel",
                        "unit": None,
                        "value_text": "",
                    },
                ],
            },
            {
                "name": "Vereine",
                "kind": "einheit",
                "rows": [
                    {"place": 1, "name": "Anderer Verein", "unit": 999999, "value_text": "290"},
                    {
                        "place": 2,
                        "name": "Schützenverein Beispiel",
                        "unit": None,
                        "value_text": "280",
                    },
                ],
            },
        ]
    }


def _wettbewerb(fed, title, **extra):
    values = {
        "organization": fed,
        "title": title,
        "date": timezone.localdate() - datetime.timedelta(days=10),
        "status": Competition.Status.FINAL,
    }
    values.update(extra)
    with tenant_context(fed.pk):
        return Competition.objects.create(**values)


@pytest.fixture
def ranglisten(monkeypatch):
    monkeypatch.setattr(comp_services, "standings", _standings)


class TestErgebnisPaket:
    def test_standard_aus(self, net, world, ranglisten):
        with net.on(VERBAND):
            _wettbewerb(world["fed"], "Bundesmeisterschaft")
        lower, upper = couple(net, world)
        assert "results" not in (upper.packets or {})
        assert not RemoteState.objects.filter(coupling=lower, key="results").exists()

    def test_nur_einheiten(self, net, world, ranglisten):
        fed = world["fed"]
        with net.on(VERBAND):
            _wettbewerb(fed, "Bundesmeisterschaft")
            _wettbewerb(fed, "Noch offen", status=Competition.Status.RUNNING)
            _wettbewerb(fed, "Zu alt", date=timezone.localdate() - datetime.timedelta(days=800))
            _wettbewerb(fed, "Vogelschießen", form=Competition.Form.BIRD)
        lower, upper = couple(net, world)
        enable(net, world, lower, upper, packets_upper={"unit": "on", "results": "units"})
        data = RemoteState.objects.get(coupling=lower, key="results").data
        assert data["level"] == "units"
        assert [c["title"] for c in data["competitions"]] == ["Bundesmeisterschaft"]
        scorings = data["competitions"][0]["scorings"]
        # Keine Einzelwertung, also keine Personen
        assert [s["name"] for s in scorings] == ["Vereine"]
        rows = scorings[0]["rows"]
        assert [(r["place"], r["name"], r["own"]) for r in rows] == [
            (1, "Anderer Verein", False),
            (2, "Schützenverein Beispiel", True),
        ]
        assert scorings[0]["field"] == 2
        assert packet_results.persons(data) == 0

    def test_eigene_starter(self, net, world, ranglisten):
        with net.on(VERBAND):
            _wettbewerb(world["fed"], "Bundesmeisterschaft", location="Musterstadt")
        lower, upper = couple(net, world)
        enable(net, world, lower, upper, packets_upper={"unit": "on", "results": "own"})
        data = RemoteState.objects.get(coupling=lower, key="results").data
        comp = data["competitions"][0]
        assert comp["location"] == "Musterstadt"
        einzel = comp["scorings"][0]
        # Nur der eigene Starter; fremde Personen und Starter ohne Verein bleiben draußen
        assert einzel["rows"] == [{"place": 2, "name": "Max Muster", "value": "95", "own": True}]
        assert einzel["field"] == 3
        assert packet_results.persons(data) == 1
        # Abschalten entfernt die Ergebnisse
        enable(net, world, lower, upper, packets_upper={"unit": "on"})
        sync(net, lower, upper)
        assert not RemoteState.objects.filter(coupling=lower, key="results").exists()

    def test_anzeige_in_kopplung(self, net, world, ranglisten):
        with net.on(VERBAND):
            _wettbewerb(world["fed"], "Bundesmeisterschaft")
        lower, upper = couple(net, world)
        enable(net, world, lower, upper, packets_upper={"unit": "on", "results": "own"})
        with net.on(VEREIN):
            c = api(world["club_board"])
            data = c.get(f"/api/orgs/{world['club'].pk}/peering/couplings/{lower.pk}/").json()
        results = data["received"]["results"]
        assert results["competitions"][0]["title"] == "Bundesmeisterschaft"


def test_eingang_wird_bereinigt():
    data = {
        "level": "own",
        "competitions": [
            "kaputt",
            {
                "uid": "x" * 100,
                "title": "T" * 500,
                "scorings": [
                    {
                        "name": "E",
                        "kind": "einzel",
                        "field": -3,
                        "rows": [{"place": "1", "name": 5, "own": 1}, "kaputt"],
                    }
                ],
            },
        ],
    }
    clean = packet_results._clean(data)
    comp = clean["competitions"][0]
    assert len(comp["uid"]) == 40 and len(comp["title"]) == 200
    s = comp["scorings"][0]
    assert s["field"] is None
    assert s["rows"] == [{"place": None, "name": "5", "value": "", "own": True}]
