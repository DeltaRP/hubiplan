"""Untereinheiten: selbst verwaltet oder von der Einheit darüber verwaltet."""

from __future__ import annotations

import datetime

import pytest

from core.tenancy import tenant_context
from members.models import DepartmentRoleHolder
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess
from portal.services import department_contexts

from .factories import make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.department_access_enabled = True
    club.save()
    return club


def leiter(club, unit):
    """Mitglied mit Rolle „Leitung“ (alle Rechte) in der Untereinheit und Zugang."""
    m = make_member(club, "Erika", "Muster", departments=[unit])
    user = make_user("leitung@example.org")
    with tenant_context(club.pk):
        role = DepartmentRole.objects.create(
            department=unit, name="Leitung", permissions=["dept.members.view"]
        )
        DepartmentRoleHolder.objects.create(
            role=role, membership=m, valid_from=datetime.date(2020, 1, 1)
        )
        PortalAccess.objects.create(organization=club, membership=m, user=user)
    return user


def test_neue_untereinheit_wird_von_oben_verwaltet(club):
    with tenant_context(club.pk):
        zug = Department.objects.create(organization=club, name="Jäger", founding_year=1950)
    assert zug.self_managed is False


def test_von_oben_verwaltet_gibt_keine_rechte(club):
    with tenant_context(club.pk):
        zug = Department.objects.create(organization=club, name="Jäger", founding_year=1950)
    user = leiter(club, zug)
    assert department_contexts(user) == {}

    zug.self_managed = True
    zug.save()
    assert set(department_contexts(user)) == {zug.pk}


def test_rechte_von_oben_gelten_weiter_fuer_gruppen(club):
    """Eine von oben verwaltete Gruppe: die Leitung des Zugs darüber verwaltet sie mit."""
    with tenant_context(club.pk):
        zug = Department.objects.create(
            organization=club, name="Jäger", founding_year=1950, self_managed=True
        )
        gruppe = Department.objects.create(
            organization=club, parent=zug, name="Gruppe 1", founding_year=1990
        )
    user = leiter(club, zug)
    assert set(department_contexts(user)) == {zug.pk, gruppe.pk}


def test_schalter_ueber_die_schnittstelle(api, club, board_a):
    with tenant_context(club.pk):
        zug = Department.objects.create(organization=club, name="Jäger", founding_year=1950)
    c = api(board_a)
    url = f"/api/orgs/{club.pk}/departments/{zug.pk}/"
    assert c.get(url).json()["self_managed"] is False
    resp = c.patch(url, {"self_managed": True}, content_type=JSON)
    assert resp.status_code == 200, resp.content
    assert resp.json()["self_managed"] is True

    # Ein eigener Arbeitsbereich braucht Zugänge: Selbstverwaltung bleibt an
    assert c.patch(url, {"own_workspace": True}, content_type=JSON).status_code == 200
    resp = c.patch(url, {"self_managed": False}, content_type=JSON)
    assert resp.status_code == 400
    assert "self_managed" in resp.json()


def test_arbeitsbereich_schaltet_selbstverwaltung_ein(club):
    with tenant_context(club.pk):
        zug = Department.objects.create(
            organization=club, name="Jäger", founding_year=1950, own_workspace=True
        )
    assert zug.self_managed is True
