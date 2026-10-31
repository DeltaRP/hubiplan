"""Finanzamt-Prüfung B7: Eine Einheit mit Finanzdaten lässt sich nicht löschen (erfundene Daten)."""

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from core.rls import APP_ROLE
from core.tenancy import set_rls, tenant_context
from finance.models import Account, Booking, Category
from organizations.models import Department

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS nur mit PostgreSQL"),
]
JSON = "application/json"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.enabled_modules = ["finance", "members", "billing"]
    club.save()
    return club


@pytest.fixture
def c(api, board_a):
    return api(board_a)


@pytest.fixture
def unit(c, club):
    unit = Department.objects.create(organization=club, name="Spielmannszug", founding_year=1980)
    resp = c.patch(
        f"/api/orgs/{club.pk}/departments/{unit.pk}/", {"own_workspace": True}, content_type=JSON
    )
    assert resp.status_code == 200, resp.json()
    return unit


@pytest.fixture
def rls():
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    yield
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
    set_rls(None, None, False)


def _booking(org, **extra):
    with tenant_context(org.pk):
        account = Account.objects.create(
            organization=org, name="Kasse", kind="cash", opening_date=datetime.date(2025, 1, 1)
        )
        cat = Category.objects.create(organization=org, name="Testeinnahmen", kind="income")
        return Booking.objects.create(
            organization=org,
            year=2025,
            number=1,
            date=datetime.date(2025, 3, 1),
            kind="income",
            amount=Decimal("20.00"),
            account=account,
            category=cat,
            text="Spende",
            **extra,
        )


def test_leere_einheit_laesst_sich_loeschen(c, club, unit, rls):
    assert c.delete(f"/api/orgs/{club.pk}/departments/{unit.pk}/").status_code == 204


def test_einheit_mit_eigenen_buchungen_bleibt(c, club, unit):
    booking = _booking(unit)
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        resp = c.delete(f"/api/orgs/{club.pk}/departments/{unit.pk}/")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)
    assert resp.status_code == 400
    assert "Buchungen" in str(resp.json()) and "inaktiv" in str(resp.json())
    assert Booking.objects.filter(pk=booking.pk).exists()
    assert Department.objects.filter(pk=unit.pk).exists()


def test_einheit_mit_zugeordneten_buchungen_des_vereins_bleibt(c, club, rls):
    zug = Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)
    _booking(club, department=zug)
    resp = c.delete(f"/api/orgs/{club.pk}/departments/{zug.pk}/")
    assert resp.status_code == 400
    assert "zugeordnete Buchungen" in str(resp.json())
