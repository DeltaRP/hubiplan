"""Anstehende Geburtstage für die Kachel auf der Startseite (alles erfunden)."""

import datetime

import pytest

from members.birthdays import _birthday_in

from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
D = datetime.date


def url(org):
    return f"/api/orgs/{org.pk}/birthdays/"


def test_29_februar_im_normaljahr():
    assert _birthday_in(D(2000, 2, 29), 2027) == D(2027, 2, 28)
    assert _birthday_in(D(2000, 2, 29), 2028) == D(2028, 2, 29)


def test_geburtstage_im_zeitraum(api, orgs, board_a):
    types = make_types(orgs["a"])
    c = api(board_a)
    admit(c, orgs["a"], types["aktiv"], last_name="Bald", birth_date="1976-11-03")
    admit(c, orgs["a"], types["aktiv"], last_name="Spaeter", birth_date="1980-12-24")
    data = c.get(url(orgs["a"]), {"von": "2026-10-29", "bis": "2026-11-28"}).json()
    assert [(r["last_name"], r["date"], r["age"]) for r in data["results"]] == [
        ("Bald", "2026-11-03", 50)
    ]


def test_jahreswechsel(api, orgs, board_a):
    types = make_types(orgs["a"])
    c = api(board_a)
    admit(c, orgs["a"], types["aktiv"], last_name="Neujahr", birth_date="1970-01-02")
    data = c.get(url(orgs["a"]), {"von": "2026-12-20", "bis": "2027-01-19"}).json()
    assert [(r["date"], r["age"]) for r in data["results"]] == [("2027-01-02", 57)]


def test_nur_mit_leserecht(api, orgs, board_b):
    assert api(board_b).get(url(orgs["a"])).status_code in (403, 404)


def test_hoechstens_ein_jahr(api, orgs, board_a):
    resp = api(board_a).get(url(orgs["a"]), {"von": "2026-01-01", "bis": "2027-06-01"})
    assert resp.status_code == 400


def test_untereinheit_steht_dabei(api, orgs, board_a):
    from core.tenancy import tenant_context
    from organizations.models import Department

    from .factories import make_member

    club = orgs["a"]
    with tenant_context(club.pk):
        zug = Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)
    make_member(club, "Erika", "Zug", departments=[zug], birth_date=D(1976, 11, 3))
    make_member(club, "Otto", "Ohne", birth_date=D(1976, 11, 4))
    data = api(board_a).get(url(club), {"von": "2026-10-29", "bis": "2026-11-28"}).json()
    assert [(r["last_name"], r["units"]) for r in data["results"]] == [
        ("Zug", "Jägerzug"),
        ("Ohne", ""),
    ]
