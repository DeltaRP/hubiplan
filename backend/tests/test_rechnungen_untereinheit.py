"""Ein Einheitentyp: Rechnungen gehen an ein Mitglied oder an eine Untereinheit."""

import pytest

from billing.models import Invoice
from organizations.models import Department

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
LINES = [{"text": "Umlage", "amount": "10.00"}]


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def fed(orgs):
    fed = orgs["federation"]
    fed.enabled_modules = ["finance", "members", "billing"]
    fed.save()
    return fed


@pytest.fixture
def fc(api, fed):
    user = make_user("kasse@bund.example.org")
    give_role(user, fed)
    return api(user)


@pytest.fixture
def club(orgs):
    club = orgs["c"]
    club.enabled_modules = ["finance", "members", "billing"]
    club.save()
    return club


@pytest.fixture
def cc(api, board_c):
    return api(board_c)


def post(c, org, **data):
    return c.post(
        f"/api/orgs/{org.pk}/billing/invoices/", {**data, "lines": LINES}, content_type=JSON
    )


class TestOberste:
    def test_untereinheiten_zur_auswahl(self, fc, fed, orgs):
        data = fc.get(f"/api/orgs/{fed.pk}/billing/settings/").json()
        assert {u["id"] for u in data["units"]} == {orgs["a"].pk, orgs["b"].pk}
        assert data["keeps_members"] is False

    def test_rechnung_an_untereinheit(self, fc, fed, orgs):
        resp = post(fc, fed, recipient_kind="unit", unit=orgs["b"].pk)
        assert resp.status_code == 201, resp.json()
        inv = Invoice.objects.get(pk=resp.json()["id"])
        assert (inv.recipient_kind, inv.club_id) == ("club", orgs["b"].pk)

    def test_fremde_einheit_nicht(self, fc, fed, orgs):
        resp = post(fc, fed, recipient_kind="unit", unit=orgs["c"].pk)
        assert resp.status_code == 400
        assert "unit" in resp.json()

    def test_mitglied_nur_mit_eigenen_mitgliedern(self, fc, fed):
        fed.direct_members = True
        fed.save()
        person = make_member(fed, "Dora", "Direkt")
        fed.direct_members = False
        fed.save()
        resp = post(fc, fed, recipient_kind="member", membership=person.pk)
        assert resp.status_code == 400
        fed.direct_members = True
        fed.save()
        assert fc.get(f"/api/orgs/{fed.pk}/billing/settings/").json()["keeps_members"] is True
        resp = post(fc, fed, recipient_kind="member", membership=person.pk)
        assert resp.status_code == 201, resp.json()
        assert resp.json()["recipient_name"] == "Dora Direkt"


class TestMitMitgliedern:
    def test_untereinheiten_mit_pfad(self, cc, club):
        zug = Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)
        Department.objects.create(
            organization=club, parent=zug, name="Gruppe 1", founding_year=1990
        )
        Department.objects.create(
            organization=club, name="Alt", founding_year=1950, is_active=False
        )
        data = cc.get(f"/api/orgs/{club.pk}/billing/settings/").json()
        assert [u["name"] for u in data["units"]] == ["Jägerzug", "Jägerzug › Gruppe 1"]
        assert data["keeps_members"] is True

    def test_rechnung_an_untereinheit(self, cc, club):
        zug = Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)
        resp = post(cc, club, recipient_kind="unit", unit=zug.pk)
        assert resp.status_code == 201, resp.json()
        inv = Invoice.objects.get(pk=resp.json()["id"])
        assert (inv.recipient_kind, inv.department_id) == ("department", zug.pk)
        # alte Angabe gilt weiter
        resp = post(cc, club, recipient_kind="department", department=zug.pk)
        assert resp.status_code == 201

    def test_untereinheit_einer_anderen_einheit_nicht(self, cc, club, orgs):
        fremd = Department.objects.create(organization=orgs["a"], name="Fremd", founding_year=1950)
        resp = post(cc, club, recipient_kind="unit", unit=fremd.pk)
        assert resp.status_code == 400


class TestBaumImDachverband:
    def test_untereinheiten_der_vereine_nur_namen(self, api, orgs, fc):
        a = orgs["a"]
        zug = Department.objects.create(organization=a, name="Jägerzug", founding_year=1950)
        Department.objects.create(organization=a, parent=zug, name="Gruppe 1", founding_year=1990)
        Department.objects.create(organization=a, name="Alt", founding_year=1950, is_active=False)
        c = fc
        data = {x["name"]: x for x in c.get(f"/api/orgs/{orgs['federation'].pk}/clubs/").json()}
        assert [(u["name"], u["depth"]) for u in data["Verein A"]["units"]] == [
            ("Jägerzug", 0),
            ("Jägerzug › Gruppe 1", 1),
        ]
        assert data["Verein B"]["units"] == []
        # Bezeichnung pflegt die Einheit selbst
        url = f"/api/orgs/{orgs['federation'].pk}/clubs/{a.pk}/"
        c.patch(url, {"department_label_plural": "Rotten"}, content_type="application/json")
        a.refresh_from_db()
        assert a.department_label_plural != "Rotten"
