"""Meilenstein 4: Zusatzfelder, Mitgliedsdauer und Jubiläen."""

import datetime

import pytest

from customfields.models import FieldDefinition, FieldValue
from members.duration import jubilee_date, merge
from members.models import Membership, MemberType

from .factories import give_role, make_user
from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"
D = datetime.date


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b", "c")}


@pytest.fixture
def board_fed(orgs):
    user = make_user("verband@example.org")
    give_role(user, orgs["federation"])
    return user


class TestBerechnung:
    def test_zusammenfassen(self):
        assert merge([(D(2000, 1, 1), D(2005, 1, 1)), (D(2003, 1, 1), D(2010, 1, 1))]) == [
            (D(2000, 1, 1), D(2010, 1, 1))
        ]
        assert merge([(D(2000, 1, 1), D(2000, 12, 31)), (D(2001, 1, 1), None)]) == [
            (D(2000, 1, 1), None)
        ]

    def test_jubilaeum_durchgehend_und_mit_luecke(self):
        assert jubilee_date([(D(2000, 3, 1), None)], 25) == D(2025, 3, 1)
        # Ein Jahr Pause verschiebt das Jubiläum um ein Jahr
        ranges = [(D(2000, 3, 1), D(2004, 2, 29)), (D(2005, 3, 1), None)]
        assert jubilee_date(ranges, 10) == D(2011, 3, 1)
        assert jubilee_date([(D(2000, 1, 1), D(2001, 1, 1))], 10) is None


class TestDauerInDerAkte:
    def url(self, orgs, m):
        return f"/api/orgs/{orgs['a'].pk}/members/{m['id']}/"

    def test_dauer_verein_nur_zaehlende_arten(self, api, orgs, types, board_a):
        c = api(board_a)
        member = admit(c, orgs["a"], types["a"]["aktiv"], entry_date="2000-01-01").json()
        c.post(
            f"{self.url(orgs, member)}change-type/",
            {"member_type": types["a"]["foerder"].pk, "valid_from": "2010-01-01"},
            content_type=JSON,
        )
        data = c.get(self.url(orgs, member)).json()
        # Fördermitglied zählt nicht: nur 2000–2009
        assert data["duration"]["club"]["years"] == 10
        assert (
            data["duration"]["club"]["next"] is None
            or data["duration"]["club"]["next"]["years"] > 10
        )

    def test_dauer_dachverband_ueber_vereine(self, api, orgs, types, board_a, board_b):
        a = admit(api(board_a), orgs["a"], types["a"]["aktiv"], entry_date="1990-01-01").json()
        api(board_a).post(
            f"{self.url(orgs, a)}exit/",
            {"exit_date": "1999-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        b = (
            api(board_b)
            .post(
                f"/api/orgs/{orgs['b'].pk}/members/admit/",
                {
                    "person": a["person_id"],
                    "member_type": types["b"]["aktiv"].pk,
                    "entry_date": "2000-01-01",
                    "email": "e@example.org",
                    "street": "x",
                    "postal_code": "1",
                    "city": "y",
                },
                content_type=JSON,
            )
            .json()
        )
        fed = b["duration"]["federation"]
        assert fed["years"] >= 30  # durchgehend seit 1990 über zwei Vereine
        assert b["duration"]["club"]["years"] < fed["years"]

    def test_regel_nur_aktive_zeiten(self, api, orgs, types, board_a):
        orgs["federation"].federation_duration_rule = "active_reported"
        orgs["federation"].save()
        c = api(board_a)
        m = admit(c, orgs["a"], types["a"]["passiv"], entry_date="2000-01-01").json()
        assert m["duration"]["federation"]["days"] == 0
        assert m["duration"]["club"]["days"] > 0


class TestJubilaeen:
    def test_liste_im_zeitraum(self, api, orgs, types, board_a):
        orgs["a"].jubilee_years = [10, 25]
        orgs["a"].save()
        orgs["federation"].jubilee_years = [25]
        orgs["federation"].save()
        c = api(board_a)
        admit(c, orgs["a"], types["a"]["aktiv"], entry_date="2000-06-15", last_name="Silber")
        admit(
            c,
            orgs["a"],
            types["a"]["aktiv"],
            entry_date="2016-06-15",
            last_name="Zehn",
            birth_date="1990-01-01",
        )
        data = c.get(
            f"/api/orgs/{orgs['a'].pk}/jubilees/", {"von": "2025-01-01", "bis": "2026-12-31"}
        ).json()
        rows = [(r["last_name"], r["kind"], r["years"], r["date"]) for r in data["results"]]
        assert ("Silber", "club", 25, "2025-06-15") in rows
        assert ("Silber", "federation", 25, "2025-06-15") in rows
        assert ("Zehn", "club", 10, "2026-06-15") in rows

    def test_kurznamen_in_der_liste(self, api, orgs, types, board_a):
        orgs["a"].jubilee_years = [25]
        orgs["a"].short_name = "VA"
        orgs["a"].save()
        orgs["federation"].jubilee_years = [25]
        orgs["federation"].save()
        c = api(board_a)
        admit(c, orgs["a"], types["a"]["aktiv"], entry_date="2000-06-15", last_name="Silber")
        data = c.get(
            f"/api/orgs/{orgs['a'].pk}/jubilees/", {"von": "2025-01-01", "bis": "2025-12-31"}
        ).json()
        names = {r["kind"]: (r["organization"], r["organization_short"]) for r in data["results"]}
        # ohne Kurzname (Dachverband) steht der volle Name
        assert names == {"club": ("Verein A", "VA"), "federation": ("Testbund", "Testbund")}

    def test_stufen_einstellbar(self, api, orgs, board_a):
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/", {"jubilee_years": [50, 10, "25"]}, content_type=JSON
        )
        assert resp.status_code == 200
        assert resp.json()["jubilee_years"] == [10, 25, 50]
        bad = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/", {"jubilee_years": [0]}, content_type=JSON
        )
        assert bad.status_code == 400

    def test_zeitraum_begrenzt(self, api, orgs, board_a):
        resp = api(board_a).get(
            f"/api/orgs/{orgs['a'].pk}/jubilees/", {"von": "2020-01-01", "bis": "2030-01-01"}
        )
        assert resp.status_code == 400


