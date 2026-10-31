"""Row-Level Security direkt auf Datenbankebene (nur PostgreSQL).

Die Tests wechseln wie die laufende Anwendung in die eingeschränkte Rolle
hubiplan_app. Dann darf PostgreSQL selbst keine fremden Zeilen herausgeben –
auch wenn die Anwendung (absichtlich) nicht nach Organisation filtert.

Als Beispiel einer Tabelle mit Mandantentrennung dienen Rollen von
Untereinheiten (``DepartmentRole``). Die Einheiten selbst stehen wie alle
Organisationen ohne RLS in der Organisationstabelle.
"""

from contextlib import contextmanager

import pytest
from django.db import DatabaseError, connection, transaction

from access.models import Role, RoleAssignment
from audit.models import AuditEntry
from core.rls import APP_ROLE
from core.tenancy import rls_bypass, set_rls, tenant_context
from organizations.models import Department, DepartmentRole

pytestmark = [
    pytest.mark.django_db(transaction=False),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Row-Level Security gibt es nur in PostgreSQL"
    ),
]


@contextmanager
def as_app_role():
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)


@pytest.fixture
def data(orgs, board_a, board_b):
    turnen = Department.objects.create(organization=orgs["a"], name="Turnen", founding_year=1950)
    fussball = Department.objects.create(organization=orgs["b"], name="Fußball", founding_year=1960)
    DepartmentRole.objects.create(department=turnen, name="Turnen")
    DepartmentRole.objects.create(department=fussball, name="Fußball")
    return orgs


def test_rolle_ist_kein_superuser():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", [APP_ROLE])
        assert cursor.fetchone() == (False, False)


def test_ohne_organisation_keine_daten(data):
    with as_app_role():
        set_rls(None, None, False)
        assert DepartmentRole.objects.count() == 0
        assert Role.objects.count() == 0
        assert RoleAssignment.objects.count() == 0


def test_nur_aktive_organisation_sichtbar(data):
    with as_app_role(), tenant_context(data["a"].pk):
        # Absichtlich OHNE Filter nach Organisation:
        assert list(DepartmentRole.objects.values_list("name", flat=True)) == ["Turnen"]
        assert {r.organization_id for r in Role.objects.all()} == {data["a"].pk}
        assert {a.organization_id for a in RoleAssignment.objects.all()} == {data["a"].pk}


