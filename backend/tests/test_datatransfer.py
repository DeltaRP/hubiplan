"""Vollständiger JSON-Export und Import auf der höheren Ebene."""

import datetime
import io
import json
import zipfile
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from access.models import Role, RoleAssignment
from audit.models import AuditEntry
from core.tenancy import rls_bypass, tenant_context
from customfields.models import FieldDefinition, FieldValue
from finance.models import Account, Booking, Category, Project, ProjectSeries
from members.models import DepartmentMembership, FederationMember, Membership, Person
from organizations.models import Department, DepartmentRole, Organization

from .factories import give_role, make_member, make_org, make_user
from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _eager(settings, tmp_path):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture(autouse=True)
def _on_commit_now(monkeypatch):
    # Im Test gibt es kein echtes Commit: Hintergrund-Jobs sofort ausführen
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, *a, **k: func())


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b", "c")}


@pytest.fixture
def board_fed(orgs):
    user = make_user("verband@example.org")
    give_role(user, orgs["federation"])
    return user


@pytest.fixture
def platform_admin():
    user = make_user("plattform@example.org")
    give_role(user, Organization.platform())
    return user


@pytest.fixture
def club_c(api, orgs, types, board_c):
    """Verein C (ohne Dachverband) mit Abteilung, Zusatzfeld, Mitgliedern und Kasse."""
    club = orgs["c"]
    c = api(board_c)
    with tenant_context(club.pk):
        dept = Department.objects.create(
            self_managed=True, organization=club, name="1. Zug", founding_year=1950
        )
        role = DepartmentRole.objects.create(
            organization=club, department=dept, name="Oberleutnant", permissions=[]
        )
        field = FieldDefinition.objects.create(organization=club, label="Schuhgröße", key="schuh")
    erika = admit(c, club, types["c"]["aktiv"], department_ids=[dept.pk]).json()
    admit(
        c,
        club,
        types["c"]["passiv"],
        last_name="Berg",
        first_name="Bernd",
        birth_date="1970-01-01",
        email="bernd@example.org",
    )
    with tenant_context(club.pk):
        membership = Membership.objects.get(pk=erika["id"])
        FieldValue.objects.create(
            organization=club, definition=field, person=membership.person, value="42"
        )
        from members.models import DepartmentRoleHolder

        DepartmentRoleHolder.objects.create(
            organization=club,
            membership=membership,
            role=role,
            valid_from=datetime.date(2020, 1, 1),
        )
        account = Account.objects.create(
            organization=club, name="Girokonto", opening_date=datetime.date(2024, 1, 1)
        )
        category = Category.objects.create(organization=club, name="Beiträge", kind="income")
        series = ProjectSeries.objects.create(organization=club, name="Schützenfest")
        project = Project.objects.create(
            organization=club,
            series=series,
            department=dept,
            name="Schützenfest 2024",
            starts_on=datetime.date(2024, 8, 24),
        )
        Booking.objects.create(
            project=project,
            organization=club,
            year=2024,
            number=1,
            date=datetime.date(2024, 2, 1),
            kind="income",
            amount=Decimal("30.00"),
            account=account,
            category=category,
            text="Beitrag Erika",
            membership=membership,
        )
    return {"club": club, "dept": dept, "erika": erika}


