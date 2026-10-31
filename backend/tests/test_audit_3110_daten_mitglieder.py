"""Audit Datenspeicherung und Berechnungen 31.10.: Mitglieder, Statistik, Würden."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime

import pytest
from django.test import Client
from django.utils import timezone

from honors.models import Reign
from members.models import FederationMember

from .test_einheiten_direktmitglieder import board_fed, einschalten, fed, rls, types  # noqa: F401
from .test_m2_members import admit, make_types
from .test_wuerden import koenig, people, private_root, site  # noqa: F401

pytestmark = pytest.mark.django_db
JSON = "application/json"


def member_url(org, member, suffix=""):
    return f"/api/orgs/{org.pk}/members/{member['id']}/{suffix}"


class TestM3101Geburtstage:
    def test_nach_austritt_kein_geburtstag(self, api, orgs, board_a):
        org = orgs["a"]
        t = make_types(org)
        c = api(board_a)
        m = admit(c, org, t["aktiv"], last_name="Weg", birth_date="1980-11-20").json()
        resp = c.post(
            member_url(org, m, "exit/"),
            {"exit_date": "2026-11-02", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert resp.status_code in (200, 201), resp.json()
        data = c.get(
            f"/api/orgs/{org.pk}/birthdays/", {"von": "2026-11-01", "bis": "2026-11-30"}
        ).json()
        assert data["results"] == []

    def test_geburtstag_in_der_luecke_fehlt(self, api, orgs, board_a):
        org = orgs["a"]
        t = make_types(org)
        c = api(board_a)
        m = admit(c, org, t["aktiv"], last_name="Luecke", birth_date="1980-03-10").json()
        resp = c.post(
            member_url(org, m, "periods/"),
            {"entry_date": "2000-01-01", "exit_date": "2005-02-28", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        # Geburtstag 10.03.2005 liegt zwischen Austritt 2005 und Eintritt 2015
        data = c.get(
            f"/api/orgs/{org.pk}/birthdays/", {"von": "2005-02-01", "bis": "2005-04-30"}
        ).json()
        assert data["results"] == []


class TestM3103Geburtsdatum:
    def test_geburtsdatum_nach_eintritt_abgelehnt(self, api, orgs, board_a):
        org = orgs["a"]
        t = make_types(org)
        c = api(board_a)
        m = admit(c, org, t["aktiv"]).json()  # Eintritt 2015-03-01
        for value in ("9999-01-01", "2016-01-01"):
            resp = c.patch(member_url(org, m), {"birth_date": value}, content_type=JSON)
            assert resp.status_code == 400, value
            assert "birth_date" in resp.json()
        ok = c.patch(member_url(org, m), {"birth_date": "1981-01-01"}, content_type=JSON)
        assert ok.status_code == 200


class TestM3104Nachtrag:
    def test_aktive_zeit_in_anderem_verein_gesperrt(self, api, orgs, board_a, board_b):
        ta, tb = make_types(orgs["a"]), make_types(orgs["b"])
        b = api(board_b)
        mb = admit(b, orgs["b"], tb["aktiv"], entry_date="1995-01-01").json()
        a = api(board_a)
        ma = admit(a, orgs["a"], ta["foerder"], person=mb["person_id"]).json()
        resp = a.post(
            member_url(orgs["a"], ma, "periods/"),
            {
                "entry_date": "2000-01-01",
                "exit_date": "2014-12-31",
                "exit_reason": "exit",
                "member_type": ta["aktiv"].pk,
            },
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "aktives" in str(resp.json()["member_type"])

    def test_erste_gemeldete_zeit_vergibt_verbandsnummer(self, api, orgs, board_a):
        org = orgs["a"]
        t = make_types(org)
        c = api(board_a)
        m = admit(c, org, t["foerder"]).json()
        assert m["federation"]["member_number"] is None
        resp = c.post(
            member_url(org, m, "periods/"),
            {
                "entry_date": "2001-01-01",
                "exit_date": "2005-12-31",
                "exit_reason": "exit",
                "member_type": t["passiv"].pk,
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert FederationMember.objects.filter(person_id=m["person_id"]).exists()


@pytest.mark.usefixtures("rls")
class TestM3102Dachverbandsakte:
    def test_zusatzfelder_und_ehrungen_eigener_mitglieder(self, api, fed, types, board_fed):
        c = api(board_fed)
        einschalten(c, fed)
        m = admit(c, fed, types["fed"]["passiv"], last_name="Direkt").json()
        assert c.get(member_url(fed, m, "fields/")).status_code == 200
        assert c.get(member_url(fed, m, "honorary-titles/")).status_code == 200


class TestM3105AktuelleWuerde:
    def test_genauer_zeitraum_mit_ende_ist_aktuell(self, orgs, site, people, koenig):
        today = timezone.localdate()
        org = orgs["a"]
        Reign.objects.create(organization=org, dignity=koenig, year=today.year - 3, name="Alt Mann")
        Reign.objects.create(
            organization=org,
            dignity=koenig,
            valid_from=today - datetime.timedelta(days=30),
            valid_until=today + datetime.timedelta(days=30),
            name="Jetzt König",
        )
        Reign.objects.create(organization=org, dignity=koenig, year=today.year + 1, name="Zukunft")
        data = Client().get("/api/public/site/v1/schluessel-w/honors/").json()
        current = [e["holder"]["name"] for e in data["dignities"][0]["current"]]
        assert "Jetzt König" in current and "Zukunft" not in current