def test_schreiben_in_fremde_organisation_blockiert(data):
    with as_app_role(), tenant_context(data["a"].pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            DepartmentRole.objects.create(
                department=Department.objects.get(name="Fußball"), name="Eingeschleust"
            )


def test_fremde_zeilen_nicht_aenderbar(data):
    dep_b = DepartmentRole.objects.get(name="Fußball")
    with as_app_role(), tenant_context(data["a"].pk):
        changed = DepartmentRole.objects.filter(pk=dep_b.pk).update(name="gekapert")
        assert changed == 0
        assert DepartmentRole.objects.filter(pk=dep_b.pk).delete()[0] == 0
    dep_b.refresh_from_db()
    assert dep_b.name == "Fußball"


def test_eigene_rollen_ueber_organisationen_hinweg(data, board_a):
    with as_app_role():
        set_rls(None, board_a.pk, False)
        assignments = RoleAssignment.objects.select_related("role")
        assert [a.role.organization_id for a in assignments] == [data["a"].pk]


def test_protokoll_getrennt(data):
    AuditEntry.objects.create(
        organization=data["b"], action="create", object_type="x", object_id="1", object_repr="b"
    )
    with as_app_role(), tenant_context(data["a"].pk):
        assert AuditEntry.objects.count() == 0


def test_bypass_fuer_systemaufgaben(data):
    with as_app_role(), rls_bypass():
        assert DepartmentRole.objects.count() == 2


def test_api_funktioniert_unter_rls(data, board_a, api):
    """Ende-zu-Ende: die API arbeitet mit der eingeschränkten Rolle korrekt."""
    client = api(board_a)
    with as_app_role():
        deps = client.get(f"/api/orgs/{data['a'].pk}/departments/").json()
        assert [d["name"] for d in deps] == ["Turnen"]
        me = client.get("/api/me/organizations/").json()
        assert [o["name"] for o in me] == ["Verein A"]
        resp = client.post(
            f"/api/orgs/{data['a'].pk}/departments/",
            {"name": "Schwimmen", "founding_year": 1980},
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert client.get(f"/api/orgs/{data['b'].pk}/departments/").status_code == 404


# --- Meilenstein 2: Mitglieder ---


@pytest.fixture
def members(orgs):
    from members.models import ContactDetails, Membership, MemberType, Person

    result = {}
    for key in ("a", "b", "c"):
        org = orgs[key]
        scope = orgs["federation"] if key in ("a", "b") else org
        person = Person.objects.create(
            scope=scope, last_name=f"Person {key}", first_name="X", birth_date="1980-01-01"
        )
        MemberType.objects.create(organization=org, name="aktiv", active=True)
        Membership.objects.create(organization=org, scope=scope, person=person)
        ContactDetails.objects.create(
            scope=scope,
            person=person,
            organization=org,
            email=f"{key}@example.org",
            street="s",
            postal_code="1",
            city="c",
        )
        result[key] = person
    return result


def test_mitgliedschaften_nur_eigener_verein(orgs, members):
    from members.models import Membership, MemberType

    with as_app_role(), tenant_context(orgs["a"].pk):
        assert [m.organization_id for m in Membership.objects.all()] == [orgs["a"].pk]
        assert MemberType.objects.count() == 1


def test_personen_im_verbandsbereich(orgs, members):
    from members.models import Person

    with as_app_role(), tenant_context(orgs["a"].pk):
        names = sorted(Person.objects.values_list("last_name", flat=True))
        # Verein A sieht Personen des eigenen Dachverbands (Dublettenprüfung),
        # aber nicht die des eigenständigen Vereins C.
        assert names == ["Person a", "Person b"]
    with as_app_role(), tenant_context(orgs["c"].pk):
        assert list(Person.objects.values_list("last_name", flat=True)) == ["Person c"]


def test_kontaktdaten_je_verein_getrennt(orgs, members):
    from members.models import ContactDetails

    with as_app_role(), tenant_context(orgs["a"].pk):
        assert list(ContactDetails.objects.values_list("email", flat=True)) == ["a@example.org"]


def test_person_nicht_in_fremden_bereich_schreibbar(orgs, members):
    from members.models import Person

    with as_app_role(), tenant_context(orgs["c"].pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            Person.objects.create(
                scope=orgs["federation"], last_name="X", first_name="Y", birth_date="1990-01-01"
            )


def test_mitglieder_api_unter_rls(orgs, members, board_a, api):
    client = api(board_a)
    with as_app_role():
        data = client.get(f"/api/orgs/{orgs['a'].pk}/members/", {"status": "alle"}).json()
        assert [r["last_name"] for r in data["results"]] == ["Person a"]
        assert data["results"][0]["email"] == "a@example.org"


# --- Meilenstein 3: Wechselanfragen ---


def test_wechselanfrage_ende_zu_ende_unter_rls(orgs, board_a, board_b, api):
    """Anfrage stellen (B), sehen (A, nicht C) und bestätigen (A) – alles in der RLS-Rolle."""
    from members.models import Membership, MemberType

    types = {}
    for key in ("a", "b"):
        types[key] = MemberType.objects.create(organization=orgs[key], name="aktiv", active=True)
    a, b = api(board_a), api(board_b)
    contact = {"email": "x@example.org", "street": "s", "postal_code": "1", "city": "c"}
    with as_app_role():
        member = a.post(
            f"/api/orgs/{orgs['a'].pk}/members/admit/",
            {
                "last_name": "Wechsel",
                "first_name": "Willi",
                "birth_date": "1980-01-01",
                "member_type": types["a"].pk,
                "entry_date": "2010-01-01",
                **contact,
            },
            content_type="application/json",
        ).json()
        resp = b.post(
            f"/api/orgs/{orgs['b'].pk}/transfers/",
            {
                "person": member["person_id"],
                "member_type": types["b"].pk,
                "entry_date": "2024-01-01",
                **contact,
            },
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.json()
        tid = resp.json()["id"]
        # Der alte Verein sieht die Anfrage samt gewünschter Art
        incoming = a.get(f"/api/orgs/{orgs['a'].pk}/transfers/").json()
        assert [(t["id"], t["member_type_name"]) for t in incoming] == [(tid, "aktiv")]
        decided = a.post(
            f"/api/orgs/{orgs['a'].pk}/transfers/{tid}/decide/",
            {"decision": "exit"},
            content_type="application/json",
        )
        assert decided.status_code == 200, decided.json()
        listing = b.get(f"/api/orgs/{orgs['b'].pk}/members/").json()
        assert [r["last_name"] for r in listing["results"]] == ["Wechsel"]
    assert Membership.objects.filter(organization=orgs["b"]).count() == 1


def test_wechselanfragen_nur_fuer_beteiligte(orgs, members):
    from members.models import MemberType, TransferRequest

    mt = MemberType.objects.get(organization=orgs["b"])
    TransferRequest.objects.create(
        scope=orgs["federation"],
        person=members["a"],
        from_org=orgs["a"],
        to_org=orgs["b"],
        member_type=mt,
        entry_date="2024-01-01",
    )
    for key, expected in (("a", 1), ("b", 1), ("c", 0)):
        with as_app_role(), tenant_context(orgs[key].pk):
            assert TransferRequest.objects.count() == expected


# --- Meilenstein 4: Zusatzfelder ---


def test_zusatzfelder_getrennt(orgs):
    from customfields.models import FieldDefinition

    for key in ("federation", "a", "b", "c"):
        FieldDefinition.objects.create(organization=orgs[key], label=f"Feld {key}", key=f"f{key}")
    expected = {
        "a": {"Feld a", "Feld federation"},
        "b": {"Feld b", "Feld federation"},
        "c": {"Feld c"},
        "federation": {"Feld federation"},
    }
    for key, labels in expected.items():
        with as_app_role(), tenant_context(orgs[key].pk):
            assert set(FieldDefinition.objects.values_list("label", flat=True)) == labels


# --- Meilenstein 5: Import und Export ---


def test_import_und_export_unter_rls(orgs, board_a, board_b, api, settings, tmp_path):
    import io

    from openpyxl import Workbook

    from members.models import MemberType

    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.PRIVATE_ROOT = tmp_path / "private"
    MemberType.objects.create(organization=orgs["a"], name="aktiv", active=True)
    wb = Workbook()
    wb.active.append(["Name", "Vorname", "Geburtsdatum", "Mitgliedsart", "Eintritt", "Austritt"])
    wb.active.append(["Import", "Ina", "1980-01-01", "aktiv", "2000", "2010"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "import.xlsx"
    a = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}"
    with as_app_role():
        job = a.post(f"{base}/imports/", {"file": buf}).json()
        a.post(f"{base}/imports/{job['id']}/validate/")
        done = a.post(f"{base}/imports/{job['id']}/run/").json()
        assert done["status"] == "imported", done
        export = a.post(
            f"{base}/exports/",
            {
                "kind": "members",
                "file_format": "xlsx",
                "columns": ["last_name"],
                "filters": {"status": "alle"},
            },
            content_type="application/json",
        ).json()
        assert a.get(f"{base}/exports/{export['id']}/").json()["row_count"] == 1
        # Verein B sieht weder Import noch Export von A
        b = api(board_b)
        assert b.get(f"/api/orgs/{orgs['b'].pk}/imports/").json() == []
        assert b.get(f"/api/orgs/{orgs['b'].pk}/exports/").json() == []


# --- Meilenstein 6: Dachverbandszugriff ---


def fed_context(orgs, access):
    fed = orgs["federation"]
    set_rls(fed.pk, None, False, scope_id=fed.pk, fed_access=access)


def test_dachverband_ohne_freigabe_sieht_keine_mitglieder(orgs, members):
    from members.models import Membership

    with as_app_role():
        fed_context(orgs, "")
        assert Membership.objects.count() == 0


def test_dachverband_liest_nur_eigene_vereine(orgs, members):
    from members.models import ContactDetails, Membership, MemberType

    with as_app_role():
        fed_context(orgs, "read")
        clubs = set(Membership.objects.values_list("organization_id", flat=True))
        assert clubs == {orgs["a"].pk, orgs["b"].pk}  # nicht der freie Verein C
        assert MemberType.objects.count() == 2
        assert ContactDetails.objects.count() == 2


def test_dachverband_nur_lesen_kann_nicht_schreiben(orgs, members):
    from members.models import Membership

    with as_app_role():
        fed_context(orgs, "read")
        # PostgreSQL lehnt das Schreiben ab (WITH CHECK der Regel)
        with pytest.raises(DatabaseError), transaction.atomic():
            Membership.objects.update(club_number="X")
    with as_app_role():
        fed_context(orgs, "write")
        assert Membership.objects.update(club_number="Y") == 2
    assert Membership.objects.filter(club_number="Y").count() == 2


def test_dachverbandsliste_api_unter_rls(orgs, members, api):
    from .factories import give_role, make_user

    orgs["federation"].federation_member_access = "read"
    orgs["federation"].save()
    user = make_user("verband-rls@example.org")
    give_role(user, orgs["federation"])
    client = api(user)
    with as_app_role():
        data = client.get(
            f"/api/orgs/{orgs['federation'].pk}/federation/members/", {"status": "alle"}
        ).json()
        assert sorted(r["club"] for r in data["results"]) == ["Verein A", "Verein B"]


def test_rollenwechsel_fuer_jede_neue_verbindung(settings):
    """Mit DATABASE_APP_ROLE arbeitet jede neue Verbindung in der RLS-Rolle."""
    from django.db import connections

    settings.DATABASE_APP_ROLE = APP_ROLE
    conn = connections.create_connection("default")
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_user")
            assert cursor.fetchone()[0] == APP_ROLE
    finally:
        conn.close()


# --- Mitgliederfotos ---


def test_fotos_und_upload_link_unter_rls(orgs, board_a, board_b, api, client, settings, tmp_path):
    import io

    from PIL import Image

    from members.models import MemberPhoto, MemberType, PhotoUploadLink

    settings.PRIVATE_ROOT = tmp_path / "private"
    mt = MemberType.objects.create(organization=orgs["a"], name="aktiv", active=True)
    a = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}/members"

    def img():
        buf = io.BytesIO()
        Image.new("RGB", (300, 400), "green").save(buf, "JPEG")
        buf.seek(0)
        buf.name = "f.jpg"
        return buf

    with as_app_role():
        m = a.post(
            f"{base}/admit/",
            {
                "last_name": "Foto",
                "first_name": "Frida",
                "birth_date": "1990-01-01",
                "member_type": mt.pk,
                "entry_date": "2010-01-01",
                "email": "f@example.org",
                "street": "s",
                "postal_code": "1",
                "city": "c",
            },
            content_type="application/json",
        ).json()
        assert (
            a.post(f"{base}/{m['id']}/photo/", {"file": img(), "consent": "true"}).status_code
            == 200
        )
        link = a.post(f"{base}/{m['id']}/photo-links/", {}, content_type="application/json").json()
        token = link["url"].rsplit("/", 1)[1]
        # Öffentliche Seite ohne Anmeldung, ebenfalls in der RLS-Rolle
        public = client.post(f"/api/public/photo/{token}/", {"file": img(), "consent": "true"})
        assert public.status_code == 201, public.json()
    assert MemberPhoto.objects.count() == 1  # ersetzt
    with as_app_role(), tenant_context(orgs["b"].pk):
        assert MemberPhoto.objects.count() == 0
        assert PhotoUploadLink.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_anmeldung_als_app_rolle_ohne_superuser_rechte():
    """Im Betrieb meldet sich die Anwendung direkt als hubiplan_app an.

    Dann gibt es keinen Weg zurück zum Superuser: RESET ROLE bleibt in der Rolle,
    Shell-Befehle über COPY ... TO PROGRAM und das Abschalten von RLS scheitern.
    """
    import psycopg

    from core.rls import app_login_sql

    password = "nur-ein-test-passwort"
    with connection.cursor() as cursor:
        cursor.execute(app_login_sql(password, connection.connection))
    params = connection.settings_dict
    try:
        with psycopg.connect(
            host=params["HOST"],
            port=params["PORT"] or 5432,
            dbname=params["NAME"],
            user=APP_ROLE,
            password=password,
            autocommit=True,
        ) as conn:
            assert conn.execute("SELECT current_setting('is_superuser')").fetchone()[0] == "off"
            conn.execute("RESET ROLE")
            assert conn.execute("SELECT current_user").fetchone()[0] == APP_ROLE
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("COPY (SELECT 1) TO PROGRAM 'true'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("ALTER TABLE access_role DISABLE ROW LEVEL SECURITY")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("CREATE ROLE angreifer SUPERUSER")
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER ROLE {APP_ROLE} WITH NOLOGIN PASSWORD NULL")
