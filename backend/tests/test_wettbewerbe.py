"""Wettbewerbe: Rangliste, Zugwertung, Stechen, Erfassung und Auswertung (alles erfunden).

Leitszenario (Ralf, 2026-11-01): eigenes Schießen, Schützen aus allen Mitgliedern und
Gäste, Einzel- und Zugwertung (Summe der besten k; Zug mit weniger als k Schützen wird
nicht gewertet), Stechen nur bei Gleichstand auf Preisplätzen, im Zugstechen je ein
Mitglied des Zuges.
"""

import datetime
from decimal import Decimal

import pytest

from competitions import ranking
from competitions.models import Competition, Score, Scoring, Starter
from organizations.models import Department

from .factories import give_role, make_member, make_user

D = Decimal


def E(key, value, ooc=False):  # noqa: N802
    return ranking.Entry(key, None if value is None else D(value), ooc)


class TestRangliste:
    def test_reihenfolge_und_gleicher_platz_ausserhalb_der_preise(self):
        res = ranking.rank(
            [E("a", 27), E("b", 29), E("c", 25), E("d", 25), E("e", None)], prize_places=2
        )
        assert [(p.key, p.place) for p in res.placed] == [
            ("b", 1),
            ("a", 2),
            ("c", 3),
            ("d", 3),
        ]
        assert res.open == [] and res.unranked == ["e"]

    def test_gleichstand_auf_preisplatz_braucht_stechen(self):
        res = ranking.rank([E("a", 28), E("b", 28), E("c", 20)], prize_places=3)
        assert [p.place for p in res.placed] == [1, 1, 3]
        assert (
            len(res.open) == 1 and res.open[0].keys == ["a", "b"] and res.open[0].shootoff is None
        )

    def test_gleichstand_ragt_in_preisplaetze(self):
        # Platz 2 und 3 gleich, 2 Preisplätze: Stechen nötig
        res = ranking.rank([E("a", 30), E("b", 28), E("c", 28)], prize_places=2)
        assert res.open[0].keys == ["b", "c"] and res.open[0].place == 2

    def test_stechen_entscheidet_und_laeuft(self):
        entries = [E("a", 28), E("b", 28), E("c", 28)]
        laeuft = ranking.rank(
            entries, prize_places=3, shootoffs=[(1, {"a": D(9), "b": None, "c": D(7)})]
        )
        assert laeuft.open[0].shootoff == 1
        fertig = ranking.rank(
            entries, prize_places=3, shootoffs=[(1, {"a": D(9), "b": D(10), "c": D(7)})]
        )
        assert [(p.key, p.place) for p in fertig.placed] == [("b", 1), ("a", 2), ("c", 3)]
        assert fertig.open == [] and fertig.placed[0].shootoff_values == {1: D(10)}

    def test_zweites_stechen_bei_erneutem_gleichstand(self):
        entries = [E("a", 28), E("b", 28), E("c", 28)]
        erstes = (1, {"a": D(9), "b": D(9), "c": D(7)})
        res = ranking.rank(entries, prize_places=3, shootoffs=[erstes])
        assert res.open[0].keys == ["a", "b"] and res.open[0].shootoff is None
        res = ranking.rank(
            entries, prize_places=3, shootoffs=[erstes, (2, {"a": D(8), "b": D(10)})]
        )
        assert [(p.key, p.place) for p in res.placed] == [("b", 1), ("a", 2), ("c", 3)]

    def test_kleiner_ist_besser_und_ausser_konkurrenz(self):
        res = ranking.rank([E("a", 12), E("b", 9), E("c", 5, ooc=True)], higher_better=False)
        assert [p.key for p in res.placed] == ["b", "a"] and res.unranked == ["c"]

    def test_zugwert_summe_der_besten(self):
        members = [E("s1", 28), E("s2", 30), E("s3", 20), E("s4", 25)]
        tv = ranking.team_value(members, mode="beste", size=3)
        assert tv.value == D(83) and sorted(tv.counted) == ["s1", "s2", "s4"]
        zu_wenig = ranking.team_value(members[:2], mode="beste", size=3)
        assert zu_wenig.value is None and zu_wenig.reason == "nur 2 von 3 Schützen"
        assert ranking.team_value(members, mode="summe", size=None).value == D(103)
        assert ranking.team_value(members, mode="durchschnitt", size=None).value == D("25.750")


