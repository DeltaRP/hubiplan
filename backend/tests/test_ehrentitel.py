"""Ehrungen: Bezeichnungen je Verein/Dachverband, Verleihung, Beitrag, Filter, Rundschreiben."""

import datetime
from decimal import Decimal

import pytest

from audit.models import AuditEntry
from billing import services as billing
from core.tenancy import tenant_context
from members.models import HonoraryTitle, HonoraryTitleAward, MemberType

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


def titles_url(org, suffix=""):
    return f"/api/orgs/{org.pk}/honorary-titles/{suffix}"


def awards_url(org, membership, suffix=""):
    return f"/api/orgs/{org.pk}/members/{membership.pk}/honorary-titles/{suffix}"


def fed_awards_url(fed, membership, suffix=""):
    return f"/api/orgs/{fed.pk}/federation/members/{membership.pk}/honorary-titles/{suffix}"


@pytest.fixture
def fed(orgs):
    fed = orgs["federation"]
    fed.federation_member_access = "read"
    fed.save()
    return fed


@pytest.fixture
def fed_user(fed):
    user = make_user("vorstand-bund@example.org")
    give_role(user, fed)
    return user


@pytest.fixture
def members(orgs):
    a = orgs["a"]
    return {
        "anna": make_member(a, "Anna", "Aktiv"),
        "emil": make_member(a, "Emil", "Ehre"),
        "max": make_member(a, "Max", "Major"),
    }


