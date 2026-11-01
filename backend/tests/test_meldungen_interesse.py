"""Meldungen Schritt 2: Interessenabfrage über die Zusagen eines Termins und „Wofür bin ich
gemeldet?“ im Mitgliederbereich (Ralf 2026-11-01; alles erfunden)."""

import datetime

import pytest
from django.utils import timezone

from events.models import Event, EventResponse
from portal.models import PortalAccess

from .factories import give_role, make_user
from .test_meldungen import _call, _post, club, schuetzen, url  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def kalender(club):  # noqa: F811
    club.enabled_modules = [*club.enabled_modules, "events"]
    club.member_portal_enabled = True
    club.save()
    return club


def _termin(org, title="Vergleichsschießen", day=datetime.date(2027, 6, 12), **extra):
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time(10, 0)))
    return Event.objects.create(
        organization=org,
        title=title,
        location="Musterstadt",
        starts_at=start,
        ends_at=start + datetime.timedelta(hours=6),
        **extra,
    )


def _zusage(org, event, membership, status="yes", note=""):
    return EventResponse.objects.create(
        organization=org,
        event=event,
        membership=membership,
        status=status,
        note=note,
        source="member",
    )


class TestTermin:
    def test_termin_waehlen_und_zusagen_als_vorauswahl(
        self,
        kalender,
        schuetzen,  # noqa: F811
        board_a,
        api,
    ):
        c = api(board_a)
        call = _call(c, kalender, location="")
        assert call["event"] is None and call["calendar"] == {"on": True, "can_create": True}
        termin = _termin(kalender, rsvp_enabled=True)
        _termin(kalender, "Schützenfest", day=datetime.date(2027, 8, 20))
        cands = c.get(url(kalender, f"calls/{call['id']}/event-candidates/")).json()
        titles = [e["title"] for e in cands["events"]]
        assert "Vergleichsschießen" in titles and "Schützenfest" not in titles
        resp = c.post(
            url(kalender, f"calls/{call['id']}/event/"), {"event": termin.pk}, "application/json"
        )
        assert resp.status_code == 200, resp.content
        detail = resp.json()
        assert detail["event"]["id"] == termin.pk and detail["location"] == "Musterstadt"

        _zusage(kalender, termin, schuetzen["Max"], note="nur vormittags")
        _zusage(kalender, termin, schuetzen["Erika"])
        _zusage(kalender, termin, schuetzen["Otto"], status="no")
        base = url(kalender, f"calls/{call['id']}/")
        resp = c.get(f"{base}responses/")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [r["name"] for r in data["yes"]] == ["Erika Beispiel", "Max Muster"]
        assert data["no_count"] == 1
        assert data["yes"][1]["note"] == "nur vormittags"
        assert not any(r["taken"] for r in data["yes"])

        # Aus den Zusagen melden, aber auch jemand ohne Zusage aus der Mitgliederliste
        block = call["blocks"][0]["id"]
        team = _post(c, f"{base}entry/teams/", {"block": block})["teams"][0]["id"]
        for first in ("Max", "Anna"):
            _post(
                c,
                f"{base}entry/persons/",
                {"block": block, "team": team, "membership": schuetzen[first].pk},
            )
        data = c.get(f"{base}responses/").json()
        assert [r["taken"] for r in data["yes"]] == [False, True]
        response = {}
        for term in ("Otto", "Max", "Tom"):
            for r in c.get(f"{base}candidates/?suche={term}").json():
                response[r["name"]] = r["response"]
        assert response["Otto Normal"] == "no" and response["Max Muster"] == "yes"
        assert response["Tom Lang"] is None

        # Lösen
        resp = c.post(f"{base}event/", {"event": None}, "application/json")
        assert resp.json()["event"] is None
        assert c.get(f"{base}responses/").json() == {"yes": [], "no_count": 0}

    def test_termin_mit_zusagen_anlegen(self, kalender, board_a, api):
        c = api(board_a)
        call = _call(c, kalender)
        resp = c.post(
            url(kalender, f"calls/{call['id']}/event/"), {"create": True}, "application/json"
        )
        assert resp.status_code == 200, resp.content
        event = Event.objects.get(pk=resp.json()["event"]["id"])
        assert event.title == "Vergleichsschießen 2027" and event.rsvp_enabled
        assert event.visibility == Event.Visibility.MEMBERS
        assert timezone.localtime(event.starts_at).date() == datetime.date(2027, 6, 12)
        # Zusagen bis zum Abend vor dem Meldeschluss (31.05.)
        assert timezone.localtime(event.rsvp_deadline).date() == datetime.date(2027, 5, 30)
        resp = c.post(
            url(kalender, f"calls/{call['id']}/event/"), {"create": True}, "application/json"
        )
        assert resp.status_code == 400

    def test_ohne_datum_oder_terminrecht(self, kalender, api):
        melder = make_user("melder@example.org")
        give_role(melder, kalender, ["entries.submit", "members.view"], name="Melder")
        c = api(melder)
        call = _call(c, kalender)
        assert call["calendar"] == {"on": True, "can_create": False}
        link = url(kalender, f"calls/{call['id']}/event/")
        assert c.post(link, {"create": True}, "application/json").status_code == 403

    def test_zusagen_nur_mit_mitgliederrecht(self, kalender, api):
        melder = make_user("melder@example.org")
        give_role(melder, kalender, ["entries.submit"], name="Melder")
        c = api(melder)
        call = _call(c, kalender)
        assert c.get(url(kalender, f"calls/{call['id']}/responses/")).status_code == 403

    def test_fremder_termin(self, kalender, orgs, board_a, api):
        c = api(board_a)
        call = _call(c, kalender)
        fremd = _termin(orgs["b"])
        resp = c.post(
            url(kalender, f"calls/{call['id']}/event/"), {"event": fremd.pk}, "application/json"
        )
        assert resp.status_code == 400


