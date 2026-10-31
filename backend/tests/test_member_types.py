"""Mitgliedsarten löschen oder archivieren."""

import pytest

from audit.models import AuditEntry
from members.models import MemberType

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


def url(org, mt, suffix=""):
    return f"/api/orgs/{org.pk}/member-types/{mt.pk}/{suffix}"


@pytest.fixture
def types(orgs):
    club = orgs["a"]
    return {
        "frei": MemberType.objects.create(organization=club, name="Schnupper"),
        "benutzt": MemberType.objects.create(organization=club, name="passiv"),
    }


class TestLoeschen:
    def test_unbenutzte_art_wird_geloescht(self, orgs, board_a, api, types):
        c = api(board_a)
        usage = c.get(url(orgs["a"], types["frei"], "usage/")).json()
        assert usage == {"deletable": True, "reasons": [], "is_archived": False}
        assert c.delete(url(orgs["a"], types["frei"])).status_code == 204
        assert not MemberType.objects.filter(pk=types["frei"].pk).exists()
        assert AuditEntry.objects.filter(organization=orgs["a"], action="delete").exists()

    def test_benutzte_art_nur_archivieren(self, orgs, board_a, api, types):
        make_member(orgs["a"], "Paul", "Passiv", "p@example.org", member_type=types["benutzt"])
        make_member(orgs["a"], "Pia", "Passiv", "pia@example.org", member_type=types["benutzt"])
        c = api(board_a)
        usage = c.get(url(orgs["a"], types["benutzt"], "usage/")).json()
        assert usage["deletable"] is False
        assert usage["reasons"] == ["in 2 Mitgliedszeiträumen verwendet"]
        resp = c.delete(url(orgs["a"], types["benutzt"]))
        assert resp.status_code == 409
        assert resp.json()["can_archive"] is True
        assert "in 2 Mitgliedszeiträumen verwendet" in resp.json()["reasons"]
        assert MemberType.objects.filter(pk=types["benutzt"].pk).exists()

        resp = c.post(url(orgs["a"], types["benutzt"], "archive/"))
        assert resp.status_code == 200 and resp.json()["is_archived"] is True
        # bleibt in der Liste (für Historie, Filter, Akte)
        names = [t["name"] for t in c.get(f"/api/orgs/{orgs['a'].pk}/member-types/").json()]
        assert "passiv" in names
        resp = c.post(url(orgs["a"], types["benutzt"], "restore/"))
        assert resp.json()["is_archived"] is False
        assert AuditEntry.objects.filter(organization=orgs["a"], action="update").count() >= 2

    def test_vorlagen_und_beitraege_zaehlen_als_verwendung(self, orgs, board_a, api, types):
        from billing.models import FeeRate
        from exchange.models import ExportTemplate, ImportTemplate

        mt = types["frei"]
        ImportTemplate.objects.create(
            organization=orgs["a"],
            name="Altdaten",
            mapping={"0": "member_type"},
            value_mapping={"member_type": {"S": str(mt.pk)}},
        )
        ExportTemplate.objects.create(
            organization=orgs["a"], name="Schnupperliste", columns=[], filters={"art": mt.pk}
        )
        FeeRate.objects.create(organization=orgs["a"], member_type=mt, amount=10)
        reasons = api(board_a).get(url(orgs["a"], mt, "usage/")).json()["reasons"]
        assert sorted(reasons) == sorted(
            [
                "in 1 Beitragssatz verwendet",
                "in 1 Import-Vorlage verwendet",
                "in 1 Export-Vorlage verwendet",
            ]
        )

    def test_recht_wie_bearbeiten(self, orgs, api, types):
        leser = make_user("leser@example.org")
        give_role(leser, orgs["a"], permissions=["members.view"], name="Leser")
        c = api(leser)
        assert c.get(url(orgs["a"], types["frei"], "usage/")).status_code == 200
        assert c.delete(url(orgs["a"], types["frei"])).status_code == 403
        assert c.post(url(orgs["a"], types["frei"], "archive/")).status_code == 403

    def test_fremder_verein(self, orgs, board_b, api, types):
        assert api(board_b).delete(url(orgs["a"], types["frei"])).status_code == 404


class TestArchiviertNichtFuerNeues:
    def test_aufnahme_und_artwechsel_abgelehnt(self, orgs, board_a, api, types):
        types["frei"].is_archived = True
        types["frei"].save()
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/members/admit/",
            {
                "last_name": "Neu",
                "first_name": "Nina",
                "birth_date": "1990-01-01",
                "member_type": types["frei"].pk,
                "entry_date": "2024-01-01",
                "email": "nina@example.org",
                "street": "Weg 1",
                "postal_code": "12345",
                "city": "Ort",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "nicht mehr verwendet" in str(resp.json())
        m = make_member(orgs["a"], "Paul", "Passiv", "p@example.org", member_type=types["benutzt"])
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/members/{m.pk}/change-type/",
            {"member_type": types["frei"].pk, "valid_from": "2025-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "nicht mehr verwendet" in str(resp.json())
