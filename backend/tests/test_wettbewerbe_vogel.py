"""Wettbewerbe Schritte 2, 2b und 3: Vogelschießen, Standzugang, fremde Wettbewerbe
(alles erfunden).

Leitszenario Vogelschießen (Ralf, 2026-11-01): Pfänder Kopf, Flügel, Schweif, Rumpf;
gezählt werden Schüsse; wer ein Pfand hat, scheidet meist aus; die Reihenfolge kommt aus
Losnummern (Hut oder digital); Gäste möglich.
"""

import datetime
import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEntry
from competitions import bird
from competitions.models import Competition, Prize, Shot, StandAccess, Starter

from .factories import give_role, make_user
from .test_wettbewerbe import _starter, club, schuetzen, url, zuege  # noqa: F401


class S:
    """Starter-Ersatz für die reinen Rechenregeln."""

    def __init__(self, pk, number, presence=""):
        self.pk, self.number, self.presence, self.name = pk, number, presence, f"S{pk}"


class TestReihenfolge:
    def test_losnummern_ausscheiden_und_runden(self):
        starters = [S(1, "3"), S(2, "1"), S(3, "2"), S(4, ""), S(5, "4", "fehlt")]
        order = bird.shooting_order(starters, winners={3}, drop_out=True)
        assert [x.starter for x in order] == [2, 1]  # ohne Nummer, fehlend, ausgeschieden
        assert bird.next_after(order, None) == 0
        assert bird.next_after(order, 1) == 1  # nach Los 1 kommt Los 3
        assert bird.next_after(order, 2) == 1  # Los 2 ist ausgeschieden: weiter mit 3
        assert bird.next_after(order, 3) == 0  # neue Runde
        assert bird.rounds([1, 2, 3, 1, 3, 1]) == 3
        report = bird.draw_report([S(1, "1"), S(2, "1"), S(3, "4"), S(4, "")])
        assert report["duplicates"] == [{"number": 1, "names": ["S1", "S2"]}]
        assert report["gaps"] == [2, 3] and report["missing"] == ["S4"]


def _vogel(c, club):  # noqa: F811
    resp = c.post(
        url(club),
        {"title": "Vogelschießen 2027", "date": "2027-06-13", "template": "vogel"},
        "application/json",
    )
    assert resp.status_code == 201, resp.content
    comp_id = resp.json()["id"]
    detail = c.get(url(club, f"{comp_id}/")).json()
    assert detail["form"] == "vogel"
    return comp_id, detail


def _state(c, club, comp_id):  # noqa: F811
    resp = c.get(url(club, f"{comp_id}/bird/"))
    assert resp.status_code == 200, resp.content
    return resp.json()


