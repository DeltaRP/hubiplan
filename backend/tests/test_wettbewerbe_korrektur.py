"""Erfasste Werte löschen und Starter entfernen, auch über den Abgleich des Standmodus
(Ralf 2026-11-01; alles erfunden)."""

import uuid

import pytest

from competitions.models import Score, Starter

from .test_wettbewerbe import _starter, club, schuetzen, url, zuege  # noqa: F401


@pytest.mark.django_db
def test_wert_loeschen_und_starter_entfernen(club, schuetzen, zuege, board_a, api):  # noqa: F811
    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "einfach"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    scoring = c.get(url(club, f"{comp_id}/")).json()["scorings"][0]["id"]
    max_ = _starter(c, club, comp_id, membership=schuetzen["Max"].pk)
    gast = _starter(c, club, comp_id, name="Gerd Gast")
    key = str(uuid.uuid4())
    ops = [
        {"op": "score", "starter": max_["id"], "scoring": scoring, "value": "27"},
        {"op": "score", "starter": gast["id"], "scoring": scoring, "value": "21"},
        # offline angelegt und gleich wieder entfernt
        {"op": "starter", "client_key": key, "name": "Vertippt"},
        {"op": "starter_delete", "starter": key},
        # Wert löschen, Starter entfernen
        {"op": "score", "starter": max_["id"], "scoring": scoring, "value": None},
        {"op": "starter_delete", "starter": gast["id"]},
        # zweites Senden und eine leere Kennung treffen niemanden
        {"op": "starter_delete", "starter": gast["id"]},
        {"op": "starter_delete", "starter": ""},
    ]
    resp = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops}, "application/json")
    assert resp.status_code == 200, resp.content
    results = resp.json()["results"]
    assert all(r["ok"] for r in results), results
    assert list(Starter.objects.filter(competition_id=comp_id).values_list("name", flat=True)) == [
        "Max Muster"
    ]
    assert not Score.objects.filter(starter_id=max_["id"]).exists()


@pytest.mark.django_db
def test_stand_aendert_sich_mit_jeder_eingabe(club, schuetzen, zuege, board_a, api):  # noqa: F811
    """Die Ansichten fragen den kleinen Stand ab und laden nur bei einer Änderung neu."""
    from rest_framework.test import APIClient

    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "schiessen"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    scoring = c.get(url(club, f"{comp_id}/")).json()["scorings"][0]["id"]
    seen = []

    def version():
        resp = c.get(url(club, f"{comp_id}/version/"))
        assert resp.status_code == 200
        seen.append(resp.json()["version"])
        return seen[-1]

    version()
    assert version() == seen[0]  # nichts geändert
    s = _starter(c, club, comp_id, membership=schuetzen["Max"].pk)
    assert version() != seen[-2]
    sync = url(club, f"{comp_id}/sync/")
    for value in ("27", "28", None):
        c.post(
            sync,
            {"ops": [{"op": "score", "starter": s["id"], "scoring": scoring, "value": value}]},
            "application/json",
        )
        assert version() != seen[-2], value
    c.patch(url(club, f"{comp_id}/starters/{s['id']}/"), {"number": "7"}, "application/json")
    assert version() != seen[-2]

    # Standzugang: Stand und Tabellen ohne Anmeldung
    token = c.post(url(club, f"{comp_id}/stand-access/"), {"label": "Tablet"}).json()["token"]
    pub = APIClient()
    base = f"/api/public/stand/{token}/"
    assert pub.get(f"{base}version/").json()["version"] == seen[-1]
    data = pub.get(f"{base}standings/").json()
    assert [b["name"] for b in data["scorings"]][0] == "Einzelwertung"
    assert "stats" not in data
