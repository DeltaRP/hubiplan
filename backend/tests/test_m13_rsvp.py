"""Meilenstein 13: Zu- und Absagen, Teilnehmerliste, E-Mails, persönliches Kalender-Abo."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import datetime

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone
from openpyxl import load_workbook

from audit.models import AuditEntry
from events import notify
from events.models import Event, EventResponse, PersonalCalendar
from members.models import MembershipPeriod

from .factories import make_member
from .test_m12_events import (  # noqa: F401  (Fixtures)
    JSON,
    at,
    board_fed,
    cal,
    create,
    dept_role,
    member_with_access,
    org_base,
    private_root,
    zug,
    zug2,
)

pytestmark = pytest.mark.django_db

SOON = timezone.localdate() + datetime.timedelta(days=20)


def soon(hour=19, days=0) -> str:
    return f"{SOON + datetime.timedelta(days=days)}T{hour:02d}:00:00"


def rsvp_event(client, base, **data):
    payload = {
        "title": "Königsschießen",
        "starts_at": soon(14),
        "ends_at": soon(18),
        "rsvp_enabled": True,
        **data,
    }
    return create(client, base, **payload)


def portal(access) -> str:
    return f"/api/portal/{access.pk}/"


def respond(client, access, event_id, **data):
    return client.put(
        f"{portal(access)}events/{event_id}/response/",
        {"status": "yes", **data},
        content_type=JSON,
    )


class TestRegeln:
    def test_nur_einmalige_vereinstermine(self, cal, board_a, board_fed, api):
        base = org_base(cal["a"])
        resp = api(board_a).post(
            f"{base}events/",
            {
                "title": "Übungsschießen",
                "starts_at": soon(),
                "repeat": "weekly",
                "rsvp_enabled": True,
            },
            content_type=JSON,
        )
        assert resp.status_code == 400 and "rsvp_enabled" in resp.json()
        resp = api(board_a).post(
            f"{base}events/",
            {"title": "Sitzung", "starts_at": soon(), "visibility": "board", "rsvp_enabled": True},
            content_type=JSON,
        )
        assert resp.status_code == 400
        resp = api(board_fed).post(
            f"{org_base(cal['federation'])}events/",
            {"title": "Schützenfest", "starts_at": soon(), "rsvp_enabled": True},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_ausgeschaltet_loescht_einstellungen(self, cal, board_a, api):
        data = rsvp_event(api(board_a), org_base(cal["a"]), rsvp_capacity=10, rsvp_guests=True)
        assert data["rsvp"]["capacity"] == 10
        resp = api(board_a).patch(
            f"{org_base(cal['a'])}events/{data['id']}/",
            {"rsvp_enabled": False},
            content_type=JSON,
        )
        assert resp.json()["rsvp"] == {
            "enabled": False,
            "deadline": None,
            "capacity": None,
            "guests_allowed": False,
            "max_guests": 10,
        }


class TestMitglied:
    def test_zusage_aendern_zuruecknehmen(self, cal, board_a, api):
        _, user, access = member_with_access(cal["a"], "Erika")
        data = rsvp_event(api(board_a), org_base(cal["a"]), rsvp_guests=True)
        c = api(user)
        listed = c.get(f"{portal(access)}events/?from={SOON}&to={SOON}").json()["items"]
        assert listed[0]["rsvp_enabled"] and listed[0]["my_response"] is None
        resp = respond(c, access, data["id"], guests=2, note="komme später")
        assert resp.status_code == 200, resp.json()
        mine = resp.json()["rsvp"]["mine"]
        assert mine["status"] == "yes" and mine["guests"] == 2 and mine["source"] == "member"
        listed = c.get(f"{portal(access)}events/?from={SOON}&to={SOON}").json()["items"]
        assert listed[0]["my_response"] == "yes"
        resp = respond(c, access, data["id"], status="no", guests=2)
        assert resp.json()["rsvp"]["mine"]["guests"] == 0  # Absage ohne Begleitung
        assert EventResponse.objects.count() == 1
        resp = c.delete(f"{portal(access)}events/{data['id']}/response/")
        assert resp.json()["rsvp"]["mine"] is None
        assert AuditEntry.objects.filter(changes__has_key="Rückmeldung Muster, Erika").count() == 3

    def test_begleitung_nur_wenn_erlaubt(self, cal, board_a, api):
        _, user, access = member_with_access(cal["a"], "Erika")
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        resp = respond(api(user), access, data["id"], guests=3)
        assert resp.json()["rsvp"]["mine"]["guests"] == 0

    def test_anmeldeschluss_und_abgesagt(self, cal, board_a, api):
        _, user, access = member_with_access(cal["a"], "Erika")
        past = (timezone.localtime() - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:00")
        data = rsvp_event(api(board_a), org_base(cal["a"]), rsvp_deadline=past)
        detail = api(user).get(f"{portal(access)}events/{data['id']}/").json()
        assert detail["rsvp"]["can_respond"] is False
        assert "Anmeldeschluss" in detail["rsvp"]["reason"]
        assert respond(api(user), access, data["id"]).status_code == 400
        data = rsvp_event(api(board_a), org_base(cal["a"]), is_cancelled=True)
        assert respond(api(user), access, data["id"]).status_code == 400

    def test_hoechstzahl_mit_begleitung(self, cal, board_a, api):
        _, u1, a1 = member_with_access(cal["a"], "Erika")
        _, u2, a2 = member_with_access(cal["a"], "Hans")
        data = rsvp_event(api(board_a), org_base(cal["a"]), rsvp_capacity=3, rsvp_guests=True)
        assert respond(api(u1), a1, data["id"], guests=1).status_code == 200
        resp = respond(api(u2), a2, data["id"], guests=1)
        assert resp.status_code == 400 and "nur noch 1" in resp.json()["guests"][0]
        resp = respond(api(u2), a2, data["id"])
        assert resp.status_code == 200 and resp.json()["rsvp"]["free"] == 0
        # Eigene Zusage ändern zählt nicht doppelt
        assert respond(api(u1), a1, data["id"], guests=1, note="x").status_code == 200
        # Absage ist immer möglich
        assert respond(api(u1), a1, data["id"], status="no").status_code == 200

    def test_zugtermin_nur_fuer_zugmitglieder(self, cal, zug, zug2, api):
        m, user, access = member_with_access(cal["a"], "Erika", depts=[zug])
        dept_role(zug, m, ["dept.events.manage"])
        _, other, other_access = member_with_access(cal["a"], "Hans", depts=[zug2])
        data = rsvp_event(api(user), f"/api/depts/{zug.pk}/", title="Zugabend")
        assert respond(api(user), access, data["id"]).status_code == 200
        # Hans sieht den Zugtermin gar nicht
        assert respond(api(other), other_access, data["id"]).status_code == 404

    def test_ausgetretene_koennen_nicht_zusagen(self, cal, board_a, api):
        m, user, access = member_with_access(cal["a"], "Erika")
        MembershipPeriod.objects.filter(membership=m).update(
            exit_date=timezone.localdate() - datetime.timedelta(days=1), exit_reason="exit"
        )
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        resp = respond(api(user), access, data["id"])
        assert resp.status_code in (403, 404)


class TestTeilnehmerliste:
    def test_vorstand_sieht_traegt_ein_und_exportiert(self, cal, board_a, zug, api):
        _, user, access = member_with_access(cal["a"], "Erika", depts=[zug])
        offline = make_member(cal["a"], "Otto", "Ohnemail")
        make_member(cal["b"], "Fremd", "Andere")  # anderer Verein
        data = rsvp_event(api(board_a), org_base(cal["a"]), rsvp_capacity=1)
        respond(api(user), access, data["id"])
        base = f"{org_base(cal['a'])}events/{data['id']}/responses/"
        listing = api(board_a).get(base).json()
        assert listing["summary"] == {"yes": 1, "no": 0, "guests": 0, "persons": 1, "open": 1}
        assert listing["items"][0]["name"] == "Muster, Erika"
        assert listing["items"][0]["departments"] == "Jägerzug"
        assert [o["name"] for o in listing["open"]] == ["Ohnemail, Otto"]
        # Vorstand trägt nach Anruf ein, auch über die Höchstzahl hinaus
        resp = api(board_a).put(
            base, {"membership_id": offline.pk, "status": "yes"}, content_type=JSON
        )
        assert resp.status_code == 200 and resp.json()["source"] == "board"
        assert api(board_a).get(base).json()["summary"]["persons"] == 2
        # Mitglied eines anderen Vereins lässt sich nicht eintragen
        other = make_member(cal["a"], "Neu", "Später")
        MembershipPeriod.objects.filter(membership=other).update(
            exit_date=timezone.localdate() - datetime.timedelta(days=1), exit_reason="exit"
        )
        resp = api(board_a).put(
            base, {"membership_id": other.pk, "status": "yes"}, content_type=JSON
        )
        assert resp.status_code == 400
        xlsx = api(board_a).get(f"{base}export/?type=xlsx")
        assert xlsx.status_code == 200
        import io

        sheet = load_workbook(io.BytesIO(xlsx.content)).active
        names = [row[0].value for row in sheet.iter_rows(min_row=4, max_row=5)]
        assert names == ["Muster, Erika", "Ohnemail, Otto"]
        pdf = api(board_a).get(f"{base}export/?type=pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert api(board_a).delete(f"{base}{offline.pk}/").status_code == 204
        assert EventResponse.objects.count() == 1

    def test_mitglied_und_fremder_verein_sehen_keine_liste(self, cal, board_a, board_b, api):
        _, user, access = member_with_access(cal["a"], "Erika")
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        detail = api(user).get(f"{portal(access)}events/{data['id']}/").json()
        assert "summary" not in detail["rsvp"] and "can_view_list" not in detail["rsvp"]
        resp = api(board_b).get(f"{org_base(cal['b'])}events/{data['id']}/responses/")
        assert resp.status_code == 404

    def test_zugvorstand_sieht_nur_seine_zugmitglieder(self, cal, board_a, zug, zug2, api):
        leader, leader_user, _ = member_with_access(cal["a"], "Zugführer", depts=[zug])
        dept_role(zug, leader, ["dept.events.manage"])
        _, u1, a1 = member_with_access(cal["a"], "Erika", depts=[zug])
        _, u2, a2 = member_with_access(cal["a"], "Hans", depts=[zug2])
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        respond(api(u1), a1, data["id"])
        respond(api(u2), a2, data["id"])
        base = f"/api/depts/{zug.pk}/events/{data['id']}/responses/"
        listing = api(leader_user).get(base).json()
        assert listing["scope"] == "department"
        assert [i["name"] for i in listing["items"]] == ["Muster, Erika"]
        assert [o["name"] for o in listing["open"]] == ["Muster, Zugführer"]
        # Eintragen nur für eigene Zugmitglieder
        hans = EventResponse.objects.get(membership__person__first_name="Hans").membership
        resp = api(leader_user).put(
            base, {"membership_id": hans.pk, "status": "no"}, content_type=JSON
        )
        assert resp.status_code == 400
        resp = api(leader_user).put(
            base, {"membership_id": leader.pk, "status": "yes"}, content_type=JSON
        )
        assert resp.status_code == 200
        # Zugmitglied ohne Rolle sieht nichts
        resp = api(u1).get(base)
        assert resp.status_code in (403, 404)


class TestMails:
    @pytest.fixture
    def members(self, cal):
        _, user, access = member_with_access(cal["a"], "Erika")
        make_member(cal["a"], "Hans", "Muster")
        return user, access

    @pytest.fixture(autouse=True)
    def _outbox(self, mailoutbox):
        self.outbox = mailoutbox

    def mails(self):
        return [m for m in self.outbox if m.extra_headers.get("X-Hubiplan-Kind") == "termin"]

    def test_einladung_beim_anlegen(
        self, cal, board_a, members, api, settings, django_capture_on_commit_callbacks
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        with django_capture_on_commit_callbacks(execute=True):
            rsvp_event(api(board_a), org_base(cal["a"]), notify=True, location="Schützenhaus")
        mails = self.mails()
        assert sorted(m.to for m in mails) == [["erika@example.org"], ["hans@example.org"]]
        assert mails[0].subject.startswith("Einladung: Königsschießen am ")
        assert "Schützenhaus" in mails[0].body and "/termine" in mails[0].body
        # ohne Haken keine Mail
        with django_capture_on_commit_callbacks(execute=True):
            create(api(board_a), org_base(cal["a"]), title="Still")
        assert len(self.mails()) == 2

    def test_aenderung_und_absage(
        self, cal, board_a, members, api, settings, django_capture_on_commit_callbacks
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        user, access = members
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        respond(api(user), access, data["id"], status="no")
        url = f"{org_base(cal['a'])}events/{data['id']}/"
        with django_capture_on_commit_callbacks(execute=True):
            api(board_a).patch(url, {"title": "Neu", "notify": True}, content_type=JSON)
        assert self.mails() == []  # nur Titel: keine Nachricht
        with django_capture_on_commit_callbacks(execute=True):
            api(board_a).patch(url, {"location": "Festzelt", "notify": True}, content_type=JSON)
        # Erika hat abgesagt und bekommt keine Änderung
        assert [m.to for m in self.mails()] == [["hans@example.org"]]
        with django_capture_on_commit_callbacks(execute=True):
            api(board_a).patch(
                url,
                {"is_cancelled": True, "cancel_note": "Regen", "notify": True},
                content_type=JSON,
            )
        last = self.mails()[-1]
        assert last.subject.startswith("Abgesagt:") and "Regen" in last.body

    def test_mail_nach_autospeichern(
        self, cal, board_a, members, api, settings, django_capture_on_commit_callbacks
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        url = f"{org_base(cal['a'])}events/{data['id']}/"
        c = api(board_a)
        c.patch(url, {"location": "Festzelt"}, content_type=JSON)
        resp = c.post(f"{url}notify/", {"kind": "cancel"}, content_type=JSON)
        assert resp.status_code == 400  # nicht abgesagt
        with django_capture_on_commit_callbacks(execute=True):
            assert c.post(f"{url}notify/", {"kind": "change"}, content_type=JSON).status_code == 204
        assert len(self.mails()) == 2
        assert "Festzelt" in self.mails()[0].body

    def test_erinnerung_nur_an_zusagen_und_einmal(self, cal, board_a, members, api):
        user, access = members
        data = rsvp_event(api(board_a), org_base(cal["a"]), remind_days=3)
        respond(api(user), access, data["id"])
        event = Event.objects.get(pk=data["id"])
        before = event.starts_at - datetime.timedelta(days=4)
        assert notify.send_reminders(before) == 0
        due = event.starts_at - datetime.timedelta(days=2)
        assert notify.send_reminders(due) == 1
        assert notify.send_reminders(due) == 0
        mail = self.mails()[0]
        assert mail.to == ["erika@example.org"] and mail.subject.startswith("Erinnerung:")
        assert "Ihre Rückmeldung: Zusage." in mail.body
        # Verschoben: Erinnerung kommt noch einmal
        api(board_a).patch(
            f"{org_base(cal['a'])}events/{data['id']}/",
            {"starts_at": soon(15, days=5), "ends_at": soon(18, days=5)},
            content_type=JSON,
        )
        assert Event.objects.get(pk=data["id"]).reminded_at is None

    def test_erinnerung_ohne_rueckmeldung_an_alle(self, cal, board_a, members, api):
        data = create(
            api(board_a),
            org_base(cal["a"]),
            title="Fest",
            starts_at=soon(),
            ends_at=soon(22),
            remind_days=1,
        )
        event = Event.objects.get(pk=data["id"])
        assert notify.send_reminders(event.starts_at - datetime.timedelta(hours=1)) == 2


class TestKalenderAbo:
    def test_persoenlicher_link(self, cal, board_a, zug, api):
        _, user, access = member_with_access(cal["a"], "Erika", depts=[zug])
        create(api(board_a), org_base(cal["a"]), title="JHV", starts_at=soon(), ends_at=soon(22))
        create(
            api(board_a),
            org_base(cal["a"]),
            title="Intern",
            starts_at=soon(),
            ends_at=soon(22),
            visibility="board",
        )
        c = api(user)
        assert c.get(f"{portal(access)}events/feed/").json() == {"ics_url": None}
        url = c.put(f"{portal(access)}events/feed/").json()["ics_url"]
        body = Client().get(url).content.decode()
        assert "SUMMARY:JHV" in body and "Intern" not in body
        # erneuern: alter Link ungültig
        new = c.put(f"{portal(access)}events/feed/").json()["ics_url"]
        assert new != url and Client().get(url).status_code == 404
        # Zugang entzogen: Link liefert nichts mehr
        access.delete()
        assert Client().get(new).status_code == 404
        assert PersonalCalendar.objects.count() == 0

    def test_ausgetreten_kein_abo(self, cal, api):
        m, user, access = member_with_access(cal["a"], "Erika")
        url = api(user).put(f"{portal(access)}events/feed/").json()["ics_url"]
        MembershipPeriod.objects.filter(membership=m).update(
            exit_date=timezone.localdate() - datetime.timedelta(days=1), exit_reason="exit"
        )
        assert Client().get(url).status_code == 404

    def test_einzelner_termin_als_datei(self, cal, board_a, api):
        _, user, access = member_with_access(cal["a"], "Erika")
        data = create(
            api(board_a), org_base(cal["a"]), title="JHV", starts_at=soon(), ends_at=soon(22)
        )
        resp = api(user).get(f"{portal(access)}events/{data['id']}/ics/")
        assert resp.status_code == 200 and b"SUMMARY:JHV" in resp.content
        assert "attachment" in resp["Content-Disposition"]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_rls_rueckmeldungen_nur_eigener_verein(cal, board_a, api):
    from core.rls import APP_ROLE
    from core.tenancy import scope_of, set_rls

    _, user, access = member_with_access(cal["a"], "Erika")
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        data = rsvp_event(api(board_a), org_base(cal["a"]))
        assert respond(api(user), access, data["id"]).status_code == 200
        assert api(user).put(f"{portal(access)}events/feed/").status_code == 200
        listing = api(board_a).get(f"{org_base(cal['a'])}events/{data['id']}/responses/")
        assert listing.json()["summary"]["yes"] == 1
        set_rls(cal["b"].pk, None, False, scope_id=scope_of(cal["b"].pk))
        assert EventResponse.objects.count() == 0
        assert PersonalCalendar.objects.count() == 0
        set_rls(cal["a"].pk, None, False, scope_id=scope_of(cal["a"].pk))
        assert EventResponse.objects.count() == 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)


def test_alle_zeiten_in_mail_deutsch(cal):
    event = Event(
        organization=cal["a"],
        title="X",
        starts_at=at(2026, 3, 28, 19),
        ends_at=at(2026, 3, 28, 22),
    )
    assert notify.when(event) == "28.03.2026, 19:00 bis 22:00 Uhr"
