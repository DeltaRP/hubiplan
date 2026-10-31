"""Meilenstein 12: Terminkalender für Dachverband, Verein und Abteilung."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.utils import timezone

from audit.models import AuditEntry
from events.models import CalendarPublication, Event, EventCategory, EventException
from events.recurrence import occurrences
from members.models import DepartmentRoleHolder
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
TZ = timezone.get_current_timezone()


def at(*args) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime(*args), TZ)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def cal(orgs):
    for org in orgs.values():
        org.enabled_modules = ["members", "events"]
        org.member_portal_enabled = True
        org.department_access_enabled = True
        org.save()
    return orgs


@pytest.fixture
def board_fed(cal):
    user = make_user("vorstand-bund@example.org")
    give_role(user, cal["federation"])
    return user


@pytest.fixture
def zug(cal):
    return Department.objects.create(
        self_managed=True, organization=cal["a"], name="Jägerzug", founding_year=1950
    )


@pytest.fixture
def zug2(cal):
    return Department.objects.create(
        self_managed=True, organization=cal["a"], name="Grenadiere", founding_year=1960
    )


def create(client, base, **data):
    payload = {
        "title": "Termin",
        "starts_at": "2026-06-13T14:00:00",
        "ends_at": "2026-06-13T18:00:00",
        "visibility": "members",
        **data,
    }
    resp = client.post(f"{base}events/", payload, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def org_base(org) -> str:
    return f"/api/orgs/{org.pk}/"


def titles(client, base, frm="2026-01-01", to="2026-12-31") -> list[str]:
    resp = client.get(f"{base}events/?from={frm}&to={to}")
    assert resp.status_code == 200, resp.content
    return [i["title"] for i in resp.json()["items"]]


def member_with_access(club, first, depts=(), user_email=None):
    m = make_member(club, first, "Muster", departments=depts)
    user = make_user(user_email or f"{first.lower()}@example.org")
    access = PortalAccess.objects.create(organization=club, membership=m, user=user)
    return m, user, access


def dept_role(dept, membership, perms):
    role = DepartmentRole.objects.create(
        department=dept, name=f"Rolle {len(perms)}", permissions=perms
    )
    DepartmentRoleHolder.objects.create(
        organization=dept.organization,
        membership=membership,
        role=role,
        valid_from=datetime.date(2020, 1, 1),
    )
    return role


class TestAnlegenUndRechte:
    def test_vorstand_legt_an_aendert_loescht(self, cal, board_a, api):
        c = api(board_a)
        base = org_base(cal["a"])
        data = create(c, base, title="Jahreshauptversammlung", location="Vereinsheim")
        assert data["can_edit"] and data["owner"] == "Verein A"
        assert data["changed_at"] is None
        resp = c.patch(f"{base}events/{data['id']}/", {"title": "JHV"}, content_type=JSON)
        assert resp.status_code == 200
        assert resp.json()["changed_at"] is None  # nur Titel geändert
        resp = c.patch(
            f"{base}events/{data['id']}/", {"location": "Schützenhaus"}, content_type=JSON
        )
        assert resp.json()["changed_at"] is not None
        assert titles(c, base) == ["JHV"]
        assert AuditEntry.objects.filter(object_type="Termin").count() >= 3
        assert c.delete(f"{base}events/{data['id']}/").status_code == 204
        assert titles(c, base) == []

    def test_ende_vor_beginn_und_titel(self, cal, board_a, api):
        resp = api(board_a).post(
            f"{org_base(cal['a'])}events/",
            {"title": " ", "starts_at": "2026-06-13T14:00:00"},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "title" in resp.json()
        resp = api(board_a).post(
            f"{org_base(cal['a'])}events/",
            {
                "title": "X",
                "starts_at": "2026-06-13T14:00:00",
                "ends_at": "2026-06-13T12:00:00",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400 and "ends_at" in resp.json()

    def test_ohne_recht_nur_lesen(self, cal, board_a, api):
        create(api(board_a), org_base(cal["a"]), title="Fest")
        reader = make_user("kassenpruefer@example.org")
        give_role(reader, cal["a"], ["finance.view"], name="Kassenprüfer")
        c = api(reader)
        resp = c.get(f"{org_base(cal['a'])}events/?from=2026-01-01&to=2026-12-31")
        assert [i["title"] for i in resp.json()["items"]] == ["Fest"]
        assert resp.json()["can_manage"] is False
        resp = c.post(
            f"{org_base(cal['a'])}events/",
            {"title": "X", "starts_at": "2026-06-13T14:00:00"},
            content_type=JSON,
        )
        assert resp.status_code == 403

    def test_modul_aus(self, cal, board_a, api):
        cal["a"].enabled_modules = ["members"]
        cal["a"].save()
        assert api(board_a).get(f"{org_base(cal['a'])}events/").status_code == 404

    def test_fremde_kategorie_abgelehnt(self, cal, board_a, api):
        fremd = EventCategory.objects.create(organization=cal["b"], name="Fremd")
        resp = api(board_a).post(
            f"{org_base(cal['a'])}events/",
            {"title": "X", "starts_at": "2026-06-13T14:00:00", "category": fremd.pk},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "category" in resp.json()

    def test_ganztaegig_mehrtaegig(self, cal, board_a, api):
        data = create(
            api(board_a),
            org_base(cal["a"]),
            title="Schützenfest",
            all_day=True,
            starts_at="2026-08-29T10:00:00",
            ends_at="2026-09-01T09:00:00",
        )
        assert timezone.localtime(datetime.datetime.fromisoformat(data["starts_at"])) == at(
            2026, 8, 29
        )
        assert timezone.localtime(datetime.datetime.fromisoformat(data["ends_at"])) == at(
            2026, 9, 1
        )
        # Auch am letzten Tag im Kalender
        assert titles(api(board_a), org_base(cal["a"]), "2026-09-01", "2026-09-01") == [
            "Schützenfest"
        ]


class TestKategorien:
    def test_anlegen_umbenennen_loeschen(self, cal, board_a, api):
        c = api(board_a)
        base = f"{org_base(cal['a'])}events/categories/"
        resp = c.post(base, {"name": "Versammlung", "color": "#123456"}, content_type=JSON)
        assert resp.status_code == 201
        cat = resp.json()["id"]
        resp = c.post(base, {"name": "versammlung"}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.post(base, {"name": "Fest", "color": "rot"}, content_type=JSON)
        assert resp.status_code == 400
        ev = create(c, org_base(cal["a"]), category=cat)
        assert ev["category"]["name"] == "Versammlung"
        resp = c.patch(f"{base}{cat}/", {"name": "Sitzung"}, content_type=JSON)
        assert resp.json()["name"] == "Sitzung"
        assert c.delete(f"{base}{cat}/").status_code == 204
        assert Event.objects.get(pk=ev["id"]).category is None


class TestSichtbarkeit:
    @pytest.fixture
    def kalender(self, cal, board_a, board_b, board_fed, zug, api):
        create(api(board_fed), org_base(cal["federation"]), title="Schützenfest BSV")
        create(
            api(board_fed),
            org_base(cal["federation"]),
            title="Vorstandssitzung BSV",
            visibility="board",
        )
        create(api(board_a), org_base(cal["a"]), title="Königsschießen", visibility="public")
        create(api(board_a), org_base(cal["a"]), title="Vorstand A", visibility="board")
        create(api(board_b), org_base(cal["b"]), title="Fest B")
        Event.objects.create(
            organization=cal["a"],
            department=zug,
            title="Zugabend",
            starts_at=at(2026, 3, 5, 20),
            ends_at=at(2026, 3, 5, 23),
        )
        Event.objects.create(
            organization=cal["a"],
            department=zug,
            title="Zugvorstand intern",
            visibility="board",
            starts_at=at(2026, 3, 6, 20),
            ends_at=at(2026, 3, 6, 23),
        )
        return cal

    def test_verein_sieht_dachverband_und_abteilungen(self, kalender, board_a, api):
        seen = titles(api(board_a), org_base(kalender["a"]))
        assert sorted(seen) == sorted(
            ["Schützenfest BSV", "Königsschießen", "Vorstand A", "Zugabend"]
        )

    def test_dachverband_nur_eigene(self, kalender, board_fed, api):
        seen = titles(api(board_fed), org_base(kalender["federation"]))
        assert sorted(seen) == ["Schützenfest BSV", "Vorstandssitzung BSV"]

    def test_dachverbandstermin_im_verein_nicht_bearbeitbar(self, kalender, board_a, api):
        c = api(board_a)
        items = c.get(f"{org_base(kalender['a'])}events/?from=2026-01-01&to=2026-12-31").json()[
            "items"
        ]
        fest = next(i for i in items if i["title"] == "Schützenfest BSV")
        assert fest["can_edit"] is False and fest["level"] == "federation"
        resp = c.patch(
            f"{org_base(kalender['a'])}events/{fest['event_id']}/",
            {"title": "gekapert"},
            content_type=JSON,
        )
        assert resp.status_code == 403
        zug = next(i for i in items if i["title"] == "Zugabend")
        assert zug["can_edit"] is False and zug["owner"] == "Jägerzug"

    def test_nicht_vorstand_sieht_keine_internen(self, kalender, api):
        reader = make_user("schriftfuehrer@example.org")
        role = give_role(reader, kalender["a"], ["members.view"], name="Helfer")
        role.role.is_board = False
        role.role.save()
        seen = titles(api(reader), org_base(kalender["a"]))
        assert "Vorstand A" not in seen and "Königsschießen" in seen

    def test_verein_ohne_dachverband(self, kalender, board_c, api):
        assert titles(api(board_c), org_base(kalender["c"])) == []

    def test_mitgliederbereich(self, kalender, zug, zug2, api):
        _, user, access = member_with_access(kalender["a"], "Erika", depts=[zug])
        resp = api(user).get(f"/api/portal/{access.pk}/events/?from=2026-01-01&to=2026-12-31")
        assert resp.status_code == 200
        seen = sorted(i["title"] for i in resp.json()["items"])
        assert seen == ["Königsschießen", "Schützenfest BSV", "Zugabend"]
        assert all(not i["can_edit"] for i in resp.json()["items"])
        # Ohne Zug: kein Zugtermin
        _, user2, access2 = member_with_access(kalender["a"], "Hans", depts=[zug2])
        seen2 = titles(api(user2), f"/api/portal/{access2.pk}/")
        assert "Zugabend" not in seen2
        # Nur lesen
        resp = api(user).post(
            f"/api/portal/{access.pk}/events/",
            {"title": "X", "starts_at": "2026-06-13T14:00:00"},
            content_type=JSON,
        )
        assert resp.status_code == 405

    def test_abteilung_eigener_kalender(self, kalender, zug, zug2, api):
        m, user, _ = member_with_access(kalender["a"], "Zugführer", depts=[zug])
        dept_role(zug, m, ["dept.members.view", "dept.events.manage"])
        c = api(user)
        base = f"/api/depts/{zug.pk}/"
        seen = sorted(titles(c, base))
        assert seen == sorted(
            ["Königsschießen", "Schützenfest BSV", "Zugabend", "Zugvorstand intern"]
        )
        data = create(c, base, title="Zugversammlung")
        assert data["owner"] == "Jägerzug" and data["can_edit"]
        assert Event.objects.get(pk=data["id"]).department == zug
        # Vereinstermine sind hier nicht bearbeitbar
        verein = Event.objects.get(title="Königsschießen")
        resp = c.patch(f"{base}events/{verein.pk}/", {"title": "x"}, content_type=JSON)
        assert resp.status_code == 403
        # Kein Zugriff auf den anderen Zug
        assert c.get(f"/api/depts/{zug2.pk}/events/").status_code == 404

    def test_abteilung_ohne_terminrecht_liest_nur(self, kalender, zug, api):
        m, user, _ = member_with_access(kalender["a"], "Kassierer", depts=[zug])
        dept_role(zug, m, ["dept.invoices.view"])
        c = api(user)
        resp = c.get(f"/api/depts/{zug.pk}/events/?from=2026-01-01&to=2026-12-31")
        assert resp.status_code == 200 and resp.json()["can_manage"] is False
        resp = c.post(
            f"/api/depts/{zug.pk}/events/",
            {"title": "X", "starts_at": "2026-06-13T14:00:00"},
            content_type=JSON,
        )
        assert resp.status_code == 403

    def test_verein_kann_keinen_zugtermin_bearbeiten(self, kalender, board_a, api):
        zugabend = Event.objects.get(title="Zugabend")
        resp = api(board_a).delete(f"{org_base(kalender['a'])}events/{zugabend.pk}/")
        assert resp.status_code == 403


class TestSerien:
    def test_woechentlich_ueber_zeitumstellung(self, cal):
        event = Event.objects.create(
            organization=cal["a"],
            title="Übungsabend",
            starts_at=at(2026, 3, 17, 19, 30),
            ends_at=at(2026, 3, 17, 22),
            repeat="weekly",
            repeat_until=datetime.date(2026, 4, 14),
        )
        items = occurrences([event], at(2026, 3, 1), at(2026, 5, 1))
        local = [timezone.localtime(o.starts_at) for o in items]
        assert [d.day for d in local] == [17, 24, 31, 7, 14]
        assert {(d.hour, d.minute) for d in local} == {(19, 30)}

    def test_monatlich_alle_zwei_und_jaehrlich(self, cal):
        monthly = Event.objects.create(
            organization=cal["a"],
            title="Stammtisch",
            starts_at=at(2026, 1, 10, 19),
            ends_at=at(2026, 1, 10, 22),
            repeat="monthly",
            repeat_interval=2,
        )
        yearly = Event.objects.create(
            organization=cal["a"],
            title="Gedenken",
            starts_at=at(2020, 11, 15, 11),
            ends_at=at(2020, 11, 15, 12),
            repeat="yearly",
        )
        items = occurrences([monthly, yearly], at(2026, 1, 1), at(2027, 1, 1))
        months = [timezone.localtime(o.starts_at).month for o in items if o.event == monthly]
        assert months == [1, 3, 5, 7, 9, 11]
        assert [o.starts_at for o in items if o.event == yearly] == [at(2026, 11, 15, 11)]

    def test_einzeltermin_verschieben_und_absagen(self, cal, board_a, api):
        c = api(board_a)
        base = org_base(cal["a"])
        data = create(
            c,
            base,
            title="Übungsabend",
            starts_at="2026-05-05T19:00:00",
            ends_at="2026-05-05T21:00:00",
            repeat="weekly",
            repeat_until="2026-05-26",
        )
        url = f"{base}events/{data['id']}/occurrence/"
        resp = c.put(
            url,
            {"original_start": "2026-05-12T19:00:00", "is_cancelled": True, "note": "Feiertag"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        resp = c.put(
            url,
            {
                "original_start": "2026-05-19T19:00:00",
                "starts_at": "2026-05-20T19:00:00",
                "ends_at": "2026-05-20T21:00:00",
            },
            content_type=JSON,
        )
        assert resp.status_code == 200
        resp = c.put(url, {"original_start": "2026-05-13T19:00:00"}, content_type=JSON)
        assert resp.status_code == 400  # kein Termin der Serie
        items = c.get(f"{base}events/?from=2026-05-01&to=2026-05-31").json()["items"]
        state = [
            (
                timezone.localtime(datetime.datetime.fromisoformat(i["starts_at"])).day,
                i["is_cancelled"],
                i["is_moved"],
            )
            for i in items
        ]
        assert state == [
            (5, False, False),
            (12, True, False),
            (20, False, True),
            (26, False, False),
        ]
        assert items[1]["note"] == "Feiertag"
        # Zurücksetzen
        resp = c.delete(url, {"original_start": "2026-05-12T19:00:00"}, content_type=JSON)
        assert resp.status_code == 200
        assert EventException.objects.count() == 1
        # Serie aufheben entfernt Abweichungen
        c.patch(f"{base}events/{data['id']}/", {"repeat": "none"}, content_type=JSON)
        assert EventException.objects.count() == 0

    def test_ende_der_serie_vor_beginn(self, cal, board_a, api):
        resp = api(board_a).post(
            f"{org_base(cal['a'])}events/",
            {
                "title": "X",
                "starts_at": "2026-05-05T19:00:00",
                "repeat": "weekly",
                "repeat_until": "2026-05-01",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400 and "repeat_until" in resp.json()


class TestAnhaenge:
    def test_hochladen_lesen_loeschen(self, cal, board_a, zug, api):
        c = api(board_a)
        base = org_base(cal["a"])
        ev = create(c, base, title="JHV")
        pdf = SimpleUploadedFile("Einladung JHV.pdf", b"%PDF-1.4 erfunden", "application/pdf")
        resp = c.post(f"{base}events/{ev['id']}/attachments/", {"file": pdf})
        assert resp.status_code == 201, resp.json()
        att = resp.json()["attachments"][0]
        assert att["name"] == "Einladung JHV.pdf"
        resp = c.get(att["url"])
        assert resp.status_code == 200 and b"".join(resp.streaming_content).startswith(b"%PDF")
        bad = SimpleUploadedFile("x.pdf", b"MZ ausfuehrbar", "application/pdf")
        resp = c.post(f"{base}events/{ev['id']}/attachments/", {"file": bad})
        assert resp.status_code == 400
        # Mitglied im Mitgliederbereich lädt den Anhang
        _, user, access = member_with_access(cal["a"], "Erika", depts=[zug])
        resp = api(user).get(f"/api/portal/{access.pk}/events/{ev['id']}/")
        assert resp.status_code == 200
        portal_url = resp.json()["attachments"][0]["url"]
        assert portal_url.startswith(f"/api/portal/{access.pk}/")
        assert api(user).get(portal_url).status_code == 200
        assert c.delete(att["url"]).status_code == 204
        assert c.get(att["url"]).status_code == 404

    def test_interner_termin_fuer_mitglied_unsichtbar(self, cal, board_a, zug, api):
        ev = create(api(board_a), org_base(cal["a"]), title="Intern", visibility="board")
        _, user, access = member_with_access(cal["a"], "Erika")
        assert api(user).get(f"/api/portal/{access.pk}/events/{ev['id']}/").status_code == 404


class TestOeffentlicherLink:
    def test_ein_aus_erneuern(self, cal, board_a, board_fed, api):
        c = api(board_a)
        base = org_base(cal["a"])
        create(c, base, title="Königsschießen", visibility="public", location="Schießstand")
        create(c, base, title="Nur Mitglieder")
        create(api(board_fed), org_base(cal["federation"]), title="BSV", visibility="public")
        assert c.get(f"{base}events/publication/").json()["is_public"] is False
        resp = c.put(f"{base}events/publication/", {"is_public": True}, content_type=JSON)
        data = resp.json()
        assert data["is_public"] and data["json_url"].endswith("/")
        anon = Client()
        key = CalendarPublication.objects.get().public_key
        resp = anon.get(f"/api/public/calendar/{key}/")
        assert resp.status_code == 200
        assert resp["Access-Control-Allow-Origin"] == "*"
        # Termine liegen in der Vergangenheit/Zukunft je nach Datum: Fenster prüfen
        events = resp.json()["events"]
        assert all(e["title"] == "Königsschießen" for e in events)
        assert "participants" not in str(resp.json())
        resp = anon.get(f"/api/public/calendar/{key}/termine.ics")
        assert resp.status_code == 200 and resp["Content-Type"].startswith("text/calendar")
        assert b"BEGIN:VCALENDAR" in resp.content
        # erneuern: alter Link ungültig
        c.put(f"{base}events/publication/", {"is_public": True, "renew": True}, content_type=JSON)
        assert anon.get(f"/api/public/calendar/{key}/").status_code == 404
        key2 = CalendarPublication.objects.get().public_key
        assert anon.get(f"/api/public/calendar/{key2}/").status_code == 200
        # ausschalten
        c.put(f"{base}events/publication/", {"is_public": False}, content_type=JSON)
        assert anon.get(f"/api/public/calendar/{key2}/").status_code == 404

    def test_zukuenftige_termine_im_feed(self, cal, board_a, api):
        start = timezone.localtime() + datetime.timedelta(days=10)
        create(
            api(board_a),
            org_base(cal["a"]),
            title="Kirmes",
            visibility="public",
            starts_at=start.replace(tzinfo=None).isoformat(),
            ends_at=(start + datetime.timedelta(hours=3)).replace(tzinfo=None).isoformat(),
        )
        api(board_a).put(
            f"{org_base(cal['a'])}events/publication/", {"is_public": True}, content_type=JSON
        )
        key = CalendarPublication.objects.get().public_key
        resp = Client().get(f"/api/public/calendar/{key}/")
        assert [e["title"] for e in resp.json()["events"]] == ["Kirmes"]
        ics = Client().get(f"/api/public/calendar/{key}/termine.ics").content.decode()
        assert "SUMMARY:Kirmes" in ics

    def test_abteilung_eigener_link(self, cal, zug, api):
        m, user, _ = member_with_access(cal["a"], "Zugführer", depts=[zug])
        dept_role(zug, m, ["dept.events.manage"])
        resp = api(user).put(
            f"/api/depts/{zug.pk}/events/publication/", {"is_public": True}, content_type=JSON
        )
        assert resp.status_code == 200 and resp.json()["is_public"]
        assert CalendarPublication.objects.get().department == zug


class TestJahresprogramm:
    def test_pdf(self, cal, board_a, board_fed, zug, api):
        create(api(board_a), org_base(cal["a"]), title="Königsschießen")
        create(api(board_a), org_base(cal["a"]), title="Intern", visibility="board")
        create(api(board_fed), org_base(cal["federation"]), title="Schützenfest")
        resp = api(board_a).get(f"{org_base(cal['a'])}events/program/?year=2026")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        _, user, access = member_with_access(cal["a"], "Erika", depts=[zug])
        resp = api(user).get(f"/api/portal/{access.pk}/events/program/?year=2026")
        assert resp.status_code == 200 and resp.content.startswith(b"%PDF")


def test_ical_zeilen_umbrechen_und_escapen(cal):
    from events import ical
    from events.recurrence import occurrences as occ

    event = Event.objects.create(
        organization=cal["a"],
        title="Fest; mit, Sonderzeichen " + "ä" * 60,
        description="Zeile 1\nZeile 2",
        starts_at=at(2026, 6, 1, 18),
        ends_at=at(2026, 6, 1, 20),
    )
    body = ical.calendar("Verein", occ([event], at(2026, 1, 1), at(2027, 1, 1)), "x").decode()
    assert "Fest\\; mit\\, Sonderzeichen" in body
    assert "Zeile 1\\nZeile 2" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    assert "DTSTART:20260601T160000Z" in body


def test_migration_schaltet_modul_und_rechte_frei():
    """Neue Vereine bekommen das Modul über die Standardmodule."""
    from access.catalog import SWITCHABLE_MODULES, codes_for

    assert "events" in SWITCHABLE_MODULES
    assert "events.manage" in codes_for("club")
    assert "events.manage" in codes_for("federation")


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_rls_dachverband_lesen_aber_nicht_schreiben(cal, board_a, board_b, board_fed, api):
    from django.db import DatabaseError, transaction

    from core.rls import APP_ROLE
    from core.tenancy import scope_of, set_rls

    create(api(board_fed), org_base(cal["federation"]), title="BSV")
    create(api(board_fed), org_base(cal["federation"]), title="BSV intern", visibility="board")
    create(api(board_a), org_base(cal["a"]), title="A")
    create(api(board_b), org_base(cal["b"]), title="B")
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        set_rls(cal["a"].pk, board_a.pk, False, scope_id=scope_of(cal["a"].pk))
        assert sorted(Event.objects.values_list("title", flat=True)) == ["A", "BSV"]
        with pytest.raises(DatabaseError), transaction.atomic():
            Event.objects.filter(title="BSV").update(title="gekapert")
        # Update trifft eine Zeile nicht, die nur gelesen werden darf → keine Änderung
        set_rls(cal["c"].pk, None, False, scope_id=scope_of(cal["c"].pk))
        assert list(Event.objects.values_list("title", flat=True)) == []
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_api_unter_rls_vorstand_abteilung_mitglied(cal, board_a, board_fed, zug, api):
    """Ende-zu-Ende in der eingeschränkten Rolle: alle drei Zugänge und der öffentliche Link."""
    from core.rls import APP_ROLE
    from core.tenancy import set_rls

    m, member, access = member_with_access(cal["a"], "Erika", depts=[zug])
    dept_role(zug, m, ["dept.events.manage"])
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        fed = create(
            api(board_fed), org_base(cal["federation"]), title="Schützenfest", visibility="public"
        )
        pdf = SimpleUploadedFile("plan.pdf", b"%PDF-1.4 erfunden", "application/pdf")
        resp = api(board_fed).post(
            f"{org_base(cal['federation'])}events/{fed['id']}/attachments/", {"file": pdf}
        )
        assert resp.status_code == 201
        create(api(board_a), org_base(cal["a"]), title="JHV")
        create(api(member), f"/api/depts/{zug.pk}/", title="Zugabend")
        assert sorted(titles(api(board_a), org_base(cal["a"]))) == [
            "JHV",
            "Schützenfest",
            "Zugabend",
        ]
        assert sorted(titles(api(member), f"/api/portal/{access.pk}/")) == [
            "JHV",
            "Schützenfest",
            "Zugabend",
        ]
        detail = api(member).get(f"/api/portal/{access.pk}/events/{fed['id']}/").json()
        assert api(member).get(detail["attachments"][0]["url"]).status_code == 200
        api(board_fed).put(
            f"{org_base(cal['federation'])}events/publication/",
            {"is_public": True},
            content_type=JSON,
        )
        resp = api(board_fed).get(f"{org_base(cal['federation'])}events/publication/")
        assert Client().get(resp.json()["json_url"]).status_code == 200
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)


@pytest.mark.langsam
def test_demo_termine_wiederholbar(db):
    from django.core.management import call_command

    call_command("seed_testdata", "--password", "Test-Passwort-123", stdout=None)
    count = Event.objects.count()
    assert count >= 8
    assert Event.objects.filter(department__isnull=False).count() == 2
    assert EventCategory.objects.filter(name="Versammlung").count() == 2
    call_command("seed_testdata", "--password", "Test-Passwort-123", stdout=None)
    assert Event.objects.count() == count
