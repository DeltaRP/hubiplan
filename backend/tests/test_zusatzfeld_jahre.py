"""Zusatzfeld-Typ „Startjahr/Endjahr“ (Jahreszeitraum, Endjahr optional)."""

import pytest
from django.core.exceptions import ValidationError

from customfields.models import clean_scalar, format_year_range
from exchange.export import _scalar

from .test_m2_members import admit, make_types

JSON = "application/json"


class TestPruefen:
    @pytest.mark.parametrize(
        ("raw", "stored"),
        [
            ("2010", "2010"),
            (2010, "2010"),
            (2010.0, "2010"),
            ("2010/2015", "2010/2015"),
            ("2010 - 2015", "2010/2015"),
            ("2010–2015", "2010/2015"),
            ("2024/25", "2024/2025"),
            ("1999/00", "1999/2000"),
            ("2010/", "2010"),
            ("seit 2010", "2010"),
            ("2010/2010", "2010/2010"),
        ],
    )
    def test_gueltig(self, raw, stored):
        assert clean_scalar("yearrange", raw) == stored

    @pytest.mark.parametrize("raw", ["gestern", "2015/2010", "10", "2010/5", "0999", True, "3000"])
    def test_ungueltig(self, raw):
        with pytest.raises(ValidationError):
            clean_scalar("yearrange", raw)

    def test_leer(self):
        assert clean_scalar("yearrange", "") is None

    def test_anzeige(self):
        assert format_year_range("2010/2015") == "2010/2015"
        assert format_year_range("2010") == "seit 2010"
        assert _scalar("yearrange", "2010") == "seit 2010"
        # Die Anzeige lässt sich wieder einlesen (Export → Import)
        assert clean_scalar("yearrange", format_year_range("2010")) == "2010"


@pytest.mark.django_db
class TestImMitglied:
    def test_anlegen_und_speichern(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        field = c.post(
            f"{base}/fields/",
            {"label": "Königsjahr", "field_type": "yearrange"},
            content_type=JSON,
        ).json()
        assert field["field_type"] == "yearrange"
        award = c.post(
            f"{base}/fields/",
            {
                "label": "Ämter",
                "repeatable": True,
                "subfields": [
                    {"label": "Amt", "type": "text"},
                    {"label": "Zeitraum", "type": "yearrange"},
                ],
            },
            content_type=JSON,
        )
        assert award.status_code == 201, award.json()
        award = award.json()
        member = admit(c, orgs["a"], make_types(orgs["a"])["aktiv"]).json()
        url = f"{base}/members/{member['id']}/fields/"
        resp = c.put(
            url,
            {
                "values": {
                    str(field["id"]): "2024/25",
                    str(award["id"]): [{"amt": "Schriftführer", "zeitraum": "2018"}],
                }
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        values = {row["definition"]["label"]: row["value"] for row in resp.json()}
        assert values["Königsjahr"] == "2024/2025"
        assert values["Ämter"] == [{"amt": "Schriftführer", "zeitraum": "2018"}]
        bad = c.put(url, {"values": {str(field["id"]): "2025/2020"}}, content_type=JSON)
        assert bad.status_code == 400
        assert "Endjahr" in str(bad.json())
