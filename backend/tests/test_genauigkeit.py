"""Genauigkeit (tag-/monats-/jahresgenau) für Mitgliedschaften und Jubiläen."""

import datetime

import pytest

from members.duration import Duration, jubilee_date

from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"
D = datetime.date


class TestBerechnung:
    def test_jahresgenau(self):
        ranges = [(D(2001, 9, 30), None)]
        assert jubilee_date(ranges, 25, "year") == D(2026, 1, 1)
        # im ganzen Jahr 2026 sind es 25 Jahre
        assert Duration.of(ranges, D(2026, 1, 2), "year").years == 25
        assert Duration.of(ranges, D(2025, 12, 31), "year").years == 24
        assert Duration.of(ranges, D(2026, 1, 2), "day").years == 24

    def test_monatsgenau(self):
        ranges = [(D(2001, 3, 31), None)]
        assert jubilee_date(ranges, 25, "month") == D(2026, 3, 1)
        assert jubilee_date([(D(2001, 12, 5), None)], 1, "month") == D(2002, 12, 1)

    def test_luecken_in_ganzen_einheiten(self):
        # 2001–2005 (5 Jahre), Pause 2006, ab 2007: 10 Jahre im Jahr 2012
        ranges = [(D(2001, 6, 1), D(2005, 3, 1)), (D(2007, 11, 1), None)]
        assert jubilee_date(ranges, 10, "year") == D(2012, 1, 1)
        # angrenzende Jahre gehen nahtlos weiter
        ranges = [(D(2001, 6, 1), D(2005, 3, 1)), (D(2005, 11, 1), None)]
        assert jubilee_date(ranges, 10, "year") == D(2011, 1, 1)
        # beendet und nicht erreicht
        assert jubilee_date([(D(2001, 6, 1), D(2005, 3, 1))], 10, "year") is None

    def test_tagesgenau_unveraendert(self):
        assert jubilee_date([(D(2000, 3, 1), None)], 25, "day") == D(2025, 3, 1)


class TestEinstellung:
    def test_organisation_und_abteilung(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        assert c.get(f"{base}/").json()["date_precision"] == "day"
        resp = c.patch(f"{base}/", {"date_precision": "year"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert (
            c.patch(f"{base}/", {"date_precision": "woche"}, content_type=JSON).status_code == 400
        )
        me = next(o for o in c.get("/api/me/organizations/").json() if o["id"] == orgs["a"].pk)
        assert me["date_precision"] == "year"

        dep = c.post(
            f"{base}/departments/", {"name": "Zug 1", "founding_year": 1975}, content_type=JSON
        ).json()
        assert dep["date_precision"] == ""  # wie der Verein
        resp = c.patch(
            f"{base}/departments/{dep['id']}/", {"date_precision": "month"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["date_precision"] == "month"


class TestJubilaeen:
    def test_jahresgenau_ganzes_jahr(self, api, orgs, board_a):
        types = make_types(orgs["a"])
        orgs["a"].jubilee_years = [25]
        orgs["a"].date_precision = "year"
        orgs["a"].save()
        orgs["federation"].jubilee_years = [25]
        orgs["federation"].date_precision = "month"
        orgs["federation"].save()
        c = api(board_a)
        m = admit(c, orgs["a"], types["aktiv"], entry_date="2001-09-30", last_name="Silber")
        # Zeitraum im Februar 2026: Vereinsjubiläum (ganzes Jahr 2026) zählt,
        # das monatsgenaue Dachverbandsjubiläum (September 2026) nicht
        data = c.get(
            f"/api/orgs/{orgs['a'].pk}/jubilees/", {"von": "2026-02-01", "bis": "2026-02-28"}
        ).json()
        rows = [(r["kind"], r["years"], r["date"], r["precision"]) for r in data["results"]]
        assert rows == [("club", 25, "2026-01-01", "year")]
        data = c.get(
            f"/api/orgs/{orgs['a'].pk}/jubilees/", {"von": "2026-09-30", "bis": "2026-10-01"}
        ).json()
        kinds = {(r["kind"], r["date"]) for r in data["results"]}
        assert kinds == {("club", "2026-01-01"), ("federation", "2026-09-01")}

        detail = c.get(f"/api/orgs/{orgs['a'].pk}/members/{m.json()['id']}/").json()
        assert detail["duration"]["club"]["precision"] == "year"
        assert detail["duration"]["federation"]["precision"] == "month"