def create_title(c, org, name, **extra):
    resp = c.post(titles_url(org), {"name": name, **extra}, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()["id"]


def award(c, url, title, valid_from="2020-01-01", **extra):
    resp = c.post(url, {"title": title, "valid_from": valid_from, **extra}, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()


class TestBezeichnungen:
    def test_anlegen_pruefen_und_eindeutig(self, orgs, board_a, api):
        c = api(board_a)
        create_title(c, orgs["a"], "Ehrenmitglied", fee_mode="free")
        resp = c.post(titles_url(orgs["a"]), {"name": "ehrenmitglied"}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.post(
            titles_url(orgs["a"]), {"name": "Ehrenmajor", "fee_mode": "amount"}, content_type=JSON
        )
        assert resp.status_code == 400 and "fee_amount" in resp.json()
        resp = c.post(
            titles_url(orgs["a"]),
            {"name": "Ehrenmajor", "fee_mode": "discount", "fee_discount_percent": "150"},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "fee_discount_percent" in resp.json()
        tid = create_title(
            c, orgs["a"], "Ehrenmajor", fee_mode="discount", fee_discount_percent="50"
        )
        data = {t["id"]: t for t in c.get(titles_url(orgs["a"])).json()}
        assert data[tid]["fee_text"] == "50 % Abschlag"
        assert data[tid]["own"] is True

    def test_verliehen_nur_archivieren(self, orgs, board_a, api, members):
        c = api(board_a)
        tid = create_title(c, orgs["a"], "Ehrenmitglied")
        frei = create_title(c, orgs["a"], "Ungenutzt")
        award(c, awards_url(orgs["a"], members["emil"]), tid)
        assert c.delete(titles_url(orgs["a"], f"{tid}/")).status_code == 409
        assert c.post(titles_url(orgs["a"], f"{tid}/archive/")).json()["is_archived"] is True
        assert c.delete(titles_url(orgs["a"], f"{frei}/")).status_code == 204

    def test_verein_sieht_titel_des_dachverbands_nicht_eines_anderen_vereins(
        self, orgs, board_a, board_b, fed_user, api
    ):
        create_title(api(fed_user), orgs["federation"], "Ehrenoberst")
        create_title(api(board_b), orgs["b"], "Ehrenkönig")
        c = api(board_a)
        create_title(c, orgs["a"], "Ehrenmitglied")
        assert [t["name"] for t in c.get(titles_url(orgs["a"])).json()] == ["Ehrenmitglied"]
        rows = c.get(titles_url(orgs["a"], "?alle=1")).json()
        assert [(t["name"], t["own"]) for t in rows] == [
            ("Ehrenmitglied", True),
            ("Ehrenoberst", False),
        ]


class TestVerleihung:
    def test_verleihen_mit_zeitraum_und_protokoll(self, orgs, board_a, api, members):
        c = api(board_a)
        tid = create_title(c, orgs["a"], "Ehrenmitglied")
        url = awards_url(orgs["a"], members["emil"])
        first = award(c, url, tid, valid_from="2010-01-01", valid_until="2015-12-31")
        award(c, url, tid, valid_from="2020-01-01")
        # Überschneidung mit derselben Verleihung
        resp = c.post(url, {"title": tid, "valid_from": "2021-01-01"}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.patch(f"{url}{first['id']}/", {"valid_until": "2009-01-01"}, content_type=JSON)
        assert resp.status_code == 400
        detail = c.get(f"/api/orgs/{orgs['a'].pk}/members/{members['emil'].pk}/").json()
        assert [a["valid_from"] for a in detail["honorary_titles"]["own"]] == [
            "2010-01-01",
            "2020-01-01",
        ]
        assert AuditEntry.objects.filter(
            organization=orgs["a"], person_id=members["emil"].person_id, action="create"
        ).exists()

    def test_nur_jahr_der_verleihung(self, orgs, board_a, api, members):
        """Ralf 2026-10-31: Ehrung wahlweise nur mit dem Jahr der Verleihung."""
        c = api(board_a)
        tid = create_title(c, orgs["a"], "Ehrennadel", year_only=True)
        assert c.get(titles_url(orgs["a"])).json()[0]["year_only"] is True
        url = awards_url(orgs["a"], members["emil"])
        got = award(c, url, tid, valid_from="1998-06-15")
        assert got["valid_from"] == "1998-01-01"
        assert got["valid_until"] is None
        assert got["year_only"] is True
        resp = c.patch(f"{url}{got['id']}/", {"valid_from": "2001-03-03"}, content_type=JSON)
        assert resp.json()["valid_from"] == "2001-01-01"

    def test_fremder_titel_nicht_waehlbar(self, orgs, board_a, board_b, api, members):
        fremd = create_title(api(board_b), orgs["b"], "Ehrenkönig")
        resp = api(board_a).post(
            awards_url(orgs["a"], members["emil"]),
            {"title": fremd, "valid_from": "2020-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_dachverband_verleiht_eigene_titel(self, orgs, fed, fed_user, board_a, api, members):
        f = api(fed_user)
        tid = create_title(f, fed, "Ehrenoberst")
        award(f, fed_awards_url(fed, members["max"]), tid)
        # Verein sieht ihn (nur lesen), Dachverbandstitel stehen nicht unter „own“
        detail = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/members/{members['max'].pk}/").json()
        assert detail["honorary_titles"]["own"] == []
        assert [a["title_name"] for a in detail["honorary_titles"]["federation"]] == ["Ehrenoberst"]
        # Verein kann den Titel des Dachverbands nicht selbst verleihen
        resp = api(board_a).post(
            awards_url(orgs["a"], members["anna"]),
            {"title": tid, "valid_from": "2020-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_dachverband_ohne_mitgliederzugriff(self, orgs, fed, fed_user, api, members):
        fed.federation_member_access = "none"
        fed.save()
        f = api(fed_user)
        tid = create_title(f, fed, "Ehrenoberst")
        resp = f.post(
            fed_awards_url(fed, members["max"]),
            {"title": tid, "valid_from": "2020-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 403


class TestListe:
    def test_filter_spalte_und_sortierung(self, orgs, fed, fed_user, board_a, api, members):
        c = api(board_a)
        ehren = create_title(c, orgs["a"], "Ehrenmitglied", sort_order=1)
        major = create_title(c, orgs["a"], "Ehrenmajor", sort_order=2)
        award(c, awards_url(orgs["a"], members["emil"]), ehren)
        award(c, awards_url(orgs["a"], members["max"]), major)
        # abgelaufener Titel zählt nicht
        award(
            c,
            awards_url(orgs["a"], members["anna"]),
            major,
            valid_from="2000-01-01",
            valid_until="2001-01-01",
        )
        oberst = create_title(api(fed_user), fed, "Ehrenoberst")
        award(api(fed_user), fed_awards_url(fed, members["max"]), oberst)

        base = f"/api/orgs/{orgs['a'].pk}/members/"
        rows = c.get(f"{base}?ehrentitel={ehren}").json()["results"]
        assert [r["first_name"] for r in rows] == ["Emil"]
        rows = c.get(f"{base}?ehrentitel={oberst}").json()["results"]
        assert [r["first_name"] for r in rows] == ["Max"]
        assert rows[0]["honorary_titles"] == ["Ehrenmajor", "Ehrenoberst"]
        rows = c.get(f"{base}?ehrentitel=mit").json()["results"]
        assert sorted(r["first_name"] for r in rows) == ["Emil", "Max"]
        rows = c.get(f"{base}?sortierung=ehrentitel").json()["results"]
        assert [r["first_name"] for r in rows] == ["Emil", "Max", "Anna"]
        rows = c.get(f"{base}?sortierung=-ehrentitel").json()["results"]
        assert [r["first_name"] for r in rows] == ["Max", "Emil", "Anna"]

    def test_dachverbandsliste_zeigt_titel(self, orgs, fed, fed_user, board_a, api, members):
        ehren = create_title(api(board_a), orgs["a"], "Ehrenmitglied")
        award(api(board_a), awards_url(orgs["a"], members["emil"]), ehren)
        rows = api(fed_user).get(f"/api/orgs/{fed.pk}/federation/members/").json()["results"]
        assert {r["first_name"]: r["honorary_titles"] for r in rows}["Emil"] == ["Ehrenmitglied"]

    def test_dachverbandsliste_filtert_nach_eigenem_titel(
        self, orgs, fed, fed_user, board_a, api, members
    ):
        f = api(fed_user)
        oberst = create_title(f, fed, "Ehrenoberst")
        award(f, fed_awards_url(fed, members["max"]), oberst)
        base = f"/api/orgs/{fed.pk}/federation/members/"
        rows = f.get(f"{base}?ehrentitel={oberst}").json()["results"]
        assert [r["first_name"] for r in rows] == ["Max"]
        rows = f.get(f"{base}?ehrentitel=mit").json()["results"]
        assert [r["first_name"] for r in rows] == ["Max"]


class TestDatenuebernahme:
    def test_export_und_import_mit_titeln_beider_ebenen(
        self, orgs, fed, fed_user, board_a, api, members, settings, tmp_path, monkeypatch
    ):
        from core.tenancy import rls_bypass
        from organizations.models import Organization

        from .test_datatransfer import upload

        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.PRIVATE_ROOT = tmp_path / "private"
        monkeypatch.setattr("django.db.transaction.on_commit", lambda func, *a, **k: func())
        c = api(board_a)
        award(
            c, awards_url(orgs["a"], members["emil"]), create_title(c, orgs["a"], "Ehrenmitglied")
        )
        f = api(fed_user)
        award(f, fed_awards_url(fed, members["max"]), create_title(f, fed, "Ehrenoberst"))

        from organizations.models import Organization as Org

        admin = make_user("plattform@example.org")
        give_role(admin, Org.platform())
        p = api(admin)
        resp = p.post(
            "/api/platform/datatransfer/exports/", {"organization": fed.pk}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        content = b"".join(
            p.get(
                f"/api/platform/datatransfer/exports/{resp.json()['id']}/download/"
            ).streaming_content
        )
        job = upload(p, "/api/platform", content, name="Kopie Verband", invite=False)
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        p.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = p.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        copy = Organization.objects.get(pk=job["result_organization"]["id"])
        with rls_bypass():
            got = {
                (a.organization.type, a.title.name, a.person.first_name)
                for a in HonoraryTitleAward.objects.filter(
                    organization__in=[copy, *copy.children.all()]
                ).select_related("organization", "title", "person")
            }
        assert got == {("club", "Ehrenmitglied", "Emil"), ("federation", "Ehrenoberst", "Max")}


class TestBeitrag:
    @pytest.fixture
    def setup(self, orgs, members):
        a = orgs["a"]
        a.enabled_modules = ["finance", "members", "billing"]
        a.save()
        with tenant_context(a.pk):
            from billing.models import FeeRate

            aktiv = MemberType.objects.get(organization=a, name="aktiv")
            FeeRate.objects.create(organization=a, member_type=aktiv, amount=Decimal("60"))
            titles = {
                "frei": HonoraryTitle.objects.create(
                    organization=a, name="Ehrenmitglied", fee_mode="free"
                ),
                "fest": HonoraryTitle.objects.create(
                    organization=a, name="Ehrenmajor", fee_mode="amount", fee_amount=Decimal("20")
                ),
                "rabatt": HonoraryTitle.objects.create(
                    organization=a,
                    name="Jubilar",
                    fee_mode="discount",
                    fee_discount_percent=Decimal("25"),
                ),
                "ohne": HonoraryTitle.objects.create(organization=a, name="Ehrenzeichen"),
            }
        return a, titles

    def give(self, org, membership, title, start=datetime.date(2020, 1, 1), end=None):
        with tenant_context(org.pk):
            HonoraryTitleAward.objects.create(
                organization=org,
                person_id=membership.person_id,
                title=title,
                valid_from=start,
                valid_until=end,
            )

    def test_vereinsbeitrag_guenstigster_titel(self, setup, members):
        a, t = setup
        self.give(a, members["emil"], t["frei"])
        self.give(a, members["max"], t["fest"])
        self.give(a, members["max"], t["rabatt"])  # 45 > 20: fester Betrag gilt
        self.give(a, members["anna"], t["ohne"])
        with tenant_context(a.pk):
            plan = billing.plan_run(a, billing.period(a, 2025, "yearly", 1))
        amounts = {i.membership.pk: i.amount for i in plan.member_items}
        assert amounts[members["anna"].pk] == Decimal("60.00")
        assert amounts[members["max"].pk] == Decimal("20.00")
        assert members["emil"].pk not in amounts
        skipped = {s["membership"]: s["reason"] for s in plan.skipped}
        assert skipped[members["emil"].pk] == "beitragsfrei (Ehrenmitglied)"
        detail = next(i.detail for i in plan.member_items if i.membership == members["max"])
        assert "Ehrenmajor" in detail

    def test_abschlag_und_abgelaufener_titel(self, setup, members):
        a, t = setup
        self.give(a, members["max"], t["rabatt"])
        self.give(a, members["anna"], t["frei"], end=datetime.date(2024, 12, 31))
        with tenant_context(a.pk):
            plan = billing.plan_run(a, billing.period(a, 2025, "yearly", 1))
        amounts = {i.membership.pk: i.amount for i in plan.member_items}
        assert amounts[members["max"].pk] == Decimal("45.00")
        assert amounts[members["anna"].pk] == Decimal("60.00")

    def test_verbandsbeitrag_mit_titel_des_dachverbands(self, orgs, fed, members):
        from billing.models import BillingSettings

        BillingSettings.objects.create(
            organization=fed, club_rate_active=Decimal("10"), club_rate_passive=Decimal("4")
        )
        with tenant_context(fed.pk):
            frei = HonoraryTitle.objects.create(
                organization=fed, name="Ehrenoberst", fee_mode="free"
            )
            halb = HonoraryTitle.objects.create(
                organization=fed,
                name="Ehrenhauptmann",
                fee_mode="discount",
                fee_discount_percent=Decimal("50"),
            )
        self.give(fed, members["emil"], frei)
        self.give(fed, members["max"], halb)
        with tenant_context(fed.pk):
            items = billing.plan_federation_run(fed, billing.period(fed, 2025, "yearly", 1))
        item = next(i for i in items if i.club == orgs["a"])
        assert item.members == 3
        # Anna 10 + Max 5, Emil beitragsfrei
        assert item.total == Decimal("15.00")
        assert any("Ehrenhauptmann" in text for text, *_ in item.lines)


class TestRundschreiben:
    def test_empfaenger_nach_ehrentitel(self, orgs, fed, fed_user, board_a, api, members):
        c = api(board_a)
        ehren = create_title(c, orgs["a"], "Ehrenmitglied")
        award(c, awards_url(orgs["a"], members["emil"]), ehren)
        oberst = create_title(api(fed_user), fed, "Ehrenoberst")
        award(api(fed_user), fed_awards_url(fed, members["max"]), oberst)

        from circulars.models import Circular
        from circulars.recipients import club_candidates, federation_member_candidates

        with tenant_context(orgs["a"].pk):
            circular = Circular.objects.create(
                organization=orgs["a"], filters={"honorary_titles": [ehren, oberst]}
            )
            found, _ = club_candidates(circular)
        assert sorted(x.first_name for x in found if not x.included) == ["Emil", "Max"]

        with tenant_context(fed.pk):
            from core.tenancy import get_rls, set_rls

            state = get_rls()
            set_rls(fed.pk, state.user_id, scope_id=fed.pk, fed_access="read")
            circular = Circular.objects.create(
                organization=fed, audience="members", filters={"honorary_titles": [oberst]}
            )
            found = federation_member_candidates(circular)
        assert [x.first_name for x in found if not x.included] == ["Max"]

    def test_optionen_enthalten_titel(self, orgs, fed, fed_user, board_a, api):
        create_title(api(fed_user), fed, "Ehrenoberst")
        create_title(api(board_a), orgs["a"], "Ehrenmitglied")
        resp = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/circulars/options/")
        assert resp.status_code == 200, resp.content
        names = [t["name"] for t in resp.json()["honorary_titles"]]
        assert names == ["Ehrenmitglied", "Ehrenoberst (Testbund)"]
