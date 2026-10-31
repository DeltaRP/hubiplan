"""Eine Rollenart: Rollen von Untereinheiten stehen in derselben Tabelle wie alle Rollen."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from access.models import Role, RoleAssignment
from core.tenancy import rls_bypass, tenant_context
from members.models import DepartmentRoleHolder
from organizations.models import Department, DepartmentRole

from .factories import make_member

JSON = "application/json"


@pytest.fixture
def zug(orgs):
    with tenant_context(orgs["a"].pk):
        return Department.objects.create(organization=orgs["a"], name="Jäger", founding_year=1950)


@pytest.fixture
def mitglied(orgs, zug):
    return make_member(orgs["a"], "Erika", "Muster", departments=[zug])


class TestEineTabelle:
    def test_rollen_der_untereinheit_stehen_bei_den_rollen(self, orgs, zug, board_a):
        with tenant_context(orgs["a"].pk):
            role = DepartmentRole.objects.create(department=zug, name="Zugführer")
            assert Role.all_objects.filter(pk=role.pk, department=zug).exists()
            # Die Zugänge der Einheit sehen nur ihre eigenen Rollen …
            assert list(Role.objects.filter(organization=orgs["a"]).values_list("name", flat=True))
            assert not Role.objects.filter(pk=role.pk).exists()
            # … die Untereinheit nur ihre
            assert list(zug.unit_roles.values_list("name", flat=True)) == ["Zugführer"]
            assert role.organization_id == orgs["a"].pk
            assert role.is_board is False

    def test_gleicher_name_in_einheit_und_untereinheit(self, orgs, zug, board_a):
        with tenant_context(orgs["a"].pk):
            DepartmentRole.objects.create(department=zug, name="Vorstand")
            assert Role.objects.filter(organization=orgs["a"], name="Vorstand").exists()
            assert zug.unit_roles.filter(name="Vorstand").exists()

    def test_inhaber_stehen_bei_den_rollenzuordnungen(self, orgs, zug, mitglied):
        with tenant_context(orgs["a"].pk):
            role = DepartmentRole.objects.create(department=zug, name="Zugführer")
            holder = DepartmentRoleHolder.objects.create(
                role=role, membership=mitglied, valid_from=datetime.date(2020, 1, 1)
            )
            assert holder.organization_id == orgs["a"].pk
            assert RoleAssignment.all_objects.filter(pk=holder.pk).exists()
            assert not RoleAssignment.objects.filter(pk=holder.pk).exists()
            assert list(mitglied.department_roles.all()) == [holder]
            assert list(role.holders.all()) == [holder]

    def test_untereinheit_mit_inhabern_nicht_loeschbar(self, api, orgs, zug, mitglied, board_a):
        with tenant_context(orgs["a"].pk):
            role = DepartmentRole.objects.create(department=zug, name="Zugführer")
            DepartmentRoleHolder.objects.create(
                role=role, membership=mitglied, valid_from=datetime.date(2020, 1, 1)
            )
            mitglied.department_memberships.all().delete()
        resp = api(board_a).delete(f"/api/orgs/{orgs['a'].pk}/departments/{zug.pk}/")
        assert resp.status_code == 400
        with rls_bypass():
            assert Role.all_objects.filter(pk=role.pk).exists()

    def test_rolle_der_untereinheit_rueckgaengig(self, api, orgs, zug, board_a):
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/department-roles/",
            {"department": zug.pk, "name": "Kassierer"},
            content_type=JSON,
        )
        assert resp.status_code == 201
        undone = c.post(
            f"/api/orgs/{orgs['a'].pk}/changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON
        )
        assert undone.status_code == 200, undone.json()
        with rls_bypass():
            assert not Role.all_objects.filter(department=zug).exists()

    def test_inhaber_eintragen_rueckgaengig(self, api, orgs, zug, mitglied, board_a):
        with tenant_context(orgs["a"].pk):
            role = DepartmentRole.objects.create(department=zug, name="Zugführer")
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/members/{mitglied.pk}/department-roles/",
            {"role": role.pk, "valid_from": "2021-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        undone = c.post(
            f"/api/orgs/{orgs['a'].pk}/changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON
        )
        assert undone.status_code == 200, undone.json()
        with rls_bypass():
            assert not RoleAssignment.all_objects.filter(membership=mitglied).exists()

    def test_zugang_der_einheit_bleibt_nicht_rueckgaengig(self, api, orgs, board_a):
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/roles/",
            {"name": "Kassenprüfer", "permissions": []},
            content_type=JSON,
        )
        assert resp.status_code == 201
        # Zugänge lassen sich nicht zurücknehmen: kein Änderungspaket
        assert not resp.has_header("X-Change-Set")


OLD = [
    ("access", "0008_webseite"),
    ("members", "0012_geschlecht"),
    ("organizations", "0026_termine_weitergabe"),
    ("circulars", "0002_empfaengerkreis_abteilungen"),
    ("changes", "0004_anfrageschluessel_pruefsumme"),
]


@pytest.mark.langsam
@pytest.mark.django_db(transaction=True)
def test_umzug_der_alten_rollen():
    """Die Migration kopiert Rollen, Inhaber und Verweise in die gemeinsamen Tabellen."""
    executor = MigrationExecutor(connection)
    executor.migrate(OLD)
    try:
        ids = _alte_daten(executor.loader.project_state(OLD).apps)
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
    _pruefen(**ids)


def _alte_daten(apps) -> dict:
    Organization = apps.get_model("organizations", "Organization")
    OldRole = apps.get_model("organizations", "DepartmentRole")
    OldHolder = apps.get_model("members", "DepartmentRoleHolder")
    OrgRole = apps.get_model("access", "Role")
    Person = apps.get_model("members", "Person")
    Membership = apps.get_model("members", "Membership")
    Circular = apps.get_model("circulars", "Circular")
    ChangeSet = apps.get_model("changes", "ChangeSet")
    ChangeRecord = apps.get_model("changes", "ChangeRecord")

    with rls_bypass():
        platform = Organization.objects.filter(type="platform").first() or (
            Organization.objects.create(name="Plattform", type="platform")
        )
        club = Organization.objects.create(name="Verein", type="club", parent=platform)
        unit = Organization.objects.create(
            name="Zug", type="unit", parent=club, organization=club, founding_year=1950
        )
        # Rolle der Einheit mit gleichem Namen: darf es weiter geben
        OrgRole.objects.create(organization=club, name="Zugführer", permissions=[])
        person = Person.objects.create(
            first_name="Erika",
            last_name="Muster",
            birth_date=datetime.date(1980, 5, 17),
            scope=club,
        )
        membership = Membership.objects.create(organization=club, scope=club, person=person)
        old_role = OldRole.objects.create(
            organization=club,
            department_id=unit.pk,
            name="Zugführer",
            permissions=["dept.members.view"],
            position=3,
            on_website=True,
        )
        gone = OldRole.objects.create(organization=club, department_id=unit.pk, name="Weg")
        gone_pk = gone.pk
        gone.delete()
        old_holder = OldHolder.objects.create(
            organization=club,
            membership=membership,
            role=old_role,
            valid_from=datetime.date(2020, 1, 1),
        )
        circular = Circular.objects.create(
            organization=club, subject="Test", body="", filters={"roles": [old_role.pk]}
        )
        cs = ChangeSet.objects.create(organization=club)
        ChangeRecord.objects.create(
            organization=club,
            change_set=cs,
            seq=1,
            model="members.departmentroleholder",
            object_id=str(old_holder.pk),
            operation="create",
            after={"id": old_holder.pk, "role_id": old_role.pk},
        )
        gone_cs = ChangeSet.objects.create(organization=club)
        ChangeRecord.objects.create(
            organization=club,
            change_set=gone_cs,
            seq=1,
            model="organizations.departmentrole",
            object_id=str(gone_pk),
            operation="delete",
            before={"id": gone_pk, "name": "Weg"},
        )
    return {
        "club": club.pk,
        "unit": unit.pk,
        "membership": membership.pk,
        "circular": circular.pk,
        "cs": cs.pk,
        "gone_cs": gone_cs.pk,
    }


def _pruefen(club, unit, membership, circular, cs, gone_cs):
    with rls_bypass():
        role = Role.all_objects.get(department_id=unit)
        assert (role.name, role.position, role.on_website, role.organization_id) == (
            "Zugführer",
            3,
            True,
            club,
        )
        assert role.permissions == ["dept.members.view"]
        holder = RoleAssignment.all_objects.get(membership_id=membership)
        assert holder.role_id == role.pk
        assert holder.valid_from == datetime.date(2020, 1, 1)
        from changes.models import ChangeRecord as NewRecord
        from changes.models import ChangeSet as NewSet
        from circulars.models import Circular as NewCircular

        assert NewCircular.objects.get(pk=circular).filters["roles"] == [role.pk]
        rec = NewRecord.objects.get(change_set_id=cs)
        assert (rec.model, rec.object_id) == ("access.roleassignment", str(holder.pk))
        assert rec.after == {"id": holder.pk, "role_id": role.pk}
        assert NewSet.objects.get(pk=gone_cs).blocked_reason
        assert NewSet.objects.get(pk=cs).blocked_reason == ""
    from django.apps import apps as live

    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
    known = {m._meta.db_table for m in live.get_models(include_auto_created=True)}
    assert tables - known <= {"django_migrations"}, tables - known
