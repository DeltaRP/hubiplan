"""Vereine sehen statt „Dachverband“ den Namen ihres Dachverbands."""

import pytest

from organizations.terms import (
    build_federation_terms,
    department_terms,
    fill,
    rename_word,
)

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


class TestFormen:
    def test_maennlich_unveraenderter_genitiv(self):
        t = build_federation_terms("BSV", "m")
        assert t["dv_akk"] == "den BSV"
        assert t["dv_im"] == "im BSV"
        assert t["dv_gen"] == "des BSV"
        assert t["dv_Vom"] == "Vom BSV"
        assert t["dv_has"] == "1"
        assert fill("an {dv_akk} melden", t) == "an den BSV melden"

    def test_weiblich(self):
        t = build_federation_terms("Bruderschaft", "f")
        assert t["dv_im"] == "in der Bruderschaft"
        assert t["dv_Vom"] == "Von der Bruderschaft"

    def test_eigener_genitiv(self):
        t = build_federation_terms("Schützenbund", "m", "Schützenbundes")
        assert t["dv_gen"] == "des Schützenbundes"

    def test_ohne_name_bleibt_dachverband(self):
        t = build_federation_terms()
        assert t["dv_akk"] == "den Dachverband"
        assert t["dv_gen"] == "des Dachverbands"
        assert t["dv_has"] == ""

    def test_fill_ohne_dv_formen(self):
        # Formen ohne dv_-Schlüssel (z. B. reine Abteilungsformen) ergänzen die Vorgabe
        assert fill("Für {dv_akk}", {"sg": "Zug"}) == "Für den Dachverband"


class TestOrganisationen:
    def test_verein_nutzt_kurzname_sonst_name(self, orgs):
        assert department_terms(orgs["a"])["dv_im"] == "im Testbund"
        fed = orgs["federation"]
        fed.short_name = "TB"
        fed.save()
        orgs["a"].refresh_from_db()
        assert department_terms(orgs["a"])["dv_akk"] == "den TB"

    def test_ebenen_ohne_namen(self, orgs):
        assert department_terms(orgs["federation"])["dv_akk"] == "den Dachverband"
        assert department_terms(orgs["c"])["dv_has"] == ""

    def test_protokollbegriffe(self, orgs):
        assert rename_word("an Dachverband melden", orgs["a"]) == "an den Testbund melden"
        assert rename_word("an Dachverband melden", orgs["federation"]) == (
            "an den Dachverband melden"
        )


class TestApi:
    def test_dachverband_stellt_artikel_ein(self, api, orgs, board_a):
        fed_board = make_user("verband-name@example.org")
        give_role(fed_board, orgs["federation"])
        resp = api(fed_board).patch(
            f"/api/orgs/{orgs['federation'].pk}/",
            {"short_name": "Bruderschaft", "name_gender": "f"},
            content_type=JSON,
        )
        assert resp.status_code == 200
        assert resp.json()["name_gender"] == "f"
        me = next(
            o for o in api(board_a).get("/api/me/organizations/").json() if o["id"] == orgs["a"].pk
        )
        assert me["department_terms"]["dv_im"] == "in der Bruderschaft"
        assert me["department_terms"]["dv_has"] == "1"

    def test_artikel_ungueltig(self, api, orgs):
        fed_board = make_user("verband-name2@example.org")
        give_role(fed_board, orgs["federation"])
        resp = api(fed_board).patch(
            f"/api/orgs/{orgs['federation'].pk}/", {"name_gender": "x"}, content_type=JSON
        )
        assert resp.status_code == 400
