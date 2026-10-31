"""Gründungsjahr ist bei Untereinheiten freiwillig."""

import pytest

from organizations.models import Department

pytestmark = pytest.mark.django_db
JSON = "application/json"


def test_untereinheit_ohne_gruendungsjahr(api, orgs, board_a):
    c = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}/departments"
    resp = c.post(f"{base}/", {"name": "Herolde"}, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    assert resp.json()["founding_year"] is None
    resp = c.post(f"{base}/", {"name": "Jungschützen", "founding_year": None}, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    dep = resp.json()

    # Wert eintragen und wieder leeren
    url = f"{base}/{dep['id']}/"
    assert c.patch(url, {"founding_year": 1990}, content_type=JSON).json()["founding_year"] == 1990
    resp = c.patch(url, {"founding_year": None}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    assert Department.objects.get(pk=dep["id"]).founding_year is None

    # Untergrenze gilt weiter, wenn ein Wert eingetragen ist
    assert c.patch(url, {"founding_year": 500}, content_type=JSON).status_code == 400
