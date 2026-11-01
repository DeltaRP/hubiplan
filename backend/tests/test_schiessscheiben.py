"""Schießscheiben Schritt 1: Scheibenkatalog, Wertung aus dem Trefferpunkt,
Gleichstandskette und Treffer je Starter (alles erfundene Daten).

Maße und Formeln: konzepte/schiessscheiben-recherche.md, Abschnitte 1.1–1.3 und 2.3.
"""

from decimal import Decimal

import pytest

from competitions import ranking, targets, tiebreak
from competitions.models import Hit, Score

from .test_wettbewerbe import _starter, url

D = Decimal


@pytest.fixture
def verein(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "competitions"]
    org.save()
    return org


def at(key, d):
    """Wertung eines Treffers im Abstand d (mm) rechts der Mitte."""
    return targets.score(targets.BY_KEY[key], d, 0.0)


class TestWertungAusTrefferpunkt:
    def test_luftgewehr_dsb(self):
        mitte = at("lg10_dsb", 0)
        assert (mitte.ring, mitte.decimal, mitte.inner, mitte.teiler) == (10, D("10.9"), True, 0)
        assert at("lg10_dsb", 1.0).decimal == D("10.6")  # Beispiel aus der Recherche
        # Innenzehner: Punkt (0,5 mm) ganz weggeschossen bis d = 2,0 mm
        assert at("lg10_dsb", 2.0).inner and not at("lg10_dsb", 2.01).inner
        # Lochrand berührt die Ringlinie: höherer Ring
        assert (at("lg10_dsb", 2.5).ring, at("lg10_dsb", 2.5).decimal) == (10, D("10.0"))
        assert (at("lg10_dsb", 2.51).ring, at("lg10_dsb", 2.51).decimal) == (9, D("9.9"))
        assert at("lg10_dsb", 25.0).ring == 1
        assert (at("lg10_dsb", 25.1).ring, at("lg10_dsb", 25.1).decimal) == (0, D("0.0"))
        assert at("lg10_dsb", 1.234).teiler == D("123.4")

    def test_luftgewehr_kyffhaeuser(self):
        assert at("lg10_kyf", 0).decimal == D("10.7")  # 10 + 3,25/4,5
        assert at("lg10_kyf", 1.0).decimal == D("10.5")
        assert at("lg10_kyf", 3.25).ring == 10 and at("lg10_kyf", 3.26).ring == 9
        assert not at("lg10_kyf", 0).inner  # kein Innenzehner
        # Ring 6 reicht bis 3,25 + 4 · 4,5 = 21,25 mm; die Fünf-Spiegel-Karte hat keinen 5er
        assert at("lg10_kyf", 21.3).ring == 5
        assert at("lg10_kyf5", 21.25).ring == 6 and at("lg10_kyf5", 21.3).ring == 0

    def test_luftpistole_und_kleinkaliber(self):
        assert at("lp10", 8.0).ring == 10 and at("lp10", 8.01).ring == 9
        assert at("lp10", 4.75).inner and not at("lp10", 4.76).inner
        assert at("kk50", 8.0).ring == 10 and at("kk50", 5.3).inner
        assert at("kk50", 0).decimal == D("10.9")

    def test_ringe_der_scheibe(self):
        lg = targets.BY_KEY["lg10_dsb"]
        assert lg.ring_diameter(1) == pytest.approx(45.5)
        assert targets.BY_KEY["lg10_kyf"].ring_diameter(1) == pytest.approx(83)
        assert targets.BY_KEY["lp10"].ring_diameter(1) == pytest.approx(155.5)
        assert targets.BY_KEY["kk50"].ring_diameter(1) == pytest.approx(154.4)

    def test_eigene_scheibe(self):
        c = targets.clean_custom(
            {"name": "Festscheibe", "top_diameter": "3", "ring_width": "5", "caliber": "4,5"}
        )
        assert c["top"] == 10 and c["lowest"] == 1 and c["teiler_factor"] == 1.0
        t = targets.get(targets.CUSTOM, c)
        assert t.name == "Festscheibe" and targets.score(t, 0, 0).decimal == D("10.7")
        with pytest.raises(targets.TargetError) as err:
            targets.clean_custom({"top_diameter": "3", "ring_width": "0", "caliber": "4.5"})
        assert err.value.field == "ring_width"
        with pytest.raises(targets.TargetError):
            targets.clean_custom({"top_diameter": "3", "ring_width": "5"})
        assert targets.get(targets.CUSTOM, {}) is None

    def test_summe_der_besten_und_teiler(self):
        shots = [at("lg10_kyf", d) for d in (0.5, 30, 10, 3.5, 1.0)]  # 10, 4, 8, 9, 10
        assert [s.ring for s in shots] == [10, 4, 8, 9, 10]
        assert targets.total("ringe", shots, 3) == 29
        assert targets.total("ringe", shots, None) == 41
        assert targets.total("teiler", shots, None) == D("50.0")
        assert [s.ring for s in targets.counted_shots("ringe", shots, 3)] == [10, 9, 10]
        assert targets.total("ringe", [], 3) is None