class TestMitgliederbereich:
    def test_wofuer_bin_ich_gemeldet(self, kalender, schuetzen, board_a, api):  # noqa: F811
        max_ = schuetzen["Max"]
        user = make_user("max@example.org")
        access = PortalAccess.objects.create(organization=kalender, membership=max_, user=user)
        me = api(user)
        mine = f"/api/portal/{access.pk}/entries/"
        info = me.get("/api/me/contexts/").json()["portal"][0]
        assert info["entries_enabled"] is True
        assert me.get(mine).json() == []

        c = api(board_a)
        call = _call(c, kalender)
        base = url(kalender, f"calls/{call['id']}/")
        block = call["blocks"][0]["id"]
        team = _post(c, f"{base}entry/teams/", {"block": block})["teams"][0]["id"]
        _post(c, f"{base}entry/persons/", {"block": block, "team": team, "membership": max_.pk})
        # Entwurf: noch nicht gemeldet
        assert me.get(mine).json() == []
        _post(c, f"{base}entry/submit/", {"channel": "brief"})
        rows = me.get(mine).json()
        assert len(rows) == 1
        assert rows[0]["title"] == "Vergleichsschießen 2027"
        assert rows[0]["group"] == "Hubertus I" and rows[0]["confirmed"] is False

        # Ersetzt: Tom erscheint erst mit der nächsten Fassung
        person = c.get(f"{base}entry/").json()["persons"][0]["id"]
        resp = c.patch(
            f"{base}entry/persons/{person}/",
            {"membership": schuetzen["Tom"].pk},
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        assert me.get(mine).json() == []  # der Eintrag gehört jetzt Tom
        tom = make_user("tom@example.org")
        acc = PortalAccess.objects.create(
            organization=kalender, membership=schuetzen["Tom"], user=tom
        )
        toms = f"/api/portal/{acc.pk}/entries/"
        assert api(tom).get(toms).json() == []  # noch nicht gemeldet
        _post(c, f"{base}entry/submit/", {"channel": "brief"})
        assert me.get(mine).json() == []
        rows = api(tom).get(toms).json()
        assert [r["group"] for r in rows] == ["Hubertus I"]
        # Fremder Zugang
        assert api(tom).get(mine).status_code == 404

    def test_zurueckgezogen_nicht_mehr_gemeldet(
        self,
        kalender,
        schuetzen,  # noqa: F811
        board_a,
        api,
    ):
        max_ = schuetzen["Max"]
        user = make_user("max@example.org")
        access = PortalAccess.objects.create(organization=kalender, membership=max_, user=user)
        c = api(board_a)
        call = _call(c, kalender)
        base = url(kalender, f"calls/{call['id']}/")
        block = call["blocks"][0]["id"]
        team = _post(c, f"{base}entry/teams/", {"block": block})["teams"][0]["id"]
        _post(c, f"{base}entry/persons/", {"block": block, "team": team, "membership": max_.pk})
        _post(c, f"{base}entry/submit/", {"channel": "brief"})
        _post(c, f"{base}entry/submit/", {"channel": "brief", "withdraw": True, "reason": "krank"})
        assert api(user).get(f"/api/portal/{access.pk}/entries/").json() == []
