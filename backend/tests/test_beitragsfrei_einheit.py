"""Beitragsfreie Untereinheit: ihre Mitglieder (auch darunter) zahlen keinen Vereinsbeitrag."""

import datetime
from decimal import Decimal

import pytest

from billing import services as billing
from core.tenancy import tenant_context
from members.models import DepartmentMembership, MemberType
from organizations.models import Department

from .factories import make_member

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def club(orgs):
    a = orgs["a"]
    a.enabled_modules = ["finance", "members", "billing"]
    a.save()
    with tenant_context(a.pk):
        from billing.models import FeeRate

        aktiv, _ = MemberType.objects.get_or_create(
            organization=a, name="aktiv", defaults={"active": True}
        )
        FeeRate.objects.create(organization=a, member_type=aktiv, amount=Decimal("60"))
    return a


@pytest.fixture
def units(club):
    with tenant_context(club.pk):
        jugend = Department.objects.create(organization=club, name="Jugendzug")
        rotte = Department.objects.create(organization=club, parent=jugend, name="Rotte 1")
        jaeger = Department.objects.create(organization=club, name="Jägerzug")
    return {"jugend": jugend, "rotte": rotte, "jaeger": jaeger}


def plan(club):
    with tenant_context(club.pk):
        return billing.plan_run(club, billing.period(club, 2025, "yearly", 1))


def test_schalter_ueber_die_maske(api, board_a, club, units):
    c = api(board_a)
    url = f"/api/orgs/{club.pk}/departments/{units['jugend'].pk}/"
    resp = c.patch(url, {"fee_exempt": True}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["fee_exempt"] is True
    units["jugend"].refresh_from_db()
    assert units["jugend"].fee_exempt


def test_mitglieder_beitragsfrei_auch_darunter(club, units):
    units["jugend"].fee_exempt = True
    units["jugend"].save()
    j = make_member(club, "Jan", "Jung", departments=[units["jugend"]])
    r = make_member(club, "Rita", "Rotte", departments=[units["rotte"]])
    z = make_member(club, "Jakob", "Jäger", departments=[units["jaeger"]])
    o = make_member(club, "Olga", "Ohne")
    p = plan(club)
    skipped = {s["membership"]: s["reason"] for s in p.skipped}
    assert skipped[j.pk] == "beitragsfrei (Jugendzug)"
    assert skipped[r.pk] == "beitragsfrei (Jugendzug)"
    billed = {i.membership.pk: i.amount for i in p.member_items}
    for items in p.department_items.values():
        billed.update({i.membership.pk: i.amount for i in items})
    assert billed == {z.pk: Decimal("60.00"), o.pk: Decimal("60.00")}


def test_ohne_schalter_normaler_beitrag(club, units):
    j = make_member(club, "Jan", "Jung", departments=[units["jugend"]])
    p = plan(club)
    assert not p.skipped
    assert [i.amount for i in p.department_items[units["jugend"].pk]] == [Decimal("60.00")]
    assert j.pk == p.department_items[units["jugend"].pk][0].membership.pk


def test_zugehoerigkeit_zum_stichtag(club, units):
    units["jugend"].fee_exempt = True
    units["jugend"].save()
    m = make_member(club, "Jan", "Jung", departments=[units["jugend"]])
    with tenant_context(club.pk):
        DepartmentMembership.objects.filter(membership=m).update(
            valid_until=datetime.date(2024, 12, 31)
        )
    p = plan(club)
    assert not p.skipped
    assert [i.membership.pk for i in p.member_items] == [m.pk]