class TestGleichstandskette:
    def _shots(self, *ds, key="lg10_kyf"):
        return [at(key, d) for d in ds]

    def test_regeln(self):
        t = targets.BY_KEY["lg10_kyf"]
        a = self._shots(0.5, 0.5, 8.0)  # 10, 10, 8
        b = self._shots(0.5, 4.0, 4.0)  # 10, 9, 9
        rc = lambda s: tiebreak.value("ringzahlen", s, t, "ringe", 10)  # noqa: E731
        assert rc(a) > rc(b)
        assert tiebreak.value("serien", a, t, "ringe", 2) == (D(8), D(20))
        assert tiebreak.value("teiler", a, t, "ringe", 10) == -D("50.0")
        assert tiebreak.value("schlechtester", b, t, "ringe", 10) == -D("4.000")
        assert tiebreak.value("ringzahlen", [], t, "ringe", 10) is None
        assert tiebreak.clean(["innenzehner", "innenzehner", "zehntel"]) == [
            "innenzehner",
            "zehntel",
        ]
        with pytest.raises(ValueError):
            tiebreak.clean(["gibtsnicht"])

    def test_rangliste_mit_kette(self):
        e = ranking.Entry
        res = ranking.rank(
            [
                e("a", D(28), tiebreak=((1, 2), D(3))),
                e("b", D(28), tiebreak=((2, 0), D(1))),
                e("c", D(28), tiebreak=((1, 2), D(5))),
                e("d", D(27)),
            ],
            prize_places=3,
        )
        places = {p.key: (p.place, p.decided_by, p.tie) for p in res.placed}
        assert places == {
            "b": (1, 0, False),
            "c": (2, 1, False),
            "a": (3, 1, False),
            "d": (4, None, False),
        }
        assert res.open == []

    def test_fehlende_treffer_beenden_die_kette(self):
        e = ranking.Entry
        res = ranking.rank(
            [e("a", D(28), tiebreak=(D(2),)), e("b", D(28), tiebreak=(None,))], prize_places=3
        )
        assert {p.place for p in res.placed} == {1}
        assert res.open and res.open[0].keys == ["a", "b"]


