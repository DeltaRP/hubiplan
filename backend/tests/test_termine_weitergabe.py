"""Termine: Weitergabe nach oben und unten (Schalter je Einheit, Abweichung je Termin)."""

import pytest

from events.models import Event
from organizations.models import Department

from .factories import give_role, make_user
from .test_m12_events import create, dept_role, member_with_access, org_base, titles

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def cal(orgs):
    for org in orgs.values():
        org.enabled_modules = ["members", "events"]
        org.member_portal_enabled = True
        org.department_access_enabled = True
        org.save()
    return orgs


@pytest.fixture
def zug(cal):
    return Department.objects.create(self_managed=True, organization=cal["a"], name="Jägerzug")


@pytest.fixture
def board_fed(cal):
    user = make_user("vorstand-bund@example.org")
    give_role(user, cal["federation"])
    return user


def dept_base(dept) -> str:
    return f"/api/depts/{dept.pk}/"


class TestVoreinstellung:
    def test_wie_bisher(self, cal, zug):
        assert zug.events_share_up and zug.events_share_down
        assert not cal["a"].events_share_up and cal["a"].events_share_down

    def test_verein_gibt_nach_oben(self, cal, board_a, board_fed, api):
        create(api(board_a), org_base(cal["a"]), title="Schützenfest")
        create(api(board_a), org_base(cal["a"]), title="Intern", visibility="board")
        fed = api(board_fed)
        assert "Schützenfest" not in titles(fed, org_base(cal["federation"]))
        resp = api(board_a).patch(
            f"{org_base(cal['a'])}events/sharing/", {"share_up": True}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["up_possible"] is True
        got = titles(fed, org_base(cal["federation"]))
        assert "Schützenfest" in got and "Intern" not in got
        # Der Dachverband kann den Termin nicht bearbeiten
        ev = Event.objects.get(title="Schützenfest")
        resp = fed.patch(
            f"{org_base(cal['federation'])}events/{ev.pk}/", {"title": "x"}, content_type=JSON
        )
        assert resp.status_code in (403, 404)

    def test_einzelner_termin_weicht_ab(self, cal, board_a, board_fed, api):
        c = api(board_a)
        create(c, org_base(cal["a"]), title="Nur dieser", share_up=True)
        create(c, org_base(cal["a"]), title="Standard")
        got = titles(api(board_fed), org_base(cal["federation"]))
        assert got == ["Nur dieser"]

    def test_dachverband_nach_unten_aus(self, cal, board_a, board_fed, api):
        create(api(board_fed), org_base(cal["federation"]), title="Bundesfest")
        create(api(board_fed), org_base(cal["federation"]), title="Für alle", share_down=True)
        assert "Bundesfest" in titles(api(board_a), org_base(cal["a"]))
        api(board_fed).patch(
            f"{org_base(cal['federation'])}events/sharing/",
            {"share_down": False},
            content_type=JSON,
        )
        got = titles(api(board_a), org_base(cal["a"]))
        assert "Bundesfest" not in got and "Für alle" in got


class TestUntereinheiten:
    def test_zug_nach_oben_aus_entscheidet_verein(self, cal, zug, board_a, api):
        m, user, _ = member_with_access(cal["a"], "Zugi", depts=[zug])
        role = dept_role(zug, m, ["dept.members.view"])  # ohne Kalenderrecht
        assert role
        c = api(user)
        resp = c.get(f"{dept_base(zug)}events/sharing/")
        assert resp.status_code == 200
        assert resp.json()["editable"] is False

        board = api(board_a)
        Event.objects.create(
            organization=cal["a"],
            department=zug,
            title="Zugabend",
            starts_at="2026-05-01T18:00:00+02:00",
            ends_at="2026-05-01T22:00:00+02:00",
        )
        assert "Zugabend" in titles(board, org_base(cal["a"]))
        data = board.get(f"{org_base(cal['a'])}events/sharing/").json()
        assert [u["name"] for u in data["units"]] == ["Jägerzug"]
        assert data["units"][0]["own_admin"] is False
        resp = board.patch(
            f"{org_base(cal['a'])}events/sharing/",
            {"units": [{"id": zug.pk, "share_up": False}]},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert "Zugabend" not in titles(board, org_base(cal["a"]))

    def test_zug_mit_eigener_verwaltung_entscheidet_selbst(self, cal, zug, board_a, api):
        m, user, _ = member_with_access(cal["a"], "Zugi", depts=[zug])
        dept_role(zug, m, ["dept.events.manage"])
        c = api(user)
        data = c.get(f"{dept_base(zug)}events/sharing/").json()
        assert data["editable"] is True
        resp = c.patch(f"{dept_base(zug)}events/sharing/", {"share_up": False}, content_type=JSON)
        assert resp.status_code == 200
        zug.refresh_from_db()
        assert zug.events_share_up is False
        # Der Verein kann es dann nicht mehr ändern
        board = api(board_a)
        assert board.get(f"{org_base(cal['a'])}events/sharing/").json()["units"][0]["own_admin"]
        resp = board.patch(
            f"{org_base(cal['a'])}events/sharing/",
            {"units": [{"id": zug.pk, "share_up": True}]},
            content_type=JSON,
        )
        assert resp.status_code == 403

    def test_verein_nach_unten_aus(self, cal, zug, board_a, api):
        create(api(board_a), org_base(cal["a"]), title="Vereinsfest")
        m, user, access = member_with_access(cal["a"], "Zugi", depts=[zug])
        dept_role(zug, m, ["dept.events.manage"])
        assert "Vereinsfest" in titles(api(user), dept_base(zug))
        api(board_a).patch(
            f"{org_base(cal['a'])}events/sharing/", {"share_down": False}, content_type=JSON
        )
        assert "Vereinsfest" not in titles(api(user), dept_base(zug))
        # Mitglieder des Vereins sehen seine Termine trotzdem
        assert "Vereinsfest" in titles(api(user), f"/api/portal/{access.pk}/")

    def test_ohne_recht_keine_aenderung(self, cal, zug, api):
        m, user, _ = member_with_access(cal["a"], "Zugi", depts=[zug])
        dept_role(zug, m, ["dept.members.view"])
        resp = api(user).patch(
            f"{dept_base(zug)}events/sharing/", {"share_up": False}, content_type=JSON
        )
        assert resp.status_code == 403