@pytest.mark.django_db(transaction=True)
class TestVogelschiessen:
    def test_ablauf_live(self, club, schuetzen, zuege, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, detail = _vogel(c, club)
        assert [p["name"] for p in detail["prizes"]] == bird.PRIZE_TEMPLATE
        prizes = {p["name"]: p["id"] for p in detail["prizes"]}
        st = {f: _starter(c, club, comp_id, membership=m.pk) for f, m in schuetzen.items()}
        gast = _starter(c, club, comp_id, name="Gerd Gast", club="Nachbarverein")
        # Hut: Nummer eintragen; doppelte Nummer wird abgelehnt
        resp = c.post(
            url(club, f"{comp_id}/draw/"),
            {"starter": st["Max"]["id"], "number": 1},
            "application/json",
        )
        assert resp.status_code == 200 and resp.json()["number"] == 1
        resp = c.post(
            url(club, f"{comp_id}/draw/"),
            {"starter": st["Erika"]["id"], "number": "1"},
            "application/json",
        )
        assert resp.status_code == 400 and "Max Muster" in str(resp.json())
        # Digital: freie Nummer
        resp = c.post(
            url(club, f"{comp_id}/draw/"), {"starter": st["Erika"]["id"]}, "application/json"
        )
        assert resp.status_code == 200 and 2 <= resp.json()["number"] <= 8
        # Alle übrigen auf einmal
        resp = c.post(url(club, f"{comp_id}/draw-all/"), {}, "application/json")
        assert resp.json()["count"] == 6
        state = resp.json()["state"]
        numbers = sorted(int(s.number) for s in Starter.objects.filter(competition_id=comp_id))
        assert numbers == list(range(1, 9))
        assert state["draw"] == {"missing": [], "duplicates": [], "gaps": []}
        assert Starter.objects.get(pk=gast["id"]).drawn_how == "alle"
        # Losnummer per Bearbeiten: doppelt geht nicht
        other = Starter.objects.filter(competition_id=comp_id, number="2").get()
        resp = c.patch(
            url(club, f"{comp_id}/starters/{st['Max']['id']}/"), {"number": "2"}, "application/json"
        )
        assert resp.status_code == 400 and other.name in str(resp.json())

        by_number = {int(s.number): s.pk for s in Starter.objects.filter(competition_id=comp_id)}
        assert state["order"] == [by_number[n] for n in range(1, 9)]
        assert state["upcoming"][0] == by_number[1]

        def schuss(n, hits=()):
            resp = c.post(
                url(club, f"{comp_id}/shots/"),
                {"starter": by_number[n], "hits": [prizes[h] for h in hits]},
                "application/json",
            )
            assert resp.status_code == 201, resp.content
            return resp.json()

        for n in range(1, 9):
            state = schuss(n)
        assert state["shots"] == 8 and state["round"] == 1
        assert state["upcoming"][0] == by_number[1]
        schuss(1)
        state = schuss(2, ["Kopf"])
        kopf = next(p for p in state["prizes"] if p["name"] == "Kopf")
        assert kopf["shot_number"] == 10 and kopf["shots_for"] == 10 and kopf["live"]
        assert by_number[2] not in state["order"]  # scheidet aus
        assert state["upcoming"][0] == by_number[3]
        assert state["since_last"] == 0 and state["round"] == 2
        # Wer ausgeschieden ist, kann nicht mehr schießen
        resp = c.post(url(club, f"{comp_id}/shots/"), {"starter": by_number[2]}, "application/json")
        assert resp.status_code == 400
        # Zwei Pfänder mit einem Schuss
        schuss(3)
        state = schuss(4, ["linker Flügel", "rechter Flügel"])
        fl = [p for p in state["prizes"] if "Flügel" in p["name"]]
        assert {p["shots_for"] for p in fl} == {2} and {p["shot_number"] for p in fl} == {12}
        # Schon gefallen
        resp = c.post(
            url(club, f"{comp_id}/shots/"),
            {"starter": by_number[5], "hits": [prizes["Kopf"]]},
            "application/json",
        )
        assert resp.status_code == 400 and "schon gefallen" in str(resp.json())
        # Rückgängig: letzter Schuss mit beiden Flügeln
        state = c.post(url(club, f"{comp_id}/undo/"), {}, "application/json").json()
        assert state["shots"] == 11
        assert all(not p["fallen"] for p in state["prizes"] if "Flügel" in p["name"])
        assert state["upcoming"][0] == by_number[4]
        # Fehlt: wird übersprungen
        c.patch(
            url(club, f"{comp_id}/starters/{by_number[4]}/"),
            {"presence": "fehlt"},
            "application/json",
        )
        assert _state(c, club, comp_id)["upcoming"][0] == by_number[5]
        # Auswertung und Ausgaben
        standings = c.get(url(club, f"{comp_id}/standings/")).json()
        assert standings["bird"]["stats"]["shots"] == 11
        assert standings["bird"]["stats"]["rounds"] == 2
        for als in ("pdf", "losliste", "pfaenderliste"):
            resp = c.get(url(club, f"{comp_id}/export/?als={als}"))
            assert resp.status_code == 200 and resp.content[:4] == b"%PDF", als
        resp = c.get(url(club, f"{comp_id}/export/?als=xlsx"))
        assert resp.status_code == 200 and resp.content[:2] == b"PK"
        # Endgültig: nichts mehr
        c.post(url(club, f"{comp_id}/status/"), {"status": "endgueltig"}, "application/json")
        resp = c.post(url(club, f"{comp_id}/shots/"), {"starter": by_number[5]}, "application/json")
        assert resp.status_code == 400

    def test_lose_im_hut(self, club, board_a, api):  # noqa: F811
        """Ralf 2026-11-01: einzeln gezogen kam immer die nächste Nummer. Mit „Lose im Hut“
        zieht „Nummer ziehen“ aus allen freien Nummern bis zu dieser Zahl."""
        c = api(board_a)
        comp_id, _ = _vogel(c, club)
        resp = c.patch(url(club, f"{comp_id}/"), {"lots": 40}, "application/json")
        assert resp.status_code == 200 and resp.json()["lots"] == 40
        drawn = []
        for i in range(12):
            st = _starter(c, club, comp_id, name=f"Gast {i}")
            resp = c.post(url(club, f"{comp_id}/draw/"), {"starter": st["id"]}, "application/json")
            drawn.append(resp.json()["number"])
        assert len(set(drawn)) == 12 and all(1 <= n <= 40 for n in drawn)
        assert drawn != list(range(1, 13))  # Zufall: nicht der Reihe nach (p ≈ 1e-17)
        assert _state(c, club, comp_id)["draw"]["gaps"] == []  # Lücken sind hier normal

    def test_nachtraeglich_und_feste_reihenfolge(self, club, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, detail = _vogel(c, club)
        prizes = {p["name"]: p["id"] for p in detail["prizes"]}
        max_ = _starter(c, club, comp_id, membership=schuetzen["Max"].pk)
        resp = c.patch(
            url(club, f"{comp_id}/prizes/{prizes['Kopf']}/"),
            {"winner": max_["id"], "shot_number": 37},
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        kopf = next(p for p in resp.json()["prizes"] if p["name"] == "Kopf")
        assert kopf["winner_name"] == "Max Muster" and kopf["shots_for"] == 37
        c.patch(url(club, f"{comp_id}/"), {"total_shots": 140}, "application/json")
        state = _state(c, club, comp_id)
        assert state["shots"] == 140 and state["since_last"] == 103
        # Pfand umbenennen, hinzufügen, entfernen
        resp = c.post(url(club, f"{comp_id}/prizes/"), {"name": "Zepter"}, "application/json")
        assert resp.status_code == 201
        resp = c.delete(url(club, f"{comp_id}/prizes/{prizes['Kopf']}/"))
        assert resp.status_code == 400  # schon gefallen
        resp = c.delete(url(club, f"{comp_id}/prizes/{prizes['Rumpf']}/"))
        assert resp.status_code == 200
        # Feste Reihenfolge: als Nächstes fällt der linke Flügel
        c.patch(url(club, f"{comp_id}/"), {"fixed_order": True}, "application/json")
        erika = _starter(c, club, comp_id, membership=schuetzen["Erika"].pk, number="1")
        resp = c.post(
            url(club, f"{comp_id}/shots/"),
            {"starter": erika["id"], "hits": [prizes["Schweif"]]},
            "application/json",
        )
        assert resp.status_code == 400 and "linker Flügel" in str(resp.json())
        # Form lässt sich nicht ändern, Wertungen gibt es nicht
        resp = c.patch(url(club, f"{comp_id}/"), {"form": "rangliste"}, "application/json")
        assert resp.status_code == 400
        resp = c.post(url(club, f"{comp_id}/scorings/"), {"name": "X"}, "application/json")
        assert resp.status_code == 400

    def test_offline_abgleich(self, club, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, detail = _vogel(c, club)
        kopf = detail["prizes"][0]["id"]
        gast_key = str(uuid.uuid4())
        shot1, shot2 = str(uuid.uuid4()), str(uuid.uuid4())
        ops = [
            {"op": "starter", "client_key": gast_key, "name": "Gerd Gast"},
            {"op": "draw", "starter": gast_key, "number": 1, "how": "hut"},
            {"op": "starter", "client_key": str(uuid.uuid4()), "membership": schuetzen["Max"].pk},
            {"op": "shot", "starter": gast_key, "hits": [], "client_key": shot1},
            {"op": "shot", "starter": gast_key, "hits": [kopf], "client_key": shot2},
            {"op": "undo", "client_key": shot2},
            {"op": "shot", "starter": gast_key, "hits": [kopf], "client_key": str(uuid.uuid4())},
        ]
        resp = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops}, "application/json")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert all(r["ok"] for r in data["results"]), data["results"]
        assert data["bird"]["shots"] == 2
        assert data["bird"]["prizes"][0]["winner_name"] == "Gerd Gast"
        # Noch einmal gesendet: nichts doppelt; Rücknahme eines älteren Schusses geht nicht
        again = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops[:5]}, "application/json")
        assert Shot.objects.filter(competition_id=comp_id).count() == 2
        assert again.json()["bird"]["shots"] == 2
        resp = c.post(
            url(club, f"{comp_id}/sync/"),
            {"ops": [{"op": "undo", "client_key": shot1}]},
            "application/json",
        )
        assert resp.json()["results"][0]["ok"] is False
        # Digital gezogene Nummer, die inzwischen vergeben ist: neu ziehen und melden
        max_id = Starter.objects.get(competition_id=comp_id, membership=schuetzen["Max"]).pk
        resp = c.post(
            url(club, f"{comp_id}/sync/"),
            {"ops": [{"op": "draw", "starter": max_id, "number": 1, "how": "digital"}]},
            "application/json",
        )
        assert resp.json()["conflicts"][0]["number"] != 1


