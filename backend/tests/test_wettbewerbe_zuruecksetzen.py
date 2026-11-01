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


@pytest.mark.django_db
def test_gast_fuer_einen_zug(club, zuege, board_a, api):  # noqa: F811
    """Ralf 2026-11-01: beim Gast freie Eingabe oder eine Untereinheit wählen."""
    import uuid

    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "einfach"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    key = str(uuid.uuid4())
    ops = [{"op": "starter", "client_key": key, "name": "Gina Gast", "unit": zuege[1].pk}]
    res = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops}, "application/json").json()
    assert res["results"][0]["ok"], res
    gina = next(s for s in res["starters"] if s["name"] == "Gina Gast")
    assert gina["guest"] and gina["unit"] == zuege[1].pk and gina["club"] == ""


@pytest.mark.django_db
def test_stechen_ueber_den_standzugang(club, schuetzen, zuege, board_a, api):  # noqa: F811
    """Ralf 2026-11-01: Stechen auch am geliehenen Tablet; Abschluss bleibt angemeldet."""
    from rest_framework.test import APIClient

    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "einfach"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    scoring = c.get(url(club, f"{comp_id}/")).json()["scorings"][0]["id"]
    for first in ("Max", "Erika"):
        s = _starter(c, club, comp_id, membership=schuetzen[first].pk)
        c.put(
            url(club, f"{comp_id}/scores/"),
            {"scoring": scoring, "starter": s["id"], "value": "27"},
            "application/json",
        )
    token = c.post(
        url(club, f"{comp_id}/stand-access/"), {"label": "Tablet 2"}, "application/json"
    ).json()["token"]
    anon = APIClient()
    base = f"/api/public/stand/{token}/"
    block = next(
        b for b in anon.get(f"{base}standings/").json()["scorings"] if b["scoring"] == scoring
    )
    keys = block["open"][0]["keys"]
    resp = anon.post(
        f"{base}shootoffs/", {"scoring": scoring, "keys": keys, "shots": 1}, format="json"
    )
    assert resp.status_code == 201, resp.content
    so = resp.json()
    assert so["shots"] == 1 and len(so["entries"]) == 2
    resp = anon.patch(f"{base}shootoffs/{so['id']}/", {"shots": 2}, format="json")
    assert resp.json()["shots"] == 2
    entry = so["entries"][0]["id"]
    resp = anon.patch(f"{base}shootoff-entries/{entry}/", {"value": "9"}, format="json")
    assert resp.status_code == 200, resp.content
    assert anon.get(f"{base}shootoffs/").json()[0]["entries"][0]["value"].startswith("9")
    # Zustand ändern geht über den Standzugang nicht
    assert anon.post(f"{base}status/", {"status": "endgueltig"}, format="json").status_code in (
        404,
        405,
    )
    # fremdes Stechen: nicht erreichbar
    assert (
        anon.patch(f"{base}shootoff-entries/999999/", {"value": "1"}, format="json").status_code
        == 404
    )


@pytest.mark.django_db(transaction=True)
def test_stechen_ohne_empfang_zwei_tablets(club, schuetzen, board_a, api):  # noqa: F811
    """Ralf 2026-11-01: Stechen muss zur Not auch ohne Empfang gehen. Zwei Tablets legen
    dasselbe Stechen an und tragen Werte nach; der Server führt zusammen."""
    import datetime
    import uuid

    now = datetime.datetime.now(datetime.UTC)

    def ago(seconds: int) -> str:
        return (now - datetime.timedelta(seconds=seconds)).isoformat()

    c = api(board_a)
    resp = c.post(
        url(club),
        {"title": "Preisschießen 2027", "date": "2027-06-14", "template": "einfach"},
        "application/json",
    )
    comp_id = resp.json()["id"]
    scoring = c.get(url(club, f"{comp_id}/")).json()["scorings"][0]["id"]
    for first in ("Max", "Erika"):
        s = _starter(c, club, comp_id, membership=schuetzen[first].pk)
        c.put(
            url(club, f"{comp_id}/scores/"),
            {"scoring": scoring, "starter": s["id"], "value": "27"},
            "application/json",
        )
    sync = url(club, f"{comp_id}/sync/")
    keys = c.get(url(club, f"{comp_id}/standings/")).json()["scorings"][0]["open"][0]["keys"]
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    # Tablet A: anlegen und gleich einen Wert, alles in einem Abgleich
    ops = [
        {"op": "shootoff", "client_key": a, "scoring": scoring, "keys": keys, "shots": 1},
        {
            "op": "shootoff_value",
            "shootoff": a,
            "key": keys[0],
            "value": "9",
            "at": ago(0),
        },
    ]
    res = c.post(sync, {"ops": ops}, "application/json").json()
    assert all(r["ok"] for r in res["results"]), res["results"]
    so_id = res["shootoff_keys"][a]
    assert res["shootoffs"][0]["id"] == so_id and res["shootoffs"][0]["shots"] == 1
    # Tablet B war ohne Netz: dasselbe Stechen mit anderer Regel, älterer Wert für keys[0]
    ops = [
        {"op": "shootoff", "client_key": b, "scoring": scoring, "keys": keys, "shots": 3},
        {
            "op": "shootoff_value",
            "shootoff": b,
            "key": keys[0],
            "value": "7",
            "at": ago(60),
        },
        {
            "op": "shootoff_value",
            "shootoff": b,
            "key": keys[1],
            "value": "8",
            "at": ago(30),
        },
    ]
    res = c.post(sync, {"ops": ops}, "application/json").json()
    assert all(r["ok"] for r in res["results"]), res["results"]
    assert res["shootoff_keys"][b] == so_id and len(res["shootoffs"]) == 1
    notes = " ".join(x.get("note", "") for x in res["conflicts"])
    assert "zusammengeführt" in notes and "andere Regeln" in notes and "später" in notes
    values = {e["key"]: e["value"] for e in res["shootoffs"][0]["entries"]}
    assert values[keys[0]].startswith("9") and values[keys[1]].startswith("8")
    # dieselben Eingaben noch einmal (Gerät hat die Antwort nicht bekommen): nichts doppelt
    res = c.post(sync, {"ops": ops[:1]}, "application/json").json()
    assert res["results"][0]["ok"] and len(res["shootoffs"]) == 1
