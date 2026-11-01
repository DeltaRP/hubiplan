"""Wettbewerbe Schritt 5: Ergebnisse auf der Webseite (öffentliche Schnittstelle, alles
erfunden). Ralf 2026-11-01: eigener Baustein „Ergebnisse“ und Block auf der Startseite;
live fragt die Seite alle 15 Sekunden nach."""

import datetime
from decimal import Decimal

import pytest
from django.test import Client

from competitions.models import AwardGrant, Competition, Score, Scoring, Series, Starter, Trophy
from organizations.models import Department
from website import services
from website.models import Website

from .factories import make_member

pytestmark = pytest.mark.django_db(transaction=True)


def get(path):
    return Client().get(f"/api/public/site/v1/schluessel-a/{path}")


@pytest.fixture
def setup(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "website", "competitions"]
    org.save()
    site = Website.objects.create(
        organization=org, public_key="schluessel-a", state="public", name_format="initial"
    )
    zug = Department.objects.create(organization=org, parent=org, name="Zug 1")
    max_ = make_member(org, "Max", "Muster", departments=[zug])
    erika = make_member(org, "Erika", "Beispiel", departments=[zug])
    jung = make_member(
        org, "Jonas", "Jung", departments=[zug], birth_date=datetime.date(2012, 5, 1)
    )
    reihe = Series.objects.create(organization=org, name="Vereinsmeisterschaft")
    comp = Competition.objects.create(
        organization=org,
        title="Vereinsmeisterschaft 2027",
        date=datetime.date(2027, 6, 14),
        website="abschluss",
        website_depth="alle",
        series=reihe,
    )
    einzel = Scoring.objects.create(organization=org, competition=comp, name="Einzel")
    zugw = Scoring.objects.create(
        organization=org,
        competition=comp,
        name="Zugwertung",
        kind="einheit",
        source=einzel,
        team_size=2,
    )
    st = {}
    for m, v in ((max_, 30), (erika, 28), (jung, 27)):
        s = Starter.objects.create(
            organization=org,
            competition=comp,
            membership=m,
            name=f"{m.person.first_name} {m.person.last_name}",
            unit=zug,
        )
        Score.objects.create(organization=org, scoring=einzel, starter=s, value=Decimal(v))
        st[m.person.first_name] = s
    gast = Starter.objects.create(
        organization=org, competition=comp, name="Gerd Gast", club="Nachbarverein"
    )
    Score.objects.create(organization=org, scoring=einzel, starter=gast, value=Decimal(20))
    return {
        "org": org,
        "site": site,
        "comp": comp,
        "max": max_,
        "erika": erika,
        "jung": jung,
        "reihe": reihe,
        "zugw": zugw,
        "st": st,
    }


