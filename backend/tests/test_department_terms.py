"""Eigene Abteilungsbezeichnung: Grammatik und Verwendung in Texten."""

import pytest

from audit.log import record
from organizations.models import Department
from organizations.terms import build_terms, fill

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


class TestFormen:
    def test_weiblich(self):
        t = build_terms("Abteilung", "Abteilungen", "f")
        assert t["gen"] == "der Abteilung"
        assert t["diesem"] == "dieser Abteilung"
        assert t["im"] == "in der Abteilung"
        assert fill("Unbekannt{adj} {sg}.", t) == "Unbekannte Abteilung."

    def test_maennlich(self):
        t = build_terms("Zug", "Züge", "m")
        assert t["gen"] == "des Zugs"
        assert t["diesem"] == "diesem Zug"
        assert t["einem"] == "einem Zug"
        assert t["pl_dat"] == "Zügen"
        assert t["Ein"] == "Ein Zug"
        assert fill("Mitglieder {gen}, Rollen {im}", t) == "Mitglieder des Zugs, Rollen im Zug"

    def test_saechlich_mit_eigenem_genitiv(self):
        t = build_terms("Korps", "Korps", "n", "Korps")
        assert t["gen"] == "des Korps"
        assert t["pl_dat"] == "Korps"
        assert fill("Unbekannt{adj} {sg}", t) == "Unbekanntes Korps"

    def test_genitiv_mit_es(self):
        assert build_terms("Kreis", "Kreise", "m")["gen"] == "des Kreises"


@pytest.fixture
def zug(api, orgs, board_a):
    org = orgs["a"]
    org.department_label = "Zug"
    org.department_label_plural = "Züge"
    org.department_label_gender = "m"
    org.save()
    return org


def _no_abteilung(data) -> None:
    assert "Abteilung" not in str(data)


class TestOberflaeche:
    def test_einstellungen_speichern_und_formen(self, api, orgs, board_a):
        c = api(board_a)
        resp = c.patch(
            f"/api/orgs/{orgs['a'].pk}/",
            {
                "department_label": "Zug",
                "department_label_plural": "Züge",
                "department_label_gender": "m",
            },
            content_type=JSON,
        )
        assert resp.status_code == 200
        assert resp.json()["department_terms"]["gen"] == "des Zugs"
        me = next(o for o in c.get("/api/me/organizations/").json() if o["id"] == orgs["a"].pk)
        assert me["department_terms"]["diesem"] == "diesem Zug"

    def test_rechtekatalog_mit_eigener_bezeichnung(self, api, zug, board_a):
        data = api(board_a).get(f"/api/permissions/?org_type=department&org={zug.pk}").json()
        _no_abteilung(data)
        labels = [p["label"] for m in data for p in m["permissions"]]
        assert "Mitglieder des Zugs lesen" in labels
        club = api(board_a).get(f"/api/permissions/?org_type=club&org={zug.pk}").json()
        _no_abteilung(club)

    def test_rechtekatalog_ohne_org_und_fremde_org(self, api, zug, orgs, board_a):
        labels = str(api(board_a).get("/api/permissions/?org_type=department").json())
        assert "Mitglieder der Abteilung lesen" in labels
        other = orgs["b"]
        other.department_label = "Sparte"
        other.save()
        foreign = str(
            api(board_a).get(f"/api/permissions/?org_type=department&org={other.pk}").json()
        )
        assert "Sparte" not in foreign

    def test_fehlermeldung_rolle_mit_fremder_abteilung(self, api, zug, orgs, board_a):
        foreign = Department.objects.create(
            organization=orgs["b"], name="Fremd", founding_year=1990
        )
        resp = api(board_a).post(
            f"/api/orgs/{zug.pk}/department-roles/",
            {"department": foreign.pk, "name": "Kassierer"},
            content_type=JSON,
        )
        assert resp.status_code == 400
        _no_abteilung(resp.json())

    def test_protokoll_zeigt_eigene_bezeichnung(self, api, zug, board_a):
        dep = Department.objects.create(organization=zug, name="Jäger", founding_year=1950)
        record(zug, board_a, "create", dep, {"Abteilung": [None, "Jäger"]})
        role_user = make_user("protokoll@example.org")
        give_role(role_user, zug, ["audit.view"])
        entries = api(role_user).get(f"/api/orgs/{zug.pk}/audit/").json()["results"]
        _no_abteilung(entries)
        assert any(e["object_type"] == "Zug" for e in entries)