def export(client, base, **data):
    resp = client.post(f"{base}/datatransfer/exports/", data, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    job = resp.json()
    detail = client.get(f"{base}/datatransfer/exports/{job['id']}/").json()
    assert detail["status"] == "done", detail
    resp = client.get(f"{base}/datatransfer/exports/{job['id']}/download/")
    assert resp.status_code == 200
    content = b"".join(resp.streaming_content)
    return content, detail


def as_doc(content: bytes) -> dict:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return json.loads(archive.read("export.json"))
    return json.loads(content)


def upload(client, base, content: bytes, filename="export.json", **options):
    resp = client.post(
        f"{base}/datatransfer/imports/",
        {"file": SimpleUploadedFile(filename, content), **options},
    )
    assert resp.status_code == 201, resp.json()
    return client.get(f"{base}/datatransfer/imports/{resp.json()['id']}/").json()


class TestExport:
    def test_verein_vollstaendig(self, api, club_c, board_c):
        base = f"/api/orgs/{club_c['club'].pk}"
        content, job = export(api(board_c), base)
        doc = as_doc(content)
        assert doc["format"] == "hubiplan-export"
        assert doc["version"] == 1
        org = doc["organization"]
        assert org["name"] == "Verein C ohne Verband"
        assert {t["name"] for t in org["member_types"]} == {"aktiv", "passiv", "Fördermitglied"}
        assert org["departments"][0]["roles"][0]["name"] == "Oberleutnant"
        assert len(org["memberships"]) == 2
        erika = next(m for m in org["memberships"] if m["id"] == club_c["erika"]["id"])
        assert erika["contact"]["email"] == "erika@example.org"
        assert erika["periods"][0]["entry_date"] == "2015-03-01"
        assert erika["department_roles"]
        assert org["tables"]["finance.booking"][0]["amount"] == "30.00"
        assert [r["name"] for r in org["roles"]] == ["Vorstand"]
        assert org["role_assignments"][0]["email"] == "vorstand-c@example.org"
        person = next(p for p in doc["persons"] if p["id"] == erika["person"])
        assert person["field_values"] == [{"field": org["fields"][0]["id"], "value": "42"}]
        assert job["summary"]["memberships"] == 2
        # protokolliert
        with tenant_context(club_c["club"].pk):
            assert AuditEntry.objects.filter(
                organization=club_c["club"], object_type="Datenübernahme"
            ).exists()

    def test_ohne_recht_verboten(self, api, club_c):
        user = make_user("leser@example.org")
        give_role(user, club_c["club"], permissions=["members.view"], name="Leser")
        resp = api(user).post(
            f"/api/orgs/{club_c['club'].pk}/datatransfer/exports/", {}, content_type=JSON
        )
        assert resp.status_code == 403

    def test_dachverband_sieht_mitglieder_nur_mit_freigabe(
        self, api, orgs, types, board_a, board_fed
    ):
        admit(api(board_a), orgs["a"], types["a"]["aktiv"])
        base = f"/api/orgs/{orgs['federation'].pk}"
        doc = as_doc(export(api(board_fed), base)[0])
        clubs = doc["organization"]["clubs"]
        assert {c["name"] for c in clubs} == {"Verein A", "Verein B"}
        assert all(c["memberships"] == [] for c in clubs)
        assert doc["persons"] == []
        assert "tables" not in clubs[0]

        orgs["federation"].federation_member_access = "read"
        orgs["federation"].save()
        doc = as_doc(export(api(board_fed), base)[0])
        club_a = next(c for c in doc["organization"]["clubs"] if c["name"] == "Verein A")
        assert len(club_a["memberships"]) == 1
        assert doc["persons"][0]["federation"]["member_number"] == 1

    def test_abteilung_durch_verein(self, api, club_c, board_c):
        base = f"/api/orgs/{club_c['club'].pk}"
        doc = as_doc(export(api(board_c), base, kind="department", department=club_c["dept"].pk)[0])
        assert doc["kind"] == "department"
        assert doc["department"]["name"] == "1. Zug"
        assert len(doc["memberships"]) == 1
        assert [t["name"] for t in doc["member_types"]] == ["aktiv"]

    def test_mit_dateien_als_zip(self, api, club_c, board_c):
        from django.core.files.base import ContentFile

        club = club_c["club"]
        club.logo.save("wappen.png", ContentFile(b"\x89PNG-test"), save=True)
        content, job = export(api(board_c), f"/api/orgs/{club.pk}", with_files=True)
        assert job["file_name"].endswith(".zip")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            doc = json.loads(archive.read("export.json"))
            assert archive.read(doc["organization"]["logo"]) == b"\x89PNG-test"


class TestImportDachverband:
    def test_verein_importieren_mit_dublette(self, api, orgs, types, club_c, board_c, board_a):
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        # Erika gibt es im Dachverband schon (Verein A, passiv)
        admit(api(board_a), orgs["a"], types["a"]["passiv"])
        board_fed = make_user("verband@example.org")
        give_role(board_fed, orgs["federation"])
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(c, base, content, name="Neuer Verein")
        assert job["status"] == "checked", job
        preview = job["preview"]
        assert preview["error_count"] == 0, preview["errors"]
        assert preview["type"] == "club"
        assert preview["summary"]["memberships"] == 2
        assert len(preview["duplicates"]) == 1
        dup = preview["duplicates"][0]
        assert dup["name"] == "Muster, Erika"
        assert dup["candidates"][0]["clubs"][0]["name"] == "Verein A"
        existing_id = dup["candidates"][0]["id"]
        assert dup["choice"] == str(existing_id)

        resp = c.post(f"{base}/datatransfer/imports/{job['id']}/run/")
        assert resp.status_code == 200, resp.json()
        job = c.get(f"{base}/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        new_club = Organization.objects.get(pk=job["result_organization"]["id"])
        assert new_club.parent == orgs["federation"]
        assert new_club.name == "Neuer Verein"
        with rls_bypass():
            memberships = Membership.objects.filter(organization=new_club)
            assert memberships.count() == 2
            assert memberships.filter(person_id=existing_id).exists()
            assert Person.objects.filter(scope=orgs["federation"], last_name="Muster").count() == 1
            bernd = Person.objects.get(scope=orgs["federation"], last_name="Berg")
            # Neue Person im Dachverband bekommt eine Verbandsnummer
            assert FederationMember.objects.filter(person=bernd).exists()
            assert Booking.objects.filter(organization=new_club).count() == 1
            booking = Booking.objects.get(organization=new_club)
            assert booking.membership.organization == new_club
            # Veranstaltung mit Reihe und Abteilung kommt mit
            assert booking.project.organization == new_club
            assert booking.project.series.name == "Schützenfest"
            assert booking.project.department.organization == new_club
            dept = Department.objects.get(organization=new_club)
            assert DepartmentMembership.objects.filter(department=dept).count() == 1
            assert FieldValue.objects.filter(organization=new_club).count() == 1
            # Vorstand wurde übernommen, weil das Konto existiert
            assert RoleAssignment.objects.filter(
                organization=new_club, user__email="vorstand-c@example.org"
            ).exists()

    def test_fruehere_amtsinhaber_kommen_mit(self, api, orgs, club_c, board_c):
        """Freie Einträge früherer Inhaber (Mitglieder › Ämter, Ralf 2026-10-31)."""
        club = club_c["club"]
        with tenant_context(club.pk):
            chair = Role.objects.get(organization=club, name="Vorstand")
            unit_role = DepartmentRole.objects.get(department=club_c["dept"])
            unit_role.in_chronicle = True
            unit_role.save()
            for role, name in ((chair, "Wilhelm Vorzeit"), (unit_role, "Karl Alt")):
                RoleAssignment.all_objects.create(
                    organization=club,
                    role=role,
                    name=name,
                    valid_from=datetime.date(1955, 1, 1),
                    valid_until=datetime.date(1972, 1, 1),
                )
        content, _ = export(api(board_c), f"/api/orgs/{club.pk}")
        board_fed = make_user("verband@example.org")
        give_role(board_fed, orgs["federation"])
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(c, base, content, name="Neuer Verein")
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        assert c.post(f"{base}/datatransfer/imports/{job['id']}/run/").status_code == 200
        job = c.get(f"{base}/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new_club = Organization.objects.get(pk=job["result_organization"]["id"])
            entries = RoleAssignment.all_objects.filter(organization=new_club).exclude(name="")
            assert sorted((e.name, e.role.name, e.valid_until.year) for e in entries) == [
                ("Karl Alt", "Oberleutnant", 1972),
                ("Wilhelm Vorzeit", "Vorstand", 1972),
            ]
            assert Role.all_objects.get(organization=new_club, name="Oberleutnant").in_chronicle

    def test_aktiv_in_anderem_verein_ist_fehler(self, api, orgs, types, club_c, board_c, board_a):
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        admit(api(board_a), orgs["a"], types["a"]["aktiv"])
        board_fed = make_user("verband@example.org")
        give_role(board_fed, orgs["federation"])
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(c, base, content)
        assert job["preview"].get("error_count") == 1, job["error"]
        assert "bereits aktives Mitglied" in job["preview"]["errors"][0]
        assert c.post(f"{base}/datatransfer/imports/{job['id']}/run/").status_code == 400
        # Als neue Person anlegen löst den Konflikt
        dup = job["preview"]["duplicates"][0]
        resp = c.patch(
            f"{base}/datatransfer/imports/{job['id']}/",
            {"persons": {str(dup["person"]): "new"}},
            content_type=JSON,
        )
        assert resp.status_code == 200
        job = c.get(f"{base}/datatransfer/imports/{job['id']}/").json()
        assert job["preview"]["error_count"] == 0

    def test_falsche_datei(self, api, orgs, board_fed, club_c, board_c):
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(api(board_fed), base, b'{"hallo": 1}')
        assert job["status"] == "failed"
        assert "keine Exportdatei" in job["error"]
        # Abteilungsdatei passt nicht in den Dachverband
        dept_file, _ = export(
            api(board_c),
            f"/api/orgs/{club_c['club'].pk}",
            kind="department",
            department=club_c["dept"].pk,
        )
        job = upload(api(board_fed), base, dept_file)
        assert job["status"] == "failed"
        assert "Untereinheit" in job["error"]

    def test_verein_ohne_recht(self, api, orgs, club_c, board_c):
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        user = make_user("leser@example.org")
        give_role(user, orgs["federation"], permissions=["members.view"], name="Leser")
        resp = api(user).post(
            f"/api/orgs/{orgs['federation'].pk}/datatransfer/imports/",
            {"file": SimpleUploadedFile("x.json", content)},
        )
        assert resp.status_code == 403

    def test_verein_von_hand_anlegen(self, api, orgs, board_fed):
        resp = api(board_fed).post(
            f"/api/orgs/{orgs['federation'].pk}/federation/clubs/new/",
            {
                "name": "Neuverein",
                "founding_year": 2001,
                "street": "Weg 1",
                "postal_code": "41468",
                "city": "Neuss",
                "board_email": "neu@example.org",
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        club = Organization.objects.get(pk=resp.json()["id"])
        assert club.parent == orgs["federation"]
        assert resp.json()["invited"] == 1
        with rls_bypass():
            assert RoleAssignment.objects.get(organization=club).user.email == "neu@example.org"


class TestImportPlattform:
    def test_dachverband_mit_vereinen(self, api, orgs, types, board_a, board_b, platform_admin):
        a = admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()
        c = api(platform_admin)
        resp = c.post(
            "/api/platform/datatransfer/exports/",
            {"organization": orgs["federation"].pk},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        pk = resp.json()["id"]
        content = b"".join(
            c.get(f"/api/platform/datatransfer/exports/{pk}/download/").streaming_content
        )
        doc = json.loads(content)
        # Die Plattform bekommt alles, auch ohne Freigabe des Dachverbands
        club_a = next(x for x in doc["organization"]["clubs"] if x["name"] == "Verein A")
        assert club_a["memberships"][0]["id"] == a["id"]

        job = upload(c, "/api/platform", content, name="Kopie Verband", invite=True)
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        assert job["preview"]["duplicates"] == []
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        fed = Organization.objects.get(pk=job["result_organization"]["id"])
        assert fed.type == "federation"
        assert fed.name == "Kopie Verband"
        assert {x.name for x in fed.children.all()} == {"Verein A", "Verein B"}
        with rls_bypass():
            person = Person.objects.get(scope=fed)
            assert person.federation.member_number == 1
            assert Membership.objects.get(person=person).scope == fed

    def test_verein_ohne_dachverband(self, api, club_c, board_c, platform_admin):
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        c = api(platform_admin)
        job = upload(c, "/api/platform", content)
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        club = Organization.objects.get(pk=job["result_organization"]["id"])
        assert club.parent == Organization.platform()
        with rls_bypass():
            assert Person.objects.filter(scope=club).count() == 2
            assert not FederationMember.objects.filter(person__scope=club).exists()

    def test_nur_plattform_admin(self, api, board_c):
        assert api(board_c).get("/api/platform/datatransfer/imports/").status_code == 403


class TestImportAbteilung:
    def test_abteilung_in_anderen_verein(self, api, orgs, types, club_c, board_c, board_a):
        content, _ = export(
            api(board_c),
            f"/api/orgs/{club_c['club'].pk}",
            kind="department",
            department=club_c["dept"].pk,
        )
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        job = upload(c, base, content, name="Jägerzug")
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        assert job["preview"]["summary"]["memberships"] == 1
        c.post(f"{base}/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"{base}/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            dept = Department.objects.get(organization=orgs["a"], name="Jägerzug")
            assert dept.unit_roles.get().name == "Oberleutnant"
            membership = DepartmentMembership.objects.get(department=dept).membership
            assert membership.organization == orgs["a"]
            # Mitgliedsart „aktiv“ gab es im Verein schon
            assert membership.type_assignments.get().member_type == types["a"]["aktiv"]
            assert membership.department_roles.get().role.department == dept

    def test_vorhandenes_mitglied_wird_zugeordnet(self, api, orgs, types, board_a):
        club = orgs["a"]
        with tenant_context(club.pk):
            dept = Department.objects.create(
                self_managed=True, organization=club, name="Altzug", founding_year=1960
            )
        make_member(club, "Erika", "Muster", member_type=types["a"]["passiv"], departments=[dept])
        content, _ = export(
            api(board_a), f"/api/orgs/{club.pk}", kind="department", department=dept.pk
        )
        c = api(board_a)
        base = f"/api/orgs/{club.pk}"
        job = upload(c, base, content)
        # Name gibt es im Verein schon
        assert job["preview"].get("error_count") == 1, job["error"]
        c.patch(f"{base}/datatransfer/imports/{job['id']}/", {"name": "Neuzug"}, content_type=JSON)
        job = c.get(f"{base}/datatransfer/imports/{job['id']}/").json()
        assert job["preview"]["error_count"] == 0
        assert job["preview"]["duplicates"][0]["fixed"] is True
        c.post(f"{base}/datatransfer/imports/{job['id']}/run/")
        with rls_bypass():
            assert Membership.objects.filter(organization=club).count() == 1
            new = Department.objects.get(organization=club, name="Neuzug")
            assert DepartmentMembership.objects.filter(department=new).count() == 1


class TestUntereinheitWirdEigeneEinheit:
    """Verbund Schritt 8b: Plattform liest den Export einer Untereinheit als eigene Einheit."""

    def test_untereinheit_auf_plattform(self, api, club_c, board_c, platform_admin):
        content, _ = export(
            api(board_c),
            f"/api/orgs/{club_c['club'].pk}",
            kind="department",
            department=club_c["dept"].pk,
        )
        doc = as_doc(content)
        assert doc["club"]["city"] == club_c["club"].city
        c = api(platform_admin)
        job = upload(c, "/api/platform", content, name="Jägerzug Grünrock", city="Neustadt")
        preview = job["preview"]
        assert preview["error_count"] == 0, preview["errors"]
        assert preview["kind"] == "unit" and preview["type"] == "club"
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        unit = Organization.objects.get(pk=job["result_organization"]["id"])
        assert unit.type == "club" and unit.parent == Organization.platform()
        assert unit.name == "Jägerzug Grünrock" and unit.founding_year == 1950
        assert unit.city == "Neustadt" and unit.street == club_c["club"].street
        with rls_bypass():
            membership = Membership.objects.get(organization=unit)
            # Kennung beim abgebenden Verein bleibt: darüber läuft später der Abgleich
            assert membership.origin_ref == str(club_c["erika"]["id"])
            assert membership.person.scope == unit
            assert membership.type_assignments.get().member_type.name == "aktiv"
            assert not DepartmentMembership.objects.filter(organization=unit).exists()
            # Amt der Untereinheit wird Amt der Einheit, ohne Konto
            holder = RoleAssignment.objects.get(organization=unit, role__name="Oberleutnant")
            assert holder.user is None and holder.person == membership.person
            # Der Verein bleibt unverändert
            assert Membership.objects.filter(organization=club_c["club"]).count() == 2

    def test_ohne_anschrift_fehler(self, api, orgs, club_c, board_c, platform_admin):
        club = club_c["club"]
        Organization.objects.filter(pk=club.pk).update(street="")
        content, _ = export(
            api(board_c), f"/api/orgs/{club.pk}", kind="department", department=club_c["dept"].pk
        )
        c = api(platform_admin)
        job = upload(c, "/api/platform", content)
        assert job["preview"].get("error_count") == 1, job["error"]
        assert "Anschrift" in job["preview"]["errors"][0]
        c.patch(
            f"/api/platform/datatransfer/imports/{job['id']}/",
            {"street": "Am Markt 1"},
            content_type=JSON,
        )
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["preview"]["error_count"] == 0


def test_abteilungsrolle_exportiert(api, orgs, types, club_c, board_c):
    club = club_c["club"]
    club.department_access_enabled = True
    club.save()
    with tenant_context(club.pk):
        role = DepartmentRole.objects.create(
            organization=club,
            department=club_c["dept"],
            name="Spieß",
            permissions=["dept.members.view", "dept.export"],
        )
        from members.models import DepartmentRoleHolder

        DepartmentRoleHolder.objects.create(
            organization=club,
            membership_id=club_c["erika"]["id"],
            role=role,
            valid_from=datetime.date(2020, 1, 1),
        )
        membership = Membership.objects.get(pk=club_c["erika"]["id"])
    from portal.models import PortalAccess

    user = make_user("spiess@example.org")
    with tenant_context(club.pk):
        PortalAccess.objects.create(organization=club, membership=membership, user=user)
    content, _ = export(api(user), f"/api/depts/{club_c['dept'].pk}")
    assert as_doc(content)["department"]["name"] == "1. Zug"


def test_rechte_migration_fuer_vorstand(orgs):
    # Neue Rechte stehen im Katalog und gehören zur Vorstandsrolle neuer Organisationen
    from access.catalog import codes_for

    assert "data.export" in codes_for("club")
    assert "clubs.manage" in codes_for("federation")
    assert "clubs.manage" not in codes_for("club")
    assert Role  # noqa: B018
    assert make_org


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_export_und_import_unter_rls(api, orgs, club_c, board_c, board_a):
    """Mit aktiver Row-Level Security (Rolle der Anwendung) funktioniert alles."""
    from .test_rls import as_app_role

    board_fed = make_user("verband@example.org")
    give_role(board_fed, orgs["federation"])
    with tenant_context(orgs["a"].pk):
        Department.objects.create(
            self_managed=True, organization=orgs["a"], name="1. Zug", founding_year=1999
        )
    with as_app_role():
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(c, base, content)
        assert job["status"] == "checked", job
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        c.post(f"{base}/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"{base}/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        # Abteilung mit vorhandenem Namen wird unter RLS erkannt
        dept_file, _ = export(
            api(board_c),
            f"/api/orgs/{club_c['club'].pk}",
            kind="department",
            department=club_c["dept"].pk,
        )
        a = api(board_a)
        job = upload(a, f"/api/orgs/{orgs['a'].pk}", dept_file)
        errors = job["preview"]["errors"]
        assert any("gibt es schon „1. Zug“" in e for e in errors), errors
        # Erika ist inzwischen im importierten Verein aktiv: auch das wird erkannt
        assert any("bereits aktives Mitglied" in e for e in errors), errors
    with rls_bypass():
        new_club = Organization.objects.get(parent=orgs["federation"], name="Verein C ohne Verband")
        assert Membership.objects.filter(organization=new_club).count() == 2


def _statute(club, department=None, public=False):
    from django.core.files.base import ContentFile

    from statutes.models import StatutePublication, StatuteVersion

    with tenant_context(club.pk):
        version = StatuteVersion(
            organization=club,
            department=department,
            name="satzung.pdf",
            size=8,
            valid_from=datetime.date(2020, 3, 1),
            note="Fassung 2020",
        )
        version.file.save("satzung.pdf", ContentFile(b"%PDF-1.4"), save=False)
        version.save()
        pub = StatutePublication.objects.create(
            organization=club,
            department=department,
            is_public=public,
            public_key=StatutePublication.new_key(),
        )
    return version, pub


class TestSatzung:
    def test_verein_mit_satzung_ueber_zip(self, api, club_c, board_c, platform_admin):
        from statutes.models import StatutePublication, StatuteVersion

        _, pub = _statute(club_c["club"], public=True)
        _statute(club_c["club"], department=club_c["dept"])
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}", with_files=True)
        doc = as_doc(content)
        assert len(doc["organization"]["tables"]["statutes.statuteversion"]) == 2
        c = api(platform_admin)
        job = upload(c, "/api/platform", content, filename="export.zip")
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        new = Organization.objects.get(pk=job["result_organization"]["id"])
        with rls_bypass():
            versions = StatuteVersion.objects.filter(organization=new)
            assert versions.count() == 2
            own = versions.get(department=None)
            assert own.note == "Fassung 2020"
            assert own.file.read() == b"%PDF-1.4"
            assert versions.get(department__isnull=False).department.organization == new
            new_pub = StatutePublication.objects.get(organization=new, department=None)
            assert new_pub.is_public is True
            # Öffentlicher Schlüssel wird neu vergeben, damit er eindeutig bleibt
            assert new_pub.public_key != pub.public_key

    def test_ohne_dateien_hinweis(self, api, club_c, board_c, platform_admin):
        _statute(club_c["club"])
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        job = upload(api(platform_admin), "/api/platform", content)
        assert any("Satzungsfassungen ohne PDF" in w for w in job["preview"]["warnings"])

    def test_abteilung_mit_satzung(self, api, orgs, club_c, board_c, board_a):
        from statutes.models import StatuteVersion

        _statute(club_c["club"])  # Satzung des Vereins gehört nicht in die Abteilung
        _statute(club_c["club"], department=club_c["dept"])
        content, _ = export(
            api(board_c),
            f"/api/orgs/{club_c['club'].pk}",
            kind="department",
            department=club_c["dept"].pk,
            with_files=True,
        )
        assert len(as_doc(content)["tables"]["statutes.statuteversion"]) == 1
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}"
        job = upload(c, base, content, filename="zug.zip")
        c.post(f"{base}/datatransfer/imports/{job['id']}/run/")
        assert c.get(f"{base}/datatransfer/imports/{job['id']}/").json()["status"] == "done"
        with rls_bypass():
            version = StatuteVersion.objects.get(organization=orgs["a"])
            assert version.department.name == "1. Zug"


class TestKurzname:
    def test_verein_mit_kurznamen(self, api, club_c, board_c, platform_admin):
        club, dept = club_c["club"], club_c["dept"]
        club.short_name = "Verein C"
        club.save()
        with tenant_context(club.pk):
            dept.short_name = "Erster"
            dept.save()
        content, _ = export(api(board_c), f"/api/orgs/{club.pk}")
        doc = as_doc(content)
        assert doc["organization"]["short_name"] == "Verein C"
        assert doc["organization"]["departments"][0]["short_name"] == "Erster"

        c = api(platform_admin)
        job = upload(c, "/api/platform", content)
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new = Organization.objects.get(pk=job["result_organization"]["id"])
            assert new.short_name == "Verein C"
            assert new.departments.get().short_name == "Erster"

    def test_alte_exporte_ohne_kurzname(self, api, club_c, board_c, platform_admin):
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        doc = as_doc(content)
        doc["organization"].pop("short_name")
        for d in doc["organization"]["departments"]:
            d.pop("short_name")
        c = api(platform_admin)
        job = upload(c, "/api/platform", json.dumps(doc).encode())
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new = Organization.objects.get(pk=job["result_organization"]["id"])
            assert new.short_name == ""
            assert new.display_name == new.name


def _documents(club, department=None, name="Protokolle"):
    from django.core.files.base import ContentFile

    from documents.models import Document, DocumentVersion, Folder

    with tenant_context(club.pk):
        folder = Folder.objects.create(
            organization=club,
            department=department,
            name=name,
            visibility="members",
            public_key=Folder.new_key(),
        )
        doc = Document.objects.create(
            organization=club,
            department=department,
            folder=folder,
            title=f"{name}: JHV",
            date=datetime.date(2026, 2, 14),
        )
        for body in (b"%PDF-1.4 alt", b"%PDF-1.4 neu"):
            version = DocumentVersion(
                organization=club,
                department=department,
                document=doc,
                name="jhv.pdf",
                size=len(body),
                content_type="application/pdf",
            )
            version.file.save("jhv.pdf", ContentFile(body), save=False)
            version.save()
    return folder


class TestDokumente:
    def test_verein_mit_ablage_ueber_zip(self, api, club_c, board_c, platform_admin):
        from documents.models import Document, DocumentVersion, Folder

        old = _documents(club_c["club"])
        _documents(club_c["club"], department=club_c["dept"], name="Zug")
        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}", with_files=True)
        tables = as_doc(content)["organization"]["tables"]
        assert len(tables["documents.folder"]) == 2
        assert len(tables["documents.documentversion"]) == 4
        c = api(platform_admin)
        job = upload(c, "/api/platform", content, filename="export.zip")
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new = Organization.objects.get(pk=job["result_organization"]["id"])
            folder = Folder.objects.get(organization=new, department=None)
            assert folder.public_key != old.public_key and folder.visibility == "members"
            doc = Document.objects.get(folder=folder)
            assert sorted(v.file.read() for v in doc.versions.all()) == [
                b"%PDF-1.4 alt",
                b"%PDF-1.4 neu",
            ]
            zug = Folder.objects.get(organization=new, department__isnull=False)
            assert zug.department.organization == new
            assert DocumentVersion.objects.filter(document__folder=zug).count() == 2

    def test_abteilung_nur_eigene_ablage(self, api, club_c, board_c):
        _documents(club_c["club"])
        _documents(club_c["club"], department=club_c["dept"], name="Zug")
        content, _ = export(
            api(board_c),
            f"/api/orgs/{club_c['club'].pk}",
            kind="department",
            department=club_c["dept"].pk,
        )
        tables = as_doc(content)["tables"]
        assert [f["name"] for f in tables["documents.folder"]] == ["Zug"]


def test_untereinheiten_mit_baum(api, orgs, types, club_c, board_c):
    """Gruppen unter einem Zug kommen mit ihrer Stelle im Baum mit."""
    club = club_c["club"]
    with tenant_context(club.pk):
        gruppe = Department.objects.create(
            self_managed=True,
            organization=club,
            parent=club_c["dept"],
            name="Gruppe 1",
            founding_year=1990,
        )
    content, _ = export(api(board_c), f"/api/orgs/{club.pk}")
    units = as_doc(content)["organization"]["departments"]
    assert [(u["name"], u["parent_unit"]) for u in units] == [
        ("1. Zug", None),
        ("Gruppe 1", club_c["dept"].pk),
    ]
    board_fed = make_user("verband@example.org")
    give_role(board_fed, orgs["federation"])
    c = api(board_fed)
    base = f"/api/orgs/{orgs['federation'].pk}"
    job = upload(c, base, content, name="Neuer Verein")
    assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
    assert c.post(f"{base}/datatransfer/imports/{job['id']}/run/").status_code == 200
    new_club = Organization.objects.get(name="Neuer Verein")
    new_gruppe = Department.objects.get(organization=new_club, name="Gruppe 1")
    assert new_gruppe.parent.name == "1. Zug"
    assert new_gruppe.pk != gruppe.pk


class TestWebseite:
    def test_webseite_mit_inhalten_ueber_zip(self, api, club_c, board_c, platform_admin):
        from django.core.files.base import ContentFile

        from website.models import Website, WebsiteDomain, WebsiteImage, WebsiteText

        club = club_c["club"]
        with tenant_context(club.pk):
            site = Website.objects.create(
                organization=club, public_key=Website.new_key(), state="public"
            )
            WebsiteDomain.objects.create(organization=club, website=site, hostname="c.example.org")
            image = WebsiteImage(organization=club, website=site, key="schluessel1", width=1)
            image.file.save("bild.png", ContentFile(PNG), save=False)
            image.small.save("bild-klein.png", ContentFile(PNG), save=False)
            image.save()
            WebsiteText.objects.create(
                organization=club,
                website=site,
                kind="page",
                slug="geschichte",
                title="Geschichte",
                body="![Fahne](bild:schluessel1)",
                image=image,
            )
        content, _ = export(api(board_c), f"/api/orgs/{club.pk}", with_files=True)
        c = api(platform_admin)
        job = upload(c, "/api/platform", content, filename="export.zip")
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        new = Organization.objects.get(pk=job["result_organization"]["id"])
        with rls_bypass():
            new_site = Website.objects.get(organization=new)
            # startet in der Wartung, eigener Schlüssel, ohne Domains
            assert new_site.state == "maintenance" and new_site.public_key != site.public_key
            assert not WebsiteDomain.objects.filter(website=new_site).exists()
            new_image = WebsiteImage.objects.get(website=new_site)
            assert new_image.key != "schluessel1"
            text = WebsiteText.objects.get(website=new_site, kind="page")
            assert text.body == f"![Fahne](bild:{new_image.key})"
            assert text.image_id == new_image.pk


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestImportEinmalig:
    """Gesamtaudit 30.10. (B-F02): ein Import legt genau einmal an."""

    def test_doppelte_ausfuehrung(self, api, orgs, types, club_c, board_c, board_fed):
        from datatransfer import tasks
        from datatransfer.models import TransferJob

        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(c, base, content, name="Einmal-Verein")
        assert job["status"] == "checked", job
        assert c.post(f"{base}/datatransfer/imports/{job['id']}/run/").status_code == 200
        assert Organization.objects.filter(name="Einmal-Verein").count() == 1
        # Zweiter Start und doppelt zugestellte Aufgabe tun nichts
        assert c.post(f"{base}/datatransfer/imports/{job['id']}/run/").status_code == 400
        tasks.run_import(job["id"])
        assert Organization.objects.filter(name="Einmal-Verein").count() == 1
        with rls_bypass():
            assert TransferJob.objects.get(pk=job["id"]).status == TransferJob.Status.DONE

    def test_fehler_setzt_zurueck(self, api, orgs, types, club_c, board_c, board_fed, monkeypatch):
        from datatransfer import load, tasks
        from datatransfer.models import TransferJob

        content, _ = export(api(board_c), f"/api/orgs/{club_c['club'].pk}")
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        job = upload(c, base, content, name="Kaputt-Verein")

        def boom(job, user):
            Organization.objects.create(name="halb angelegt", founding_year=1900)
            raise RuntimeError("Abbruch")

        monkeypatch.setattr(load, "run", boom)
        assert c.post(f"{base}/datatransfer/imports/{job['id']}/run/").status_code == 200
        with rls_bypass():
            done = TransferJob.objects.get(pk=job["id"])
        assert done.status == TransferJob.Status.CHECKED
        assert "nichts angelegt" in done.error
        assert not Organization.objects.filter(name="halb angelegt").exists()
        # Nicht gestartet: Aufgabe tut nichts
        monkeypatch.undo()
        tasks.run_import(job["id"])
        assert not Organization.objects.filter(name="Kaputt-Verein").exists()
