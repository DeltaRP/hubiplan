"""Dashboards: Mitglieder- und Finanzentwicklung über die Zeit."""

import datetime
from decimal import Decimal

import pytest

from core.tenancy import tenant_context
from finance.models import Account, Booking, Category
from members import workflows
from members.models import DepartmentRoleHolder, MemberType
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def verein(orgs):
    club = orgs["a"]
    club.enabled_modules = ["members", "finance"]
    club.department_access_enabled = True
    club.save()
    with tenant_context(club.pk):
        aktiv = MemberType.objects.create(organization=club, name="aktiv", active=True)
        passiv = MemberType.objects.create(organization=club, name="passiv", reported=False)
        zug = Department.objects.create(
            self_managed=True, organization=club, name="Jägerzug", founding_year=1950
        )
    a = make_member(
        club,
        "Anna",
        "Alt",
        member_type=aktiv,
        entry_date=D(2020, 3, 1),
        birth_date=D(1950, 6, 1),
        departments=[zug],
    )
    b = make_member(
        club,
        "Bernd",
        "Bach",
        member_type=aktiv,
        entry_date=D(2025, 2, 10),
        birth_date=D(2010, 1, 1),
    )
    c = make_member(
        club,
        "Clara",
        "Christ",
        member_type=aktiv,
        entry_date=D(2025, 3, 5),
        birth_date=D(1990, 1, 1),
        departments=[zug],
    )
    with tenant_context(club.pk):
        # Clara wird passiv, Anna tritt Ende März aus
        workflows.change_type(c, passiv, D(2025, 4, 1))
        workflows.exit_membership(a, D(2025, 3, 31), "death")
    return {"club": club, "zug": zug, "a": a, "b": b, "c": c}


def get(c, url, **params):
    resp = c.get(url, params)
    assert resp.status_code == 200, resp.json()
    return resp.json()


class TestMitgliederentwicklung:
    def test_bestand_eintritte_austritte_je_monat(self, api, board_a, verein):
        data = get(
            api(board_a),
            f"/api/orgs/{verein['club'].pk}/members/statistics/",
            von="2025-01",
            bis="2025-04",
        )
        assert data["raster"] == "monat"
        assert [b["label"] for b in data["buckets"]] == [
            "Jan. 2025",
            "Feb. 2025",
            "März 2025",
            "Apr. 2025",
        ]
        assert [b["count"] for b in data["buckets"]] == [1, 2, 2, 2]
        assert [b["entries"] for b in data["buckets"]] == [0, 1, 1, 0]
        assert [b["exits"] for b in data["buckets"]] == [0, 0, 1, 0]
        assert data["summary"] == {"start": 1, "end": 2, "entries": 2, "exits": 1}
        assert data["exit_reasons"] == [{"reason": "death", "label": "Tod", "count": 1}]
        types = {s["name"]: s["values"] for s in data["types"]}
        # Clara wechselt zum 1. April: am Stichtag 31. März zählt sie schon als passiv
        assert types == {"aktiv": [1, 2, 1, 1], "passiv": [0, 0, 1, 1]}
        assert data["groups_title"] == "Abteilung"
        groups = {s["name"]: s["values"] for s in data["groups"]}
        assert groups == {"Jägerzug": [1, 1, 1, 1], "ohne Abteilung": [0, 1, 1, 1]}
        assert data["ages"]["start"][data["ages"]["groups"].index("70 bis 79")] == 1
        assert data["ages"]["end"][0] == 1  # Bernd ist unter 18
        # Ende April 2025: Bernd 15, Clara 35
        # Streuung über den ganzen Bestand (n, nicht n−1; Fachfrage 7, Audit 31.10.)
        assert data["ages"]["end_summary"] == {"count": 2, "mean": 25.0, "sd": 10.0}
        # Am Anfang nur Anna: ein Wert, Streuung 0
        assert data["ages"]["start_summary"]["count"] == 1
        assert data["ages"]["start_summary"]["sd"] == 0.0
        assert data["earliest"] == "2020-03-01"

    def test_jahresraster_und_standard(self, api, board_a, verein):
        c = api(board_a)
        url = f"/api/orgs/{verein['club'].pk}/members/statistics/"
        data = get(c, url, von="2019-06", bis="2025-12", raster="jahr")
        assert [b["label"] for b in data["buckets"]] == [str(y) for y in range(2019, 2026)]
        assert data["buckets"][0]["start"] == "2019-01-01"
        assert [b["count"] for b in data["buckets"]] == [0, 1, 1, 1, 1, 1, 2]
        # Standard: die letzten zwölf Monate bis heute
        data = get(c, url)
        assert len(data["buckets"]) == 12
        assert data["bis"] == datetime.date.today().isoformat()
        data = get(c, url, von="alles")
        assert data["von"] == "2020-01-01"  # ab dem ersten Eintritt, Jahresraster

    def test_falsche_angaben(self, api, board_a, verein):
        c = api(board_a)
        url = f"/api/orgs/{verein['club'].pk}/members/statistics/"
        assert c.get(url, {"von": "2025-13"}).status_code == 400
        assert c.get(url, {"von": "1900-01", "raster": "monat"}).status_code == 400
        assert c.get(url, {"raster": "woche"}).status_code == 400

    def test_nur_mit_leserecht(self, api, verein):
        user = make_user("kasse@example.org")
        give_role(user, verein["club"], ["finance.view"], name="Kasse")
        resp = api(user).get(f"/api/orgs/{verein['club'].pk}/members/statistics/")
        assert resp.status_code == 403

    def test_dachverband_zaehlt_gemeldete(self, api, orgs, verein):
        fed = orgs["federation"]
        fed.federation_member_access = "read"
        fed.save()
        user = make_user("verband@example.org")
        give_role(user, fed)
        data = get(
            api(user), f"/api/orgs/{fed.pk}/federation/statistics/", von="2025-01", bis="2025-04"
        )
        # Clara wechselt zu einer nicht gemeldeten Art: zählt als Abgang
        assert [b["count"] for b in data["buckets"]] == [1, 2, 1, 1]
        assert data["groups_title"] == "Verein"
        assert [g["name"] for g in data["groups"]] == ["Verein A"]
        reasons = {r["reason"]: r["count"] for r in data["exit_reasons"]}
        assert reasons == {"death": 1, "unreported": 1}

    def test_dachverband_ohne_freigabe(self, api, orgs, verein):
        user = make_user("verband@example.org")
        give_role(user, orgs["federation"])
        resp = api(user).get(f"/api/orgs/{orgs['federation'].pk}/federation/statistics/")
        assert resp.status_code == 403

    def test_abteilung(self, api, verein):
        club, zug = verein["club"], verein["zug"]
        with tenant_context(club.pk):
            role = DepartmentRole.objects.create(
                organization=club, department=zug, name="Spieß", permissions=["dept.members.view"]
            )
            DepartmentRoleHolder.objects.create(
                organization=club, membership=verein["c"], role=role, valid_from="2025-03-05"
            )
        board = make_user("vorstand@example.org")
        give_role(board, club)
        resp = api(board).post(f"/api/orgs/{club.pk}/members/{verein['c'].pk}/access/")
        assert resp.status_code in (200, 201), resp.json()
        user = PortalAccess.objects.get(membership=verein["c"]).user
        data = get(api(user), f"/api/depts/{zug.pk}/statistics/", von="2025-01", bis="2025-04")
        assert [b["count"] for b in data["buckets"]] == [1, 1, 1, 1]
        assert [b["entries"] for b in data["buckets"]] == [0, 0, 1, 0]
        assert data["groups"] == []
        with tenant_context(club.pk):
            role.permissions = ["dept.invoices.view"]
            role.save()
        assert api(user).get(f"/api/depts/{zug.pk}/statistics/").status_code == 403