@pytest.mark.django_db(transaction=True)
class TestStandzugang:
    def test_zugang_ohne_anmeldung(self, club, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, detail = _vogel(c, club)
        resp = c.post(
            url(club, f"{comp_id}/stand-access/"), {"label": "Tablet 1"}, "application/json"
        )
        assert resp.status_code == 201, resp.content
        token = resp.json()["token"]
        access_id = resp.json()["id"]
        assert StandAccess.objects.get(pk=access_id).token_hash != token
        anon = APIClient()
        base = f"/api/public/stand/{token}/"
        d = anon.get(base)
        assert d.status_code == 200 and d.json()["title"] == "Vogelschießen 2027"
        assert d.json()["can_manage"] is False and d.json()["description"] == ""
        members = anon.get(f"{base}members/").json()
        assert {m["name"] for m in members} >= {"Max Muster"}
        assert all(m["birth_year"] is None for m in members)
        key = str(uuid.uuid4())
        resp = anon.post(
            f"{base}sync/",
            {
                "ops": [
                    {"op": "starter", "client_key": key, "membership": schuetzen["Max"].pk},
                    {"op": "draw", "starter": key, "number": 1},
                    {"op": "shot", "starter": key, "hits": [detail["prizes"][0]["id"]]},
                ]
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert all(r["ok"] for r in resp.json()["results"]), resp.json()
        assert anon.get(f"{base}starters/").json()[0]["name"] == "Max Muster"
        entry = AuditEntry.objects.filter(
            organization=club, object_type__icontains="schuss"
        ).first()
        assert entry is None or entry.user is None
        assert AuditEntry.objects.filter(organization=club, via="Standzugang Tablet 1").exists()
        # Nicht an andere Wettbewerbe oder die Verwaltung
        assert anon.get(url(club, f"{comp_id}/")).status_code in (401, 403)
        # Beenden
        assert c.delete(url(club, f"{comp_id}/stand-access/{access_id}/")).status_code == 204
        assert anon.get(base).status_code == 404
        assert anon.get("/api/public/stand/falsch/").status_code == 404

    def test_ablauf_und_rechte(self, club, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, _ = _vogel(c, club)
        comp = Competition.objects.get(pk=comp_id)
        access, token = StandAccess.create(
            comp, "", None, timezone.now() - datetime.timedelta(minutes=1)
        )
        assert APIClient().get(f"/api/public/stand/{token}/").status_code == 404
        access.expires_at = timezone.now() + datetime.timedelta(hours=1)
        access.save()
        assert APIClient().get(f"/api/public/stand/{token}/").status_code == 200
        club.enabled_modules = ["members"]
        club.save()
        assert APIClient().get(f"/api/public/stand/{token}/").status_code == 404
        club.enabled_modules = ["members", "competitions"]
        club.save()
        helfer = make_user("schiessmeister@example.org")
        give_role(helfer, club, ["competitions.results"], name="Schießmeister")
        resp = api(helfer).post(url(club, f"{comp_id}/stand-access/"), {}, "application/json")
        assert resp.status_code == 403
        # Gültig bis zum Ende des Wettbewerbstags
        resp = c.post(url(club, f"{comp_id}/stand-access/"), {}, "application/json")
        until = datetime.datetime.fromisoformat(resp.json()["expires_at"])
        assert timezone.localtime(until).date() == datetime.date(2027, 6, 13)


@pytest.mark.django_db(transaction=True)
class TestFremderWettbewerb:
    def test_eigene_plaetze_eintragen(self, club, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        resp = c.post(
            url(club),
            {
                "title": "Bezirksschießen 2027",
                "date": "2027-05-02",
                "organizer": "Dachverband",
                "template": "fremd",
            },
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        comp_id = resp.json()["id"]
        detail = c.get(url(club, f"{comp_id}/")).json()
        assert detail["own"] is False
        einzel, mannschaft = detail["scorings"]
        assert mannschaft["kind"] == "mannschaft"
        c.patch(
            url(club, f"{comp_id}/scorings/{einzel['id']}/"),
            {"field_size": 40},
            "application/json",
        )
        st = {f: _starter(c, club, comp_id, membership=m.pk) for f, m in schuetzen.items()}
        teams = c.get(url(club, f"{comp_id}/teams/")).json()
        assert teams[0]["name"] == "Mannschaft 1"
        resp = c.patch(
            url(club, f"{comp_id}/teams/{teams[0]['id']}/"),
            {"members": [st["Max"]["id"], st["Erika"]["id"]]},
            "application/json",
        )
        assert resp.status_code == 200 and len(resp.json()["members"]) == 2
        put = lambda data: c.put(url(club, f"{comp_id}/placings/"), data, "application/json")  # noqa: E731
        assert (
            put(
                {"scoring": einzel["id"], "starter": st["Max"]["id"], "place": 2, "value": "29"}
            ).status_code
            == 200
        )
        assert (
            put({"scoring": einzel["id"], "starter": st["Erika"]["id"], "place": 41}).status_code
            == 400
        )
        assert (
            put({"scoring": mannschaft["id"], "team": teams[0]["id"], "place": 1}).status_code
            == 200
        )
        data = c.get(url(club, f"{comp_id}/standings/")).json()
        rows = data["scorings"][0]["rows"]
        assert rows[0]["name"] == "Max Muster" and rows[0]["place"] == 2
        assert data["scorings"][1]["rows"][0]["members"] == ["Erika Beispiel", "Max Muster"]
        for als in ("pdf", "xlsx"):
            assert c.get(url(club, f"{comp_id}/export/?als={als}")).status_code == 200
        # Mannschaftswertung gibt es nur bei fremden Wettbewerben
        own = c.post(url(club), {"title": "X", "date": "2027-01-01"}, "application/json").json()
        resp = c.post(
            url(club, f"{own['id']}/scorings/"),
            {"name": "M", "kind": "mannschaft"},
            "application/json",
        )
        assert resp.status_code == 400
        # Kopie fürs nächste Jahr: Mannschaften kommen mit
        new = c.post(url(club, f"{comp_id}/copy/"), {}, "application/json").json()
        assert c.get(url(club, f"{new['id']}/teams/")).json()[0]["name"] == "Mannschaft 1"
        assert Prize.objects.filter(competition_id=new["id"]).count() == 0


@pytest.mark.django_db(transaction=False)
def test_standzugang_unter_rls(club, schuetzen, board_a, api):  # noqa: F811
    """Wie im Betrieb in der eingeschränkten Rolle: der Standzugang sieht seine Einheit."""
    from django.db import connection

    from .test_rls import as_app_role

    if connection.vendor != "postgresql":
        pytest.skip("Row-Level Security gibt es nur in PostgreSQL")
    c = api(board_a)
    comp_id, detail = _vogel(c, club)
    _, token = StandAccess.create(
        Competition.objects.get(pk=comp_id),
        "Tablet",
        None,
        timezone.now() + datetime.timedelta(hours=2),
    )
    anon = APIClient()
    base = f"/api/public/stand/{token}/"
    with as_app_role():
        assert anon.get(base).status_code == 200
        assert len(anon.get(f"{base}members/").json()) == len(schuetzen)
        key = str(uuid.uuid4())
        resp = anon.post(
            f"{base}sync/",
            {
                "ops": [
                    {"op": "starter", "client_key": key, "membership": schuetzen["Max"].pk},
                    {"op": "draw", "starter": key, "number": 1},
                    {"op": "shot", "starter": key, "hits": [detail["prizes"][0]["id"]]},
                ]
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert all(r["ok"] for r in resp.json()["results"]), resp.json()
        assert resp.json()["bird"]["prizes"][0]["winner_name"] == "Max Muster"