pytestmark_db = pytest.mark.django_db(transaction=True)


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/competitions/{rest}"


@pytest.fixture
def club(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "competitions"]
    org.save()
    return org


@pytest.fixture
def zuege(club):
    return {
        n: Department.objects.create(organization=club, parent=club, name=f"Zug {n}")
        for n in (1, 2, 3)
    }


@pytest.fixture
def schuetzen(club, zuege):
    out = {}
    names = [
        ("Max", "Muster", 1),
        ("Erika", "Beispiel", 1),
        ("Otto", "Normal", 1),
        ("Jürgen", "Müller", 2),
        ("Anna", "Schmidt", 2),
        ("Paul", "Weber", 2),
        ("Lena", "Kraus", 3),
    ]
    for first, last, zug in names:
        out[first] = make_member(club, first, last, departments=[zuege[zug]])
    return out


def _starter(c, org, comp_id, **data):
    resp = c.post(url(org, f"{comp_id}/starters/"), data, "application/json")
    assert resp.status_code == 201, resp.content
    return resp.json()


def _punkte(c, club, comp_id, scoring, starter, value):
    resp = c.put(
        url(club, f"{comp_id}/scores/"),
        {"scoring": scoring, "starter": starter, "value": value},
        "application/json",
    )
    return resp


@pytest.mark.django_db(transaction=True)
class TestPreisschiessen:
    def _anlegen(self, c, club):
        resp = c.post(
            url(club),
            {
                "title": "Preisschießen 2027",
                "occasion": "Schützenfest",
                "discipline": "Luftgewehr",
                "location": "Schießstand",
                "date": "2027-06-14",
                "details": [{"label": "Entfernung", "value": "10 m"}],
                "template": "schiessen",
            },
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        comp_id = resp.json()["id"]
        detail = c.get(url(club, f"{comp_id}/")).json()
        einzel, zug = detail["scorings"]
        assert einzel["kind"] == "einzel" and zug["kind"] == "einheit"
        # Hier: 3 Preisplätze einzeln, 2 in der Zugwertung, je Zug die besten 2
        c.patch(
            url(club, f"{comp_id}/scorings/{einzel['id']}/"),
            {"prize_places": 3},
            "application/json",
        )
        c.patch(
            url(club, f"{comp_id}/scorings/{zug['id']}/"),
            {"team_size": 2, "prize_places": 2},
            "application/json",
        )
        return comp_id, einzel["id"], zug["id"]

    def test_ablauf_mit_zugwertung_und_stechen(self, club, schuetzen, zuege, board_a, api):
        c = api(board_a)
        comp_id, einzel, zug = self._anlegen(c, club)
        st = {}
        for first, m in schuetzen.items():
            st[first] = _starter(c, club, comp_id, membership=m.pk)
        assert st["Max"]["unit"] == zuege[1].pk  # Zug kommt aus der Untereinheit
        gast = _starter(c, club, comp_id, name="Gerd Gast", club="Nachbarverein")
        assert gast["guest"] and gast["unit"] is None
        punkte = {
            "Max": 29,
            "Erika": 27,
            "Otto": 20,
            "Jürgen": 29,
            "Anna": 27,
            "Paul": 25,
            "Lena": 30,
        }
        for first, p in punkte.items():
            assert _punkte(c, club, comp_id, einzel, st[first]["id"], p).status_code == 200
        assert _punkte(c, club, comp_id, einzel, gast["id"], "18").status_code == 200
        # Höchstwert 3 gewertete Schuss × 10
        assert _punkte(c, club, comp_id, einzel, gast["id"], 31).status_code == 400
        assert _punkte(c, club, comp_id, einzel, gast["id"], "18,5").status_code == 400
        assert Competition.objects.get(pk=comp_id).status == "laeuft"

        data = c.get(url(club, f"{comp_id}/standings/")).json()
        ein, zw = data["scorings"]
        assert [(r["name"], r["place"]) for r in ein["rows"][:3]] == [
            ("Lena Kraus", 1),
            ("Jürgen Müller", 2),
            ("Max Muster", 2),
        ]
        assert ein["open"][0]["names"] == ["Max Muster", "Jürgen Müller"] or sorted(
            ein["open"][0]["names"]
        ) == ["Jürgen Müller", "Max Muster"]
        # Zug 1: 29+27=56, Zug 2: 29+27=56, Zug 3: nur 1 Schütze → nicht gewertet
        assert [(r["name"], r["place"], r["value_text"]) for r in zw["rows"]] == [
            ("Zug 1", 1, "56"),
            ("Zug 2", 1, "56"),
            ("Zug 3", None, ""),
        ]
        assert zw["rows"][2]["reason"] == "nur 1 von 2 Schützen"
        assert len(zw["open"]) == 1 and data["open_shootoffs"] == 2

        # Endgültig erst ohne offene Stechen
        resp = c.post(url(club, f"{comp_id}/status/"), {"status": "endgueltig"}, "application/json")
        assert resp.status_code == 400

        # Einzelstechen
        so = c.post(
            url(club, f"{comp_id}/shootoffs/"),
            {"scoring": einzel, "keys": ein["open"][0]["keys"]},
            "application/json",
        ).json()
        assert so["shots"] == 3 and len(so["entries"]) == 2
        by_name = {e["name"]: e for e in so["entries"]}
        c.patch(
            url(club, f"{comp_id}/shootoff-entries/{by_name['Max Muster']['id']}/"),
            {"value": 28},
            "application/json",
        )
        c.patch(
            url(club, f"{comp_id}/shootoff-entries/{by_name['Jürgen Müller']['id']}/"),
            {"value": 26},
            "application/json",
        )
        # Zugstechen: je Zug ein Mitglied, vorgeschlagen der beste Schütze des Zuges
        zso = c.post(
            url(club, f"{comp_id}/shootoffs/"),
            {"scoring": zug, "keys": zw["open"][0]["keys"]},
            "application/json",
        ).json()
        assert zso["shots"] == 1
        by_unit = {e["unit"]: e for e in zso["entries"]}
        assert by_unit[zuege[1].pk]["name"] == "Max Muster"
        # Zug 2 schickt Paul statt des Besten (darf auch jemand sein, der nicht geschossen hat)
        resp = c.patch(
            url(club, f"{comp_id}/shootoff-entries/{by_unit[zuege[2].pk]['id']}/"),
            {"membership": schuetzen["Paul"].pk, "value": 10},
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        bad = c.patch(
            url(club, f"{comp_id}/shootoff-entries/{by_unit[zuege[1].pk]['id']}/"),
            {"value": 11},
            "application/json",
        )
        assert bad.status_code == 400  # 1 Schuss, höchstens 10
        c.patch(
            url(club, f"{comp_id}/shootoff-entries/{by_unit[zuege[1].pk]['id']}/"),
            {"value": 9},
            "application/json",
        )
        data = c.get(url(club, f"{comp_id}/standings/")).json()
        ein, zw = data["scorings"]
        assert [(r["name"], r["place"]) for r in ein["rows"][:3]] == [
            ("Lena Kraus", 1),
            ("Max Muster", 2),
            ("Jürgen Müller", 3),
        ]
        # Gleichstand außerhalb der Preise (Erika, Anna 27 → Platz 4) bleibt geteilt
        assert {r["name"]: r["place"] for r in ein["rows"]}["Anna Schmidt"] == 4
        assert {r["name"]: r["place"] for r in ein["rows"]}["Erika Beispiel"] == 4
        assert [(r["name"], r["place"]) for r in zw["rows"][:2]] == [("Zug 2", 1), ("Zug 1", 2)]
        assert data["open_shootoffs"] == 0
        stats = data["stats"]
        assert stats["count"] == 8 and stats["guests"] == 1 and stats["members"] == 7
        assert stats["max"] == "30" and stats["min"] == "18"
        zug1 = next(u for u in stats["per_unit"] if u["unit"] == zuege[1].pk)
        assert zug1["count"] == 3 and zug1["members"] == 3 and zug1["participation"] == 100

        pdf = c.get(url(club, f"{comp_id}/export/?als=pdf"))
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        xlsx = c.get(url(club, f"{comp_id}/export/?als=xlsx"))
        assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"

        for q in (
            "schiessliste&sortierung=einheit",
            "schiessliste&leer=1",
            f"stechliste&stechen={zso['id']}",
        ):
            resp = c.get(url(club, f"{comp_id}/export/?als={q}"))
            assert resp.status_code == 200 and resp.content.startswith(b"%PDF"), q
        resp = c.post(url(club, f"{comp_id}/status/"), {"status": "endgueltig"}, "application/json")
        assert resp.status_code == 200, resp.content
        # Endgültig: keine Änderungen mehr
        assert _punkte(c, club, comp_id, einzel, gast["id"], 20).status_code == 400

    def test_suche_findet_umlaute_und_zug(self, club, schuetzen, zuege, board_a, api):
        c = api(board_a)
        comp_id, einzel, _ = self._anlegen(c, club)
        rows = c.get(url(club, f"{comp_id}/candidates/?suche=muel")).json()
        assert [r["name"] for r in rows] == ["Jürgen Müller"] and rows[0]["unit_name"] == "Zug 2"
        _starter(c, club, comp_id, membership=schuetzen["Jürgen"].pk)
        rows = c.get(url(club, f"{comp_id}/candidates/?suche=Müller")).json()
        assert rows[0]["starter"] is not None
        # Doppelt eintragen geht nicht
        resp = c.post(
            url(club, f"{comp_id}/starters/"),
            {"membership": schuetzen["Jürgen"].pk},
            "application/json",
        )
        assert resp.status_code == 400

    def test_gast_einzelfall_fuer_zug(self, club, zuege, board_a, api):
        c = api(board_a)
        comp_id, _, _ = self._anlegen(c, club)
        gast = _starter(c, club, comp_id, name="Gerd Gast")
        resp = c.patch(
            url(club, f"{comp_id}/starters/{gast['id']}/"),
            {"unit": zuege[3].pk, "number": "17"},
            "application/json",
        )
        assert resp.json()["unit_name"] == "Zug 3" and resp.json()["number"] == "17"

    def test_kopie_aus_dem_vorjahr(self, club, board_a, api):
        c = api(board_a)
        comp_id, _, _ = self._anlegen(c, club)
        resp = c.post(url(club, f"{comp_id}/copy/"), {}, "application/json")
        assert resp.status_code == 201
        new = Competition.objects.get(pk=resp.json()["id"])
        assert new.title == "Preisschießen 2028" and new.date == datetime.date(2028, 6, 14)
        einzel, zug = new.scorings.order_by("sort_order")
        assert zug.source_id == einzel.pk and zug.team_size == 2

    def test_rechte_und_modul(self, orgs, club, board_a, board_b, api):
        c = api(board_a)
        comp_id, einzel, _ = self._anlegen(c, club)
        # Fremde Einheit sieht nichts
        assert api(board_b).get(url(club)).status_code == 404
        # Nur „Ergebnisse erfassen“: Werte ja, Einrichten nein
        helfer = make_user("schiessmeister@example.org")
        give_role(helfer, club, ["competitions.results"], name="Schießmeister")
        h = api(helfer)
        gast = _starter(h, club, comp_id, name="Gerd Gast")
        assert _punkte(h, club, comp_id, einzel, gast["id"], 20).status_code == 200
        assert (
            h.patch(url(club, f"{comp_id}/"), {"title": "x"}, "application/json").status_code == 403
        )
        assert (
            h.post(
                url(club, f"{comp_id}/status/"), {"status": "endgueltig"}, "application/json"
            ).status_code
            == 403
        )
        # Ohne Recht: verboten
        leser = make_user("leser@example.org")
        give_role(leser, club, ["members.view"], name="Leser")
        assert api(leser).get(url(club)).status_code == 403
        # Modul aus: nicht da
        club.enabled_modules = ["members"]
        club.save()
        assert c.get(url(club)).status_code == 404

    def test_loeschen_eines_mitglieds_behaelt_namen(self, club, schuetzen, board_a, api):
        c = api(board_a)
        comp_id, einzel, _ = self._anlegen(c, club)
        s = _starter(c, club, comp_id, membership=schuetzen["Otto"].pk)
        starter = Starter.objects.get(pk=s["id"])
        starter.membership = None
        starter.save()
        assert Starter.objects.get(pk=s["id"]).name == "Otto Normal"
        assert Score.objects.count() == 0
        assert Scoring.objects.filter(competition_id=comp_id).count() == 2


@pytest.mark.django_db(transaction=True)
class TestOfflineAbgleich:
    def test_eingaben_nachreichen_ohne_doppelte(self, club, schuetzen, zuege, board_a, api):
        c = api(board_a)
        comp_id = c.post(
            url(club),
            {"title": "Preisschießen", "date": "2027-06-14", "template": "schiessen"},
            "application/json",
        ).json()["id"]
        einzel = Scoring.objects.get(competition_id=comp_id, kind="einzel").pk
        liste = c.get(url(club, f"{comp_id}/members/")).json()
        assert {r["name"]: r["unit_name"] for r in liste}["Max Muster"] == "Zug 1"
        key_max, key_gast = (
            "6f1c2b3a-0000-4000-8000-000000000001",
            "6f1c2b3a-0000-4000-8000-000000000002",
        )
        ops = [
            {"op": "starter", "client_key": key_max, "membership": schuetzen["Max"].pk},
            {"op": "starter", "client_key": key_gast, "name": "Gerd Gast", "club": "Nachbarn"},
            {
                "op": "score",
                "starter": key_max,
                "scoring": einzel,
                "value": "27",
                "at": "2027-06-14T10:00:00+02:00",
            },
            {"op": "starter_update", "starter": key_gast, "unit": zuege[2].pk},
            {"op": "score", "starter": key_gast, "scoring": einzel, "value": "99"},
            {"op": "unsinn"},
        ]
        resp = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops}, "application/json")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [r["ok"] for r in data["results"]] == [True, True, True, True, False, False]
        assert data["results"][4]["error"] == "Höchstens 30."
        assert set(data["keys"]) == {key_max, key_gast}
        # Zweites Senden (Empfang brach ab): nichts doppelt
        again = c.post(url(club, f"{comp_id}/sync/"), {"ops": ops[:4]}, "application/json").json()
        assert all(r["ok"] for r in again["results"])
        assert Starter.objects.filter(competition_id=comp_id).count() == 2
        gast = Starter.objects.get(competition_id=comp_id, name="Gerd Gast")
        assert gast.unit_id == zuege[2].pk

    def test_spaetere_eingabe_gilt(self, club, schuetzen, board_a, api):
        c = api(board_a)
        comp_id = c.post(
            url(club),
            {"title": "Preisschießen", "date": "2027-06-14", "template": "schiessen"},
            "application/json",
        ).json()["id"]
        einzel = Scoring.objects.get(competition_id=comp_id, kind="einzel").pk
        s = _starter(c, club, comp_id, membership=schuetzen["Max"].pk)
        assert _punkte(c, club, comp_id, einzel, s["id"], 25).status_code == 200
        alt = {
            "op": "score",
            "starter": s["id"],
            "scoring": einzel,
            "value": "20",
            "at": "2000-01-01T00:00:00+00:00",
        }
        data = c.post(url(club, f"{comp_id}/sync/"), {"ops": [alt]}, "application/json").json()
        assert data["conflicts"][0]["value"] == "25.000"
        assert Score.objects.get(starter_id=s["id"]).value == 25
