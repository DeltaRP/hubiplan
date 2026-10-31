"""Termin und Veranstaltungsfinanzen verbinden (H-AF-02)."""

import datetime

import pytest
from django.utils import timezone

from events.models import Event
from finance.models import Project

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
TZ = timezone.get_current_timezone()


def at(*args) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime(*args), TZ)


@pytest.fixture
def club(orgs):
    a = orgs["a"]
    a.enabled_modules = ["members", "events", "finance"]
    a.save()
    return a


@pytest.fixture
def fest(club):
    return Event.objects.create(
        organization=club,
        title="Schützenfest",
        starts_at=at(2026, 8, 29, 0, 0),
        ends_at=at(2026, 9, 1, 0, 0),
        all_day=True,
    )


def url(club, event, suffix=""):
    return f"/api/orgs/{club.pk}/events/{event.pk}/{suffix}"


def test_anlegen_zuordnen_loesen(api, club, fest, board_a):
    c = api(board_a)
    detail = c.get(url(club, fest)).json()
    assert detail["project"] is None
    assert detail["can_link_project"] is True

    resp = c.post(url(club, fest, "project/"), {"create": True}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    project = Project.objects.get()
    assert (project.name, project.starts_on, project.ends_on) == (
        "Schützenfest",
        datetime.date(2026, 8, 29),
        datetime.date(2026, 8, 31),
    )
    assert resp.json()["project"] == {"id": project.pk, "name": "Schützenfest"}

    other = Project.objects.create(organization=club, name="Kirmes", starts_on="2026-09-01")
    resp = c.post(url(club, fest, "project/"), {"project": other.pk}, content_type=JSON)
    assert resp.json()["project"]["name"] == "Kirmes"
    resp = c.post(url(club, fest, "project/"), {"project": None}, content_type=JSON)
    assert resp.json()["project"] is None


def test_fremde_veranstaltung_abgelehnt(api, club, fest, board_a, orgs):
    orgs["b"].enabled_modules = ["finance"]
    orgs["b"].save()
    foreign = Project.objects.create(organization=orgs["b"], name="X", starts_on="2026-01-01")
    resp = api(board_a).post(
        url(club, fest, "project/"), {"project": foreign.pk}, content_type=JSON
    )
    assert resp.status_code == 400


def test_ohne_kassenrecht(api, club, fest):
    user = make_user("termine@example.org")
    give_role(user, club, permissions=["events.manage"], name="Termine")
    c = api(user)
    assert "project" not in c.get(url(club, fest)).json()
    resp = c.post(url(club, fest, "project/"), {"create": True}, content_type=JSON)
    assert resp.status_code == 403
