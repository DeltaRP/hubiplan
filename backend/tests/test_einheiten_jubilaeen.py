"""Einheiten Schritt 6: Jubiläen von Einheiten aus dem Gründungsjahr."""

import pytest

from organizations.models import Department

pytestmark = pytest.mark.django_db
JSON = "application/json"


def get(c, org, von, bis):
    resp = c.get(f"/api/orgs/{org.pk}/unit-jubilees/?von={von}&bis={bis}")
    assert resp.status_code == 200, resp.json()
    return resp.json()["results"]


def test_verein_und_untereinheiten(api, orgs, board_a):
    club = orgs["a"]
    club.founding_year = 1927
    club.save()
    zug = Department.objects.create(organization=club, name="Jägerzug", founding_year=1977)
    Department.objects.create(organization=club, parent=zug, name="Gruppe 1", founding_year=2017)
    Department.objects.create(organization=club, name="Alt", founding_year=1927, is_active=False)
    rows = get(api(board_a), club, "2027-01-01", "2027-12-31")
    assert [(r["path"], r["years"], r["year"]) for r in rows] == [
        (club.name, 100, 2027),
        ("Jägerzug", 50, 2027),
        ("Jägerzug › Gruppe 1", 10, 2027),
    ]
    assert rows[0]["kind"] == "self"
    # Eigene Bezeichnung mit Mehrzahl und Genus für Überschriften („Jubiläen der Züge“)
    assert {k: rows[1][k] for k in ("label", "label_plural", "label_gender")} == {
        "label": zug.label,
        "label_plural": zug.label_plural or zug.label,
        "label_gender": zug.label_gender,
    }
    # Jahresgenau: ein Tag im Jahr reicht
    assert len(get(api(board_a), club, "2027-12-31", "2028-01-01")) == 3
    assert get(api(board_a), club, "2028-01-01", "2028-12-31") == []


def test_eigene_stufen(api, orgs, board_a):
    club = orgs["a"]
    club.founding_year = 1916
    club.save()
    c = api(board_a)
    resp = c.patch(f"/api/orgs/{club.pk}/", {"unit_jubilee_years": [111, 11]}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["unit_jubilee_years"] == [11, 111]
    rows = get(c, club, "2027-01-01", "2027-12-31")
    assert [(r["name"], r["years"]) for r in rows] == [(club.name, 111)]


def test_dachverband_sieht_seine_vereine(api, orgs, board_a):
    from .factories import give_role, make_user

    fed = orgs["federation"]
    fed.founding_year = 1855
    fed.save()
    club = orgs["a"]
    club.founding_year = 1930
    club.save()
    user = make_user("verband@example.org")
    give_role(user, fed)
    rows = get(api(user), fed, "2030-01-01", "2030-12-31")
    assert [(r["name"], r["kind"], r["years"]) for r in rows] == [
        (fed.name, "self", 175),
        (club.name, "club", 100),
    ]


def test_ohne_rolle_kein_zugriff(api, orgs, board_b):
    assert api(board_b).get(f"/api/orgs/{orgs['a'].pk}/unit-jubilees/").status_code == 404
