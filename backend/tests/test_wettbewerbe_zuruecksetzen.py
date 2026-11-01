"""Wettbewerb zurücksetzen und nach dem letzten Pfand nicht weiterschießen
(Ralf 2026-11-01; alles erfunden)."""

import pytest

from audit.models import AuditEntry
from competitions.models import Competition, Prize, Score, Shot, Starter

from .test_wettbewerbe import _starter, club, schuetzen, url, zuege  # noqa: F401
from .test_wettbewerbe_vogel import _vogel


@pytest.mark.django_db(transaction=True)
def test_vogelschiessen_zuruecksetzen(club, board_a, api):  # noqa: F811
    c = api(board_a)
    comp_id, detail = _vogel(c, club)
    prizes = [p["id"] for p in detail["prizes"]]
    a = _starter(c, club, comp_id, name="Gerd Gast", number="1")
    b = _starter(c, club, comp_id, name="Hans Hilfe", number="2")
    gen = c.post(url(club, f"{comp_id}/sync/"), {"ops": []}, "application/json").json()
    assert gen["generation"] == 0
    # alle Pfänder fallen mit einem Schuss; danach zählt kein Schuss mehr
    resp = c.post(
        url(club, f"{comp_id}/shots/"), {"starter": a["id"], "hits": prizes}, "application/json"
    )
    assert resp.status_code == 201, resp.content
    resp = c.post(url(club, f"{comp_id}/shots/"), {"starter": b["id"]}, "application/json")
    assert resp.status_code == 400 and "Alle Pfänder" in str(resp.json())

    # nur Ergebnisse: Starter bleiben mit Losnummer, Pfänder hängen wieder
    resp = c.post(url(club, f"{comp_id}/reset/"), {"keep_starters": True}, "application/json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["deleted"] == {"Werte": 0, "Schüsse": 1, "Starter": 0}
    comp = Competition.objects.get(pk=comp_id)
    assert comp.status == "vorbereitung" and comp.generation == 1
    assert not Shot.objects.filter(competition=comp).exists()
    assert not any(p.fallen for p in Prize.objects.filter(competition=comp))
    assert sorted(Starter.objects.filter(competition=comp).values_list("number", flat=True)) == [
        "1",
        "2",
    ]
    assert any("zurückgesetzt" in (e.changes or {}) for e in AuditEntry.objects.all())

    # ein Gerät mit Eingaben von vor dem Zurücksetzen: verworfen
    ops = [{"op": "shot", "starter": a["id"], "hits": [], "client_key": None}]
    resp = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops, "generation": 0}, "application/json")
    assert resp.json()["results"][0]["ok"] is False and resp.json()["generation"] == 1
    assert not Shot.objects.filter(competition=comp).exists()

    # alles: auch die Starter
    resp = c.post(url(club, f"{comp_id}/reset/"), {}, "application/json")
    assert resp.json()["deleted"]["Starter"] == 2
    assert not Starter.objects.filter(competition=comp).exists()
    assert Prize.objects.filter(competition=comp).count() == len(prizes)


@pytest.mark.django_db
def test_rangliste_zuruecksetzen(club, schuetzen, board_a, api):  # noqa: F811
    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "einfach"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    scoring = c.get(url(club, f"{comp_id}/")).json()["scorings"][0]["id"]
    m = _starter(c, club, comp_id, membership=schuetzen["Max"].pk)
    c.put(
        url(club, f"{comp_id}/scores/"),
        {"scoring": scoring, "starter": m["id"], "value": "27"},
        "application/json",
    )
    assert Score.objects.filter(starter_id=m["id"]).exists()
    resp = c.post(url(club, f"{comp_id}/reset/"), {"keep_starters": True}, "application/json")
    assert resp.json()["deleted"]["Werte"] == 1
    assert not Score.objects.filter(starter_id=m["id"]).exists()
    assert Starter.objects.filter(pk=m["id"]).exists()
    # endgültig: nicht zurücksetzbar
    c.post(url(club, f"{comp_id}/status/"), {"status": "endgueltig"}, "application/json")
    assert c.post(url(club, f"{comp_id}/reset/"), {}, "application/json").status_code == 400


@pytest.mark.django_db
def test_zwei_tablets_legen_dasselbe_mitglied_an(club, schuetzen, board_a, api):  # noqa: F811
    """Ralf 2026-11-01: drei Tablets gleichzeitig. Legen zwei ohne Netz dasselbe Mitglied an,
    landen die Punkte beider beim selben Starter; der spätere Wert gilt."""
    import uuid

    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "einfach"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    scoring = c.get(url(club, f"{comp_id}/")).json()["scorings"][0]["id"]
    m = schuetzen["Max"].pk
    key_a, key_b = str(uuid.uuid4()), str(uuid.uuid4())
    sync = url(club, f"{comp_id}/sync/")
    tablet_a = [
        {"op": "starter", "client_key": key_a, "membership": m},
        {
            "op": "score",
            "starter": key_a,
            "scoring": scoring,
            "value": "25",
            "at": "2027-06-14T10:00:00Z",
        },
    ]
    tablet_b = [
        {"op": "starter", "client_key": key_b, "membership": m},
        {
            "op": "score",
            "starter": key_b,
            "scoring": scoring,
            "value": "28",
            "at": "2027-06-14T10:05:00Z",
        },
    ]
    assert all(
        r["ok"] for r in c.post(sync, {"ops": tablet_a}, "application/json").json()["results"]
    )
    res = c.post(sync, {"ops": tablet_b}, "application/json").json()
    assert all(r["ok"] for r in res["results"]), res["results"]
    assert any("zusammengeführt" in x.get("note", "") for x in res["conflicts"])
    assert res["keys"][key_a] == res["keys"][key_b]
    starters = Starter.objects.filter(competition_id=comp_id)
    assert starters.count() == 1
    assert str(Score.objects.get(starter=starters.get()).value).startswith("28")
    # später noch eine Eingabe von Tablet B mit seiner Kennung
    later = [{"op": "score", "starter": key_b, "scoring": scoring, "value": None}]
    assert c.post(sync, {"ops": later}, "application/json").json()["results"][0]["ok"]
    # direkt angelegt bleibt es bei der Meldung „schon eingetragen“
    resp = c.post(url(club, f"{comp_id}/starters/"), {"membership": m}, "application/json")
    assert resp.status_code == 400