@pytest.mark.django_db(transaction=True)
class TestTrefferUndWertung:
    def _wettbewerb(self, c, verein):
        resp = c.post(
            url(verein),
            {"title": "Pokalschießen 2027", "date": "2027-05-01", "template": "einfach"},
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        comp_id = resp.json()["id"]
        scoring = c.get(url(verein, f"{comp_id}/")).json()["scorings"][0]["id"]
        return comp_id, scoring

    def _treffer(self, c, verein, comp_id, scoring, starter, points):
        return c.put(
            url(verein, f"{comp_id}/hits/"),
            {
                "scoring": scoring,
                "starter": starter,
                "hits": [{"x": x, "y": y} for x, y in points],
            },
            "application/json",
        )

    def test_katalog(self, verein, board_a, api):
        data = api(board_a).get(url(verein, "targets/")).json()
        keys = [t["key"] for t in data["targets"]]
        assert {"lg10_dsb", "lg10_kyf", "lg10_kyf5", "lp10", "kk50"} <= set(keys)
        lg = next(t for t in data["targets"] if t["key"] == "lg10_dsb")
        assert lg["rings"][0] == {"ring": 1, "diameter": 45.5} and lg["max_decimal"] == "10.9"
        assert {m["value"] for m in data["methods"]} == {"frei", "ringe", "zehntel", "teiler"}
        assert data["presets"]["dsb"][0] == "serien"

    def test_ringe_aus_treffern(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein)
        s_url = url(verein, f"{comp_id}/scorings/{sc}/")
        # ohne Scheibe keine Wertungsart und keine Treffer
        assert c.patch(s_url, {"method": "ringe"}, "application/json").status_code == 400
        anna = _starter(c, verein, comp_id, name="Anna Probe")["id"]
        assert self._treffer(c, verein, comp_id, sc, anna, [(0, 0)]).status_code == 400

        resp = c.patch(
            s_url,
            {"target": "lg10_kyf", "method": "ringe", "shots": 5, "counted_shots": 3},
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert (body["decimals"], body["higher_better"], body["unit_label"]) == (0, True, "Ringe")
        assert D(body["max_per_shot"]) == 10

        resp = self._treffer(
            c, verein, comp_id, sc, anna, [(0.5, 0), (0, 30), (-10, 0), (0, -3.5), ("1,0", 0)]
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [h["ring"] for h in data["hits"]] == [10, 4, 8, 9, 10]
        assert [h["counted"] for h in data["hits"]] == [True, False, False, True, True]
        assert data["total"] == "29"
        assert Score.objects.get(starter_id=anna).value == 29
        # mehr Treffer als Schüsse
        too_many = [(0, 0)] * 6
        assert self._treffer(c, verein, comp_id, sc, anna, too_many).status_code == 400

        # Wechsel auf Zehntel rechnet die Werte neu
        resp = c.patch(s_url, {"method": "zehntel"}, "application/json")
        assert resp.json()["decimals"] == 1 and D(resp.json()["max_per_shot"]) == D("10.7")
        assert Score.objects.get(starter_id=anna).value == D("10.6") + D("10.5") + D("9.9")

        # Teiler: kleiner ist besser, bester Teiler zählt
        c.patch(s_url, {"method": "teiler", "counted_shots": None}, "application/json")
        assert Score.objects.get(starter_id=anna).value == D("50.0")

        # alle Treffer weg: Wert weg
        assert self._treffer(c, verein, comp_id, sc, anna, []).status_code == 200
        assert not Score.objects.filter(starter_id=anna).exists()
        assert not Hit.objects.filter(starter_id=anna).exists()

    def test_gleichstand_ueber_treffer(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein)
        c.patch(
            url(verein, f"{comp_id}/scorings/{sc}/"),
            {
                "target": "lg10_kyf",
                "method": "ringe",
                "shots": 3,
                "prize_places": 3,
                "tie_breaks": ["ringzahlen", "schlechtester"],
            },
            "application/json",
        )
        a = _starter(c, verein, comp_id, name="Anton Erfunden")["id"]
        b = _starter(c, verein, comp_id, name="Berta Erfunden")["id"]
        g = _starter(c, verein, comp_id, name="Gustav Gast")["id"]
        self._treffer(c, verein, comp_id, sc, a, [(0, 0), (0, 4), (0, 4)])  # 10, 9, 9 = 28
        self._treffer(c, verein, comp_id, sc, b, [(0, 0), (0, 0), (0, 8)])  # 10, 10, 8 = 28
        # nur Summe, keine Treffer
        c.put(
            url(verein, f"{comp_id}/scores/"),
            {"scoring": sc, "starter": g, "value": "27"},
            "application/json",
        )
        board = c.get(url(verein, f"{comp_id}/standings/")).json()["scorings"][0]
        rows = {r["name"]: (r["place"], r["decided_by"]) for r in board["rows"]}
        assert rows["Berta Erfunden"] == (1, "mehr Zehner, dann Neuner usw.")
        assert rows["Anton Erfunden"] == (2, "mehr Zehner, dann Neuner usw.")
        assert rows["Gustav Gast"] == (3, "")
        assert board["open"] == []

        # unbekannte Regel
        resp = c.patch(
            url(verein, f"{comp_id}/scorings/{sc}/"), {"tie_breaks": ["los"]}, "application/json"
        )
        assert resp.status_code == 400

    def test_zuruecksetzen_loescht_treffer(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein)
        c.patch(
            url(verein, f"{comp_id}/scorings/{sc}/"),
            {"target": "lg10_dsb", "method": "zehntel"},
            "application/json",
        )
        a = _starter(c, verein, comp_id, name="Anton Erfunden")["id"]
        assert self._treffer(c, verein, comp_id, sc, a, [(0, 0)]).json()["total"] == "10.9"
        resp = c.post(url(verein, f"{comp_id}/reset/"), {"keep_starters": True}, "application/json")
        assert resp.status_code == 200, resp.content
        assert not Hit.objects.exists()

    def test_eigene_scheibe_ueber_die_schnittstelle(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein)
        s_url = url(verein, f"{comp_id}/scorings/{sc}/")
        assert c.patch(s_url, {"target": "eigen"}, "application/json").status_code == 400
        resp = c.patch(
            s_url,
            {
                "target": "eigen",
                "custom_target": {"top_diameter": "2", "ring_width": "x", "caliber": "4.5"},
            },
            "application/json",
        )
        assert resp.status_code == 400
        resp = c.patch(
            s_url,
            {
                "target": "eigen",
                "method": "ringe",
                "custom_target": {
                    "name": "Glücksscheibe",
                    "top_diameter": "2",
                    "ring_width": "4,5",
                    "caliber": "4.5",
                    "top": 12,
                },
            },
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        assert D(resp.json()["max_per_shot"]) == 12
        assert resp.json()["custom_target"]["ring_width"] == 4.5


@pytest.mark.django_db(transaction=True)
class TestAntippenAmStand:
    """Schritt 2: Treffer kommen über den Abgleich des Standmodus (auch offline)."""

    def _setup(self, c, verein):
        comp_id, sc = TestTrefferUndWertung()._wettbewerb(c, verein)
        c.patch(
            url(verein, f"{comp_id}/scorings/{sc}/"),
            {"target": "lg10_kyf", "method": "ringe", "shots": 3},
            "application/json",
        )
        return comp_id, sc

    def test_scheibe_fuer_das_zeichnen(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._setup(c, verein)
        info = c.get(url(verein, f"{comp_id}/")).json()["scorings"][0]["target_info"]
        assert info["key"] == "lg10_kyf" and info["rings"][0] == {"ring": 1, "diameter": 83.0}

    def test_treffer_ueber_den_abgleich(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._setup(c, verein)
        key = "6f1c1b7e-5a43-4c0e-9d7e-1b2c3d4e5f60"
        resp = c.post(
            url(verein, f"{comp_id}/sync/"),
            {
                "ops": [
                    {"op": "starter", "client_key": key, "name": "Gerda Gast"},
                    {
                        "op": "hits",
                        "starter": key,
                        "scoring": sc,
                        "hits": [{"x": 0, "y": 0}, {"x": 4, "y": 0}],
                        "at": "2027-05-01T10:00:00+02:00",
                    },
                ]
            },
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert all(r["ok"] for r in body["results"]), body["results"]
        gerda = next(s for s in body["starters"] if s["name"] == "Gerda Gast")
        assert gerda["values"][str(sc)] == "19.000"
        assert gerda["hits"][str(sc)] == [
            {"x": "0.000", "y": "0.000", "spot": None},
            {"x": "4.000", "y": "0.000", "spot": None},
        ]

    def test_spaetere_aenderung_gilt(self, verein, board_a, api):
        c = api(board_a)
        comp_id, sc = self._setup(c, verein)
        anna = _starter(c, verein, comp_id, name="Anna Probe")["id"]
        c.put(
            url(verein, f"{comp_id}/hits/"),
            {"scoring": sc, "starter": anna, "hits": [{"x": 0, "y": 0}]},
            "application/json",
        )
        # alte Offline-Eingabe von gestern kommt später an
        resp = c.post(
            url(verein, f"{comp_id}/sync/"),
            {
                "ops": [
                    {
                        "op": "hits",
                        "starter": anna,
                        "scoring": sc,
                        "hits": [{"x": 10, "y": 0}],
                        "at": "2020-01-01T10:00:00+01:00",
                    }
                ]
            },
            "application/json",
        ).json()
        assert resp["conflicts"] and resp["conflicts"][0]["name"] == "Anna Probe"
        assert Score.objects.get(starter_id=anna).value == 10
        assert Hit.objects.get(starter_id=anna).x == 0