class TestZusatzfelder:
    def test_feld_anlegen_und_werte(self, api, orgs, types, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        shoe = c.post(
            f"{base}/fields/", {"label": "Schuhgröße", "field_type": "number"}, content_type=JSON
        ).json()
        award = c.post(
            f"{base}/fields/",
            {
                "label": "Auszeichnung",
                "repeatable": True,
                "subfields": [
                    {"label": "Bezeichnung", "type": "text"},
                    {"label": "Datum", "type": "date"},
                    {"label": "verliehen von", "type": "choice", "choices": ["Verein", "Verband"]},
                ],
            },
            content_type=JSON,
        ).json()
        assert award["key"] == "auszeichnung"
        assert [s["key"] for s in award["subfields"]] == ["bezeichnung", "datum", "verliehen-von"]
        member = admit(c, orgs["a"], types["a"]["aktiv"]).json()
        url = f"{base}/members/{member['id']}/fields/"
        resp = c.put(
            url,
            {
                "values": {
                    str(shoe["id"]): "43,5",
                    str(award["id"]): [
                        {
                            "bezeichnung": "Ehrennadel Silber",
                            "datum": "2020-05-01",
                            "verliehen-von": "Verein",
                        },
                        {
                            "bezeichnung": "",
                            "datum": "",
                            "verliehen-von": "",
                        },  # leere Zeile entfällt
                    ],
                }
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        values = {row["definition"]["label"]: row["value"] for row in resp.json()}
        assert values["Schuhgröße"] == 43.5
        assert len(values["Auszeichnung"]) == 1
        history = c.get(f"{base}/members/{member['id']}/history/").json()
        assert "Schuhgröße" in history[0]["changes"]

    def test_ungueltige_werte(self, api, orgs, types, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        f = c.post(
            f"{base}/fields/",
            {"label": "Größe", "field_type": "choice", "choices": ["S", "M"]},
            content_type=JSON,
        ).json()
        d = c.post(
            f"{base}/fields/", {"label": "Prüfung", "field_type": "date"}, content_type=JSON
        ).json()
        member = admit(c, orgs["a"], types["a"]["aktiv"]).json()
        resp = c.put(
            f"{base}/members/{member['id']}/fields/",
            {"values": {str(f["id"]): "XL", str(d["id"]): "gestern"}},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert set(resp.json()) == {str(f["id"]), str(d["id"])}

    def test_auswahl_braucht_werte(self, api, orgs, board_a):
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/fields/",
            {"label": "Leer", "field_type": "choice"},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_verbandsweites_feld_in_allen_vereinen(
        self, api, orgs, types, board_a, board_b, board_c, board_fed
    ):
        fed_field = api(board_fed).post(
            f"/api/orgs/{orgs['federation'].pk}/fields/",
            {"label": "Verbandsehrennadel", "field_type": "bool", "federation_wide": True},
            content_type=JSON,
        )
        assert fed_field.status_code == 201, fed_field.json()
        api(board_fed).post(
            f"/api/orgs/{orgs['federation'].pk}/fields/",
            {"label": "Nur Verband", "field_type": "text"},
            content_type=JSON,
        )
        a_fields = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/fields/").json()
        assert [(f["label"], f["inherited"]) for f in a_fields] == [("Verbandsehrennadel", True)]
        # Verein ohne Dachverband sieht es nicht
        assert api(board_c).get(f"/api/orgs/{orgs['c'].pk}/fields/").json() == []
        # Verein kann es nicht ändern
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/fields/{fed_field.json()['id']}/",
            {"label": "x"},
            content_type=JSON,
        )
        assert resp.status_code == 404
        # Wert setzen; die Person ist auch in Verein B -> gleicher Wert dort
        m = admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()
        api(board_a).put(
            f"/api/orgs/{orgs['a'].pk}/members/{m['id']}/fields/",
            {"values": {str(fed_field.json()["id"]): True}},
            content_type=JSON,
        )
        b = (
            api(board_b)
            .post(
                f"/api/orgs/{orgs['b'].pk}/members/admit/",
                {
                    "person": m["person_id"],
                    "member_type": types["b"]["passiv"].pk,
                    "entry_date": "2020-01-01",
                    "email": "e@example.org",
                    "street": "x",
                    "postal_code": "1",
                    "city": "y",
                },
                content_type=JSON,
            )
            .json()
        )
        b_values = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/members/{b['id']}/fields/").json()
        assert b_values[0]["value"] is True

    def test_verein_kann_nicht_verbandsweit(self, api, orgs, board_a):
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/fields/",
            {"label": "X", "field_type": "text", "federation_wide": True},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_felder_anderer_vereine_unsichtbar(self, api, orgs, types, board_a, board_b):
        api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/fields/", {"label": "Geheim"}, content_type=JSON
        )
        assert api(board_a).get(f"/api/orgs/{orgs['a'].pk}/fields/").json() == []

    def _field_with_value(self, c, orgs, types):
        base = f"/api/orgs/{orgs['a'].pk}"
        f = c.post(f"{base}/fields/", {"label": "Notiz"}, content_type=JSON).json()
        m = admit(c, orgs["a"], types["a"]["aktiv"]).json()
        c.put(
            f"{base}/members/{m['id']}/fields/",
            {"values": {str(f["id"]): "Hallo"}},
            content_type=JSON,
        )
        return base, f

    def test_feld_mit_werten_nur_mit_bestaetigung_loeschbar(self, api, orgs, types, board_a):
        c = api(board_a)
        base, f = self._field_with_value(c, orgs, types)
        usage = c.get(f"{base}/fields/{f['id']}/usage/").json()
        assert usage == {"deletable": False, "value_count": 1, "is_archived": False}
        resp = c.delete(f"{base}/fields/{f['id']}/")
        assert resp.status_code == 409
        assert resp.json()["can_archive"] is True
        assert FieldValue.objects.count() == 1
        assert FieldDefinition.objects.count() == 1
        resp = c.delete(f"{base}/fields/{f['id']}/?mit_werten=1")
        assert resp.status_code == 204
        assert FieldValue.objects.count() == 0
        assert FieldDefinition.objects.count() == 0
        assert Membership.objects.count() == 1
        assert MemberType.objects.filter(organization=orgs["a"]).count() == 3

    def test_unbenutztes_feld_loeschen(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        f = c.post(f"{base}/fields/", {"label": "Leer"}, content_type=JSON).json()
        assert c.get(f"{base}/fields/{f['id']}/usage/").json()["deletable"] is True
        assert c.delete(f"{base}/fields/{f['id']}/").status_code == 204
        assert FieldDefinition.objects.count() == 0

    def test_feld_archivieren_und_wiederherstellen(self, api, orgs, types, board_a):
        c = api(board_a)
        base, f = self._field_with_value(c, orgs, types)
        resp = c.post(f"{base}/fields/{f['id']}/archive/")
        assert resp.status_code == 200 and resp.json()["is_archived"] is True
        assert FieldValue.objects.count() == 1
        resp = c.post(f"{base}/fields/{f['id']}/restore/")
        assert resp.json()["is_archived"] is False

    def test_verbandsfeld_nicht_vom_verein_loeschbar(self, api, orgs, types, board_a, board_fed):
        fed = f"/api/orgs/{orgs['federation'].pk}"
        f = (
            api(board_fed)
            .post(
                f"{fed}/fields/",
                {"label": "Ehrennadel", "field_type": "bool", "federation_wide": True},
                content_type=JSON,
            )
            .json()
        )
        a = f"/api/orgs/{orgs['a'].pk}"
        m = admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()
        api(board_a).put(
            f"{a}/members/{m['id']}/fields/",
            {"values": {str(f["id"]): True}},
            content_type=JSON,
        )
        assert api(board_a).delete(f"{a}/fields/{f['id']}/?mit_werten=1").status_code == 404
        assert api(board_a).get(f"{a}/fields/{f['id']}/usage/").status_code == 404
        assert api(board_fed).get(f"{fed}/fields/{f['id']}/usage/").json()["value_count"] == 1
        assert api(board_fed).delete(f"{fed}/fields/{f['id']}/?mit_werten=1").status_code == 204
        assert FieldValue.objects.count() == 0