class TestErgebnisse:
    def test_sichtbar_erst_nach_abschluss(self, setup):
        comp = setup["comp"]
        info = get("").json()
        assert info["results_url"].endswith("/results/")
        assert get("results/").json()["competitions"] == []
        comp.status = "laeuft"
        comp.save()
        assert get("results/").json()["competitions"] == []
        # live: schon während des Wettbewerbs, mit Vermerk und kurzer Zwischenspeicherung
        comp.website = "live"
        comp.save()
        data = get("results/").json()
        assert data["competitions"][0]["live"] is True and data["poll_seconds"] == 15
        url = data["competitions"][0]["id"]
        resp = get(f"results/{url}/")
        assert resp.status_code == 200 and "max-age=5" in resp["Cache-Control"]
        body = resp.json()
        assert body["poll_seconds"] == 15
        v1 = get(f"results/{url}/version/").json()["version"]
        score = Score.objects.get(starter=setup["st"]["Erika"])
        score.value = Decimal(29)
        score.save()
        assert get(f"results/{url}/version/").json()["version"] != v1
        # aus: nicht mehr da
        comp.website = "aus"
        comp.save()
        assert get(f"results/{url}/").status_code == 404

    def test_namen_einwilligung_und_umfang(self, setup):
        comp = setup["comp"]
        comp.status = "endgueltig"
        comp.save()
        token = get("results/").json()["competitions"][0]["id"]
        rows = get(f"results/{token}/").json()["scorings"][0]["rows"]
        names = [r["name"] for r in rows]
        # Namensform „Vorname N.“; unter 18 ohne Einwilligung ohne Namen; Gast mit Verein
        assert names == ["Max M.", "Erika B.", "ohne Namen", "Gerd G."]
        assert rows[3]["club"] == "Nachbarverein"
        services.set_entry(setup["jung"], "minor_res", True, "paper", None)
        services.set_entry(setup["max"], "results", True, "member", None)
        rows = get(f"results/{token}/").json()["scorings"][0]["rows"]
        assert [r["name"] for r in rows][:3] == ["ohne Namen", "Erika B.", "Jonas J."]
        assert rows[0]["place"] == 1  # der Platz bleibt
        comp.website_depth = "top3"
        comp.save()
        data = get(f"results/{token}/").json()
        assert len(data["scorings"][0]["rows"]) == 3 and not data["scorings"][0]["complete"]
        comp.website_depth = "einheiten"
        comp.save()
        data = get(f"results/{token}/").json()
        assert [s["name"] for s in data["scorings"]] == ["Zugwertung"]
        assert data["scorings"][0]["rows"][0]["name"] == "Zug 1"

    def test_reihe_pokal_und_startseite(self, setup):
        org, comp = setup["org"], setup["comp"]
        comp.status = "endgueltig"
        comp.save()
        pokal = Trophy.objects.create(organization=org, name="Zugpokal")
        AwardGrant.objects.create(
            organization=org,
            competition=comp,
            series=setup["reihe"],
            year=2027,
            title="Vereinsmeister",
            name="Max Muster",
            membership=setup["max"],
        )
        AwardGrant.objects.create(
            organization=org,
            year=2026,
            trophy=pokal,
            name="Zug 1",
            unit_id=Department.objects.get(name="Zug 1").pk,
            manual=True,
        )
        AwardGrant.objects.create(
            organization=org,
            year=1999,
            series=setup["reihe"],
            title="Vereinsmeister",
            name="Karl Früher",
            manual=True,
        )
        data = get("results/").json()
        assert data["trophies"][0]["holders"] == [{"year": 2026, "name": "Zug 1", "kept": False}]
        serie = get(f"results/series/{data['series'][0]['id']}/").json()
        assert serie["years"][0]["winners"][0]["names"] == ["Max M."]
        assert {(t["year"], t["name"]) for t in serie["titles"]} == {
            (2027, "Max M."),
            (1999, "Karl F."),
        }
        start = get("results/?start=1").json()["competitions"]
        assert start[0]["title"] == "Vereinsmeisterschaft 2027"
        assert [r["name"] for r in start[0]["scorings"][0]["rows"]] == [
            "Max M.",
            "Erika B.",
            "ohne Namen",
        ]
        # Startseitenblock: erst an, wenn gewählt; nur mit Baustein und Modul
        site = setup["site"]
        assert "results" not in get("").json()["home"]
        site.home_sections = [{"key": "results", "on": True}]
        site.save()
        assert "results" in get("").json()["home"]
        site.blocks = {**site.blocks, "results": False}
        site.save()
        assert "results" not in get("").json()["home"]
        assert get("results/").status_code == 404

    def test_ohne_modul_nichts(self, setup):
        org = setup["org"]
        org.enabled_modules = ["members", "website"]
        org.save()
        assert get("results/").status_code == 404
        info = get("").json()
        assert info["results_url"] is None and "results" not in info["home"]
        assert all(n["key"] != "results" for n in info["nav"])


class TestMeineErgebnisse:
    def test_mitgliederbereich(self, setup, api):
        from portal.models import PortalAccess

        from .factories import make_user

        org, comp = setup["org"], setup["comp"]
        org.member_portal_enabled = True
        org.save()
        comp.status = "endgueltig"
        comp.save()
        AwardGrant.objects.create(
            organization=org,
            competition=comp,
            year=2027,
            title="Vereinsmeister",
            name="Max Muster",
            membership=setup["max"],
        )
        Competition.objects.create(
            organization=org, title="Noch in Vorbereitung", date=datetime.date(2028, 1, 1)
        )
        user = make_user("max@example.org")
        access = PortalAccess.objects.create(organization=org, membership=setup["max"], user=user)
        data = api(user).get(f"/api/portal/{access.pk}/results/").json()
        assert [s["title"] for s in data["starts"]] == ["Vereinsmeisterschaft 2027"]
        assert data["starts"][0]["results"][0]["place"] == 1
        assert [g["full_title"] for g in data["grants"]] == ["Vereinsmeister 2027"]
        info = api(user).get("/api/me/contexts/").json()["portal"][0]
        assert info["competitions_enabled"] is True
        # fremder Zugang: 404
        other = make_user("erika@example.org")
        assert api(other).get(f"/api/portal/{access.pk}/results/").status_code == 404
