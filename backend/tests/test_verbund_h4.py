# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Härtung H4: versiegelter Postausgang, Höchstalter, Höchststufe beim Empfänger (erfunden)."""

import datetime
import json

import pytest
from django.core import mail
from django.utils import timezone

from peering import services
from peering.models import Coupling, Message, RemoteState

from .factories import make_member
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def coupled(net, world):
    with net.on(VEREIN):
        make_member(world["club"], "Anna", "Aktiv", birth_date=datetime.date(1980, 5, 17))
    lower, upper = couple(net, world)
    return lower, upper


class TestPostausgang:
    def test_wartende_pakete_nur_verschluesselt(self, net, world, coupled):
        lower, upper = coupled
        net.down.add(VERBAND)
        with net.on(VEREIN):
            services.enqueue(lower, "coupling.config", {"packets": {"geheim": "Anna Aktiv"}})
        msg = Message.objects.filter(coupling=lower, state=Message.State.QUEUED).latest("seq")
        stored = json.dumps(msg.payload)
        assert "Anna" not in stored and "geheim" not in stored
        assert msg.payload["sealed"]["format"] == "hubiplan-sealed-v1"
        net.down.clear()
        msg.next_try_at = timezone.now()
        msg.save()
        with net.on(VEREIN):
            services.deliver(lower.pk)
        msg.refresh_from_db()
        assert msg.state == Message.State.DONE and msg.payload is None

    def test_alte_pakete_ohne_versiegelung_gehen_noch_raus(self, net, world, coupled):
        lower, _ = coupled
        net.down.add(VERBAND)
        with net.on(VEREIN):
            msg = services.enqueue(lower, "coupling.config", {"packets": lower.packets})
        Message.objects.filter(pk=msg.pk).update(
            payload={"packets": lower.packets}, next_try_at=timezone.now()
        )
        net.down.clear()
        with net.on(VEREIN):
            services.deliver(lower.pk)
        msg.refresh_from_db()
        assert msg.state == Message.State.DONE

    def test_nach_14_tagen_verworfen_und_neu_gebaut(self, net, world, coupled):
        lower, _ = coupled
        net.down.add(VERBAND)
        with net.on(VEREIN):
            msg = services.enqueue(lower, "coupling.config", {"packets": lower.packets})
        Message.objects.filter(pk=msg.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=15), next_try_at=timezone.now()
        )
        Coupling.objects.filter(pk=lower.pk).update(sent_hashes={"unit": "x"})
        mail.outbox.clear()
        with net.on(VEREIN):
            services.deliver(lower.pk)
        msg.refresh_from_db()
        assert msg.state == Message.State.FAILED and msg.payload is None
        lower.refresh_from_db()
        assert lower.sent_hashes == {} and "14 Tagen" in lower.last_error
        assert [m.subject for m in mail.outbox] == [
            "Verbund: Pakete an Bürgerbund Musterstadt verworfen"
        ]


class TestHoechststufe:
    def test_mehr_als_bestaetigt_wird_abgelehnt(self, net, world, coupled):
        lower, upper = coupled
        mail.outbox.clear()
        # Der Verein gibt die namentliche Meldung frei, der Dachverband hat nur weniger angenommen
        with net.on(VEREIN):
            services.set_packets(lower, {"unit": "on", "members": "b"}, None)
        upper.refresh_from_db()
        assert not RemoteState.objects.filter(coupling=upper, key="members").exists()
        assert [w["key"] for w in services.wants_more(upper)] == ["members"]
        assert any("möchte mehr Daten senden" in m.subject for m in mail.outbox)
        rejected = Message.objects.filter(
            coupling=lower, kind="packet.members", state=Message.State.REJECTED
        )
        assert rejected.exists()
        base = f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/"
        with net.on(VERBAND):
            c = api(world["fed_board"])
            data = c.get(base).json()
            assert data["wants_more"][0]["level"] == "b"
            assert "accept" not in data["options"]
            resp = c.post(f"{base}more-accept/", {"key": "members"}, content_type=JSON)
            assert resp.status_code == 200, resp.json()
            assert resp.json()["wants_more"] == []
        # Täglicher Abgleich schickt den Stand erneut
        with net.on(VEREIN):
            lower.refresh_from_db()
            services.reconcile(lower)
        assert RemoteState.objects.filter(coupling=upper, key="members").exists() or (
            upper.remote_members.exists()
        )

    def test_ablehnen_bleibt_bei_der_bisherigen_stufe(self, net, world, coupled):
        lower, upper = coupled
        with net.on(VEREIN):
            services.set_packets(lower, {"unit": "on", "members": "a"}, None)
        upper.refresh_from_db()
        with net.on(VERBAND):
            resp = api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/more-decline/",
                {"key": "members"},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        upper.refresh_from_db()
        assert "members" not in services.accepted(upper)
        assert services.wants_more(upper) == []

    def test_weniger_geht_immer(self, net, world, coupled):
        lower, upper = coupled
        with net.on(VEREIN):
            services.set_packets(lower, {"unit": "on"}, None)
        upper.refresh_from_db()
        assert services.wants_more(upper) == []
        assert upper.remote_packets == {"unit": "on"}

    def test_aeltere_kopplung_behaelt_bisherigen_stand(self, net, world, coupled):
        lower, upper = coupled
        options = dict(upper.options)
        options.pop("accept")
        Coupling.objects.filter(pk=upper.pk).update(options=options)
        with net.on(VEREIN):
            services.set_packets(lower, {"unit": "on", "events": "on", "members": "a"}, None)
        upper.refresh_from_db()
        assert services.accepted(upper) == {"unit": "on", "events": "on", "statute": "on"}
        assert [w["key"] for w in services.wants_more(upper)] == ["members"]