class TestFinanzentwicklung:
    @pytest.fixture
    def kasse(self, verein):
        club = verein["club"]
        with tenant_context(club.pk):
            bank = Account.objects.create(
                organization=club,
                name="Giro",
                opening_balance=Decimal("1000"),
                opening_date=D(2024, 1, 1),
            )
            bar = Account.objects.create(
                organization=club,
                name="Bar",
                kind="cash",
                opening_balance=Decimal("50"),
                opening_date=D(2025, 2, 1),
            )
            beitrag = Category.objects.create(organization=club, name="Beiträge", kind="income")
            fest = Category.objects.create(organization=club, name="Fest")
            n = iter(range(1, 100))

            def book(day, kind, amount, cat=None, acc=bank, to=None):
                Booking.objects.create(
                    organization=club,
                    year=day.year,
                    number=next(n),
                    date=day,
                    kind=kind,
                    amount=Decimal(amount),
                    account=acc,
                    to_account=to,
                    category=cat,
                    text="x",
                )

            book(D(2024, 3, 1), "income", "200", beitrag)
            book(D(2025, 1, 15), "income", "300", beitrag)
            book(D(2025, 2, 20), "expense", "120", fest)
            book(D(2025, 3, 3), "transfer", "100", to=bar)
            book(D(2025, 3, 31), "income", "80", fest, acc=bar)
        return club

    def test_verlauf_und_vergleich(self, api, board_a, kasse):
        data = get(
            api(board_a), f"/api/orgs/{kasse.pk}/finance/statistics/", von="2025-01", bis="2025-03"
        )
        assert [b["income"] for b in data["buckets"]] == ["300.00", "0.00", "80.00"]
        assert [b["expense"] for b in data["buckets"]] == ["0.00", "120.00", "0.00"]
        assert [b["balance"] for b in data["buckets"]] == ["1500.00", "1430.00", "1510.00"]
        accounts = {a["name"]: a["values"] for a in data["accounts"]}
        assert accounts["Bar"] == [None, "50.00", "230.00"]
        assert accounts["Giro"] == ["1500.00", "1380.00", "1280.00"]
        s = data["summary"]
        assert (s["income"], s["expense"], s["result"]) == ("380.00", "120.00", "260.00")
        assert s["balance_start"] == "1200.00" and s["balance_end"] == "1510.00"
        assert data["previous"] == {"von": "2024-01-01", "bis": "2024-03-31"}
        assert s["previous_income"] == "200.00"
        cats = {c["name"]: c for c in data["categories"]}
        assert cats["Beiträge"]["income"] == "300.00"
        assert cats["Beiträge"]["previous_income"] == "200.00"
        assert cats["Fest"]["expense"] == "120.00"

    def test_geschaeftsjahr_als_raster(self, api, board_a, kasse):
        kasse.fiscal_start_month = 7
        kasse.save()
        data = get(
            api(board_a),
            f"/api/orgs/{kasse.pk}/finance/statistics/",
            von="2024-01",
            bis="2025-06",
            raster="jahr",
        )
        assert [b["label"] for b in data["buckets"]] == ["2023/24", "2024/25"]
        assert data["von"] == "2023-07-01"

    def test_nur_mit_kassenrecht(self, api, verein):
        user = make_user("mitglieder@example.org")
        give_role(user, verein["club"], ["members.view"], name="Mitglieder")
        resp = api(user).get(f"/api/orgs/{verein['club'].pk}/finance/statistics/")
        assert resp.status_code == 403
