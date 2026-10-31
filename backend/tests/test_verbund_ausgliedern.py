"""Verbund Schritt 8a: Verein als obere Seite, ferne Untereinheit (erfundene Daten)."""

import datetime

import pytest
from django.utils import timezone

from core.tenancy import rls_bypass, tenant_context
from events.models import Event
from events.services import Viewer
from organizations.models import Department, Organization
from peering import packets, services
from peering.models import Coupling

from .factories import give_role, make_org, make_user
from .test_verbund_kopplung import _setup, api  # noqa: F401
from .verbund_netz import install

pytestmark = pytest.mark.django_db
JSON = "application/json"
VEREIN = "https://verein.example"
ZUG = "https://zug.example"


@pytest.fixture
def net(monkeypatch, tmp_path):
    n = install(monkeypatch, tmp_path)
    n.add(VEREIN)
    n.add(ZUG)
    return n


@pytest.fixture
def world(net):
    """Verein auf „verein.example“, ausgegliederter Zug auf „zug.example“."""
    with net.on(VEREIN):
        club = make_org("Schützenverein Beispiel", city="Beispielhausen")
        club_board = make_user("verein@example.org")
        give_role(club_board, club)
    with net.on(ZUG):
        zug = make_org("Jägerzug Grünrock", city="Beispielhausen")
        zug_board = make_user("zug@example.org")
        give_role(zug_board, zug)
    return {"club": club, "zug": zug, "club_board": club_board, "zug_board": zug_board}


def make_code(net, world) -> str:
    with net.on(VEREIN):
        resp = api(world["club_board"]).post(f"/api/orgs/{world['club'].pk}/peering/codes/")
    assert resp.status_code == 201, resp.json()
    return resp.json()["code"]


def couple(net, world, accept=True):
    code = make_code(net, world)
    with net.on(ZUG):
        resp = api(world["zug_board"]).post(
            f"/api/orgs/{world['zug'].pk}/peering/couplings/",
            {"code": code, "packets": {"unit": "on", "events": "on", "members": "b"}},
            content_type=JSON,
        )
    assert resp.status_code == 201, resp.json()
    lower = Coupling.objects.get(local_unit=world["zug"])
    upper = Coupling.objects.get(local_unit=world["club"])
    if accept:
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/couplings/{upper.pk}/accept/"
            )
        assert resp.status_code == 200, resp.json()
        lower.refresh_from_db()
        upper.refresh_from_db()
    return lower, upper


def event(org, title, **extra):
    start = timezone.now() + datetime.timedelta(days=10)
    values = {
        "organization": org,
        "title": title,
        "starts_at": start,
        "ends_at": start + datetime.timedelta(hours=2),
        "visibility": "members",
        "share_up": True,
    }
    values.update(extra)
    return Event.objects.create(**values)


class TestVereinAlsObereSeite:
    def test_verein_darf_code_erzeugen(self, net, world):
        with net.on(VEREIN):
            resp = api(world["club_board"]).get(f"/api/orgs/{world['club'].pk}/peering/")
        assert resp.json()["can_offer"] is True

    def test_vorschau_nennt_verein_und_nur_passende_pakete(self, net, world):
        code = make_code(net, world)
        with net.on(ZUG):
            resp = api(world["zug_board"]).post(
                f"/api/orgs/{world['zug'].pk}/peering/inspect/", {"code": code}, content_type=JSON
            )
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["remote"]["kind"] == "club"
        send = {p["key"] for p in data["send"]}
        receive = {p["key"] for p in data["receive"]}
        assert send == {"unit", "events", "board", "statute", "unit_members"}
        assert "invoices" not in receive and "circulars" not in receive

    def test_platzhalter_ist_untereinheit_des_vereins(self, net, world):
        lower, upper = couple(net, world, accept=False)
        assert upper.state == "pending" and lower.state == "requested"
        ph = upper.remote_unit
        assert ph.type == "unit" and ph.is_remote
        assert ph.organization_id == world["club"].pk and ph.parent_id == world["club"].pk
        assert Department.objects.filter(pk=ph.pk).exists()
        # Mitgliedermeldung gehört erst zu Schritt 8d: nicht freigegeben
        assert "members" not in lower.packets
        assert lower.options["upper"] == "club"
        assert packets.upper_kind(lower) == packets.upper_kind(upper) == "club"

    def test_stammdaten_und_termine_der_fernen_untereinheit(self, net, world):
        with net.on(ZUG):
            event(world["zug"], "Zugversammlung")
        with net.on(VEREIN):
            event(world["club"], "Schützenfest", share_down=True)
        lower, upper = couple(net, world)
        assert lower.state == upper.state == "active"
        ph = Department.objects.get(pk=upper.remote_unit_id)
        assert ph.name == "Jägerzug Grünrock"
        # Termin des Zugs erscheint im Verein als Termin der Untereinheit
        copy = Event.objects.get(title="Zugversammlung", organization=world["club"])
        assert copy.department_id == ph.pk and copy.remote_uid
        with tenant_context(world["club"].pk):
            viewer = Viewer(org=world["club"], can_manage=True, sees_board=True)
            titles = sorted(e.title for e in viewer.events())
            assert titles == ["Schützenfest", "Zugversammlung"]
            # … und lässt sich dort nicht bearbeiten
            assert not viewer.can_edit(copy)
        # Termin des Vereins erscheint beim Zug
        assert Event.objects.filter(title="Schützenfest", organization=lower.remote_unit).exists()

        with net.on(ZUG):
            Event.objects.filter(title="Zugversammlung").exclude(remote_uid__gt="").delete()
            services.sync(lower)
        assert not Event.objects.filter(title="Zugversammlung").exists()

    def test_ferne_untereinheit_nicht_bearbeitbar(self, net, world):
        lower, upper = couple(net, world)
        ph = upper.remote_unit
        club = world["club"]
        c = api(world["club_board"])
        with net.on(VEREIN):
            units = c.get(f"/api/orgs/{club.pk}/departments/").json()
            assert [u["is_remote"] for u in units if u["id"] == ph.pk] == [True]
            resp = c.patch(
                f"/api/orgs/{club.pk}/departments/{ph.pk}/", {"name": "Anders"}, content_type=JSON
            )
            assert resp.status_code == 400
            assert c.delete(f"/api/orgs/{club.pk}/departments/{ph.pk}/").status_code == 400

    def test_loesen_deaktiviert_platzhalter(self, net, world):
        lower, upper = couple(net, world)
        with net.on(VEREIN):
            services.end(upper, world["club_board"])
        ph = Department.objects.get(pk=upper.remote_unit_id)
        assert not ph.is_active
        lower.refresh_from_db()
        assert lower.state == "ended"

    def test_dachverband_unveraendert(self, net, world):
        """Codes eines Dachverbands tragen keine Art: alles wie bisher."""
        with net.on(VEREIN):
            fed = make_org("Bürgerbund Musterstadt", "federation")
            board = make_user("verband@example.org")
            give_role(board, fed)
            text, _ = services.create_code(fed, board)
        assert services.parse_code(text)["upper"] == "federation"
        probe = Coupling(direction=Coupling.Direction.PARENT)
        assert "members" in {p.key for p in packets.sendable(probe)}


# --- 8c: Ausgliedern-Assistent bis zur bestätigten Kopplung ---


@pytest.fixture
def zug_im_verein(net, world):
    from core.tenancy import tenant_context

    from .factories import make_member

    club = world["club"]
    with net.on(VEREIN), tenant_context(club.pk):
        dept = Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)
        event(club, "Alter Zugabend", department=dept)
    erika = make_member(club, "Erika", "Muster", departments=[dept])
    make_member(club, "Bernd", "Berg")
    return {"dept": dept, "erika": erika}


def spin_off(net, world, dept, **data):
    body = {
        "unit": dept.pk,
        "way": "keep",
        "cutoff": "2027-01-01",
        "checklist": {"privacy": True, "processing": True},
        "with_files": False,
        **data,
    }
    with net.on(VEREIN):
        return api(world["club_board"]).post(
            f"/api/orgs/{world['club'].pk}/peering/spin-offs/", body, content_type=JSON
        )


def platform_import(net, content: bytes, **options):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from organizations.models import Organization

    from .factories import give_role

    admin = make_user("plattform@zug.example")
    give_role(admin, Organization.platform())
    c = api(admin)
    with net.on(ZUG):
        resp = c.post(
            "/api/platform/datatransfer/imports/",
            {"file": SimpleUploadedFile("zug.json", content), **options},
        )
        assert resp.status_code == 201, resp.json()
        job = c.get(f"/api/platform/datatransfer/imports/{resp.json()['id']}/").json()
        assert job["preview"].get("error_count") == 0, job["preview"] or job["error"]
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        return c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()


class TestAusgliedern:
    def test_pruefliste_ist_pflicht(self, net, world, zug_im_verein):
        resp = spin_off(net, world, zug_im_verein["dept"], checklist={"privacy": True})
        assert resp.status_code == 400
        assert "Auftragsverarbeitung" in resp.json()["detail"]

    def test_nur_mit_exportrecht(self, net, world, zug_im_verein):
        with net.on(VEREIN):
            kasse = make_user("kasse@example.org")
            give_role(kasse, world["club"], permissions=["peering.manage"], name="Verbund")
            resp = api(kasse).post(
                f"/api/orgs/{world['club'].pk}/peering/spin-offs/",
                {"unit": zug_im_verein["dept"].pk, "way": "keep", "cutoff": "2027-01-01"},
                content_type=JSON,
            )
        assert resp.status_code == 403

    def test_ablauf_bis_platzhalter(self, net, world, zug_im_verein):
        from members.models import Membership

        dept = zug_im_verein["dept"]
        resp = spin_off(net, world, dept)
        assert resp.status_code == 201, resp.json()
        spin = resp.json()
        assert spin["state"] == "prepared" and spin["export_job"]["status"] == "done"
        # Export holen: Code steht nur in der Datei, nicht mehr in der Datenbank
        c = api(world["club_board"])
        with net.on(VEREIN):
            base = f"/api/orgs/{world['club'].pk}/datatransfer/exports/{spin['export_job']['id']}"
            content = b"".join(c.get(f"{base}/download/").streaming_content)
        import json as _json

        doc = _json.loads(content)
        assert doc["spin_off"]["way"] == "keep" and doc["spin_off"]["code"]
        from datatransfer.models import TransferJob

        assert (
            "code" not in TransferJob.objects.get(pk=spin["export_job"]["id"]).options["spin_off"]
        )

        job = platform_import(net, content, city="Neustadt")
        assert job["status"] == "done", job
        assert job["summary"]["spin_off"]["coupling"] == "requested", job["summary"]
        new = Organization.objects.get(pk=job["result_organization"]["id"])
        assert new.type == "club" and new.name == "Jägerzug"
        with rls_bypass():
            moved = Membership.objects.get(organization=new)
        assert moved.origin_ref == str(zug_im_verein["erika"].pk)

        upper = Coupling.objects.get(local_unit=world["club"])
        assert upper.state == "pending"
        # Platzhalter ist die Untereinheit selbst; sie bleibt bis zur Bestätigung, wie sie war
        assert upper.remote_unit_id == dept.pk
        dept.refresh_from_db()
        assert not dept.is_remote
        with net.on(VEREIN):
            resp = c.post(f"/api/orgs/{world['club'].pk}/peering/couplings/{upper.pk}/accept/")
        assert resp.status_code == 200, resp.json()
        dept.refresh_from_db()
        assert dept.is_remote and dept.is_active
        with net.on(VEREIN):
            data = c.get(f"/api/orgs/{world['club'].pk}/peering/spin-offs/").json()
        assert data["spin_offs"][0]["state"] == "done"
        # Alte Termine der Untereinheit bleiben beim Verein
        assert Event.objects.filter(title="Alter Zugabend", department=dept).exists()
        # Mitglieder bleiben im Verein (Weg A)
        assert Membership.objects.filter(organization=world["club"]).count() == 2

    def test_ablehnen_laesst_untereinheit_unveraendert(self, net, world, zug_im_verein):
        dept = zug_im_verein["dept"]
        spin = spin_off(net, world, dept).json()
        c = api(world["club_board"])
        with net.on(VEREIN):
            base = f"/api/orgs/{world['club'].pk}/datatransfer/exports/{spin['export_job']['id']}"
            content = b"".join(c.get(f"{base}/download/").streaming_content)
        platform_import(net, content)
        upper = Coupling.objects.get(local_unit=world["club"])
        with net.on(VEREIN):
            services.decline(upper, world["club_board"])
        dept.refresh_from_db()
        assert dept.is_active and not dept.is_remote
        assert Event.objects.filter(title="Alter Zugabend").exists()
        with net.on(VEREIN):
            data = c.get(f"/api/orgs/{world['club'].pk}/peering/spin-offs/").json()
        assert data["spin_offs"][0]["state"] == "cancelled"

    def test_abbrechen_macht_code_ungueltig(self, net, world, zug_im_verein):
        spin = spin_off(net, world, zug_im_verein["dept"]).json()
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/spin-offs/{spin['id']}/cancel/"
            )
        assert resp.json()["state"] == "cancelled"
        # Neue Ausgliederung ist danach wieder möglich
        assert spin_off(net, world, zug_im_verein["dept"]).status_code == 201


# --- 8d: fern geführte Mitgliedschaften (Weg A) ---


def ausgegliedert(net, world, zug_im_verein, way="keep"):
    """Ausgliedern bis zur bestätigten Kopplung; gibt (neue Einheit, unten, oben) zurück."""
    checklist = (
        {"privacy": True, "processing": True}
        if way == "keep"
        else {"statute": True, "processing": True}
    )
    spin = spin_off(net, world, zug_im_verein["dept"], way=way, checklist=checklist).json()
    c = api(world["club_board"])
    with net.on(VEREIN):
        base = f"/api/orgs/{world['club'].pk}/datatransfer/exports/{spin['export_job']['id']}"
        content = b"".join(c.get(f"{base}/download/").streaming_content)
    job = platform_import(net, content, city="Neustadt")
    new = Organization.objects.get(pk=job["result_organization"]["id"])
    upper = Coupling.objects.get(local_unit=world["club"])
    with net.on(VEREIN):
        services.accept(upper, world["club_board"])
    lower = Coupling.objects.get(local_unit=new)
    upper.refresh_from_db()
    lower.refresh_from_db()
    return new, lower, upper


def sync_up(net, lower):
    with net.on(ZUG):
        services.sync(lower)


class TestFernGefuehrt:
    def test_abgleich_ueber_kennungen(self, net, world, zug_im_verein):
        from members.models import DepartmentMembership, Membership, MembershipPeriod

        club, dept = world["club"], zug_im_verein["dept"]
        new, lower, upper = ausgegliedert(net, world, zug_im_verein)
        assert lower.level("unit_members") == "on"
        erika = Membership.objects.get(pk=zug_im_verein["erika"].pk)
        assert erika.managed_by_id == upper.pk
        bernd = Membership.objects.get(organization=club, person__first_name="Bernd")
        assert bernd.managed_by_id is None

        # Die Untereinheit ändert den Namen: der Verein übernimmt, ohne neue Person
        with rls_bypass():
            theirs = Membership.objects.get(organization=new)
            theirs.person.last_name = "Muster-Neu"
            theirs.person.save()
        sync_up(net, lower)
        erika.person.refresh_from_db()
        assert erika.person.last_name == "Muster-Neu"
        assert Membership.objects.filter(organization=club).count() == 2

        # Neues Mitglied der Untereinheit: neue, fern geführte Mitgliedschaft im Verein
        from .factories import make_member

        with net.on(ZUG):
            make_member(new, "Karl", "Neumann")
        sync_up(net, lower)
        karl = Membership.objects.get(organization=club, person__first_name="Karl")
        assert karl.managed_by_id == upper.pk
        assert DepartmentMembership.objects.filter(membership=karl, department=dept).exists()

        # Gleicher Name wie ein Vereinsmitglied: Klärfall, nie automatisch zusammengeführt
        with net.on(ZUG):
            make_member(new, "Bernd", "Berg", birth_date=bernd.person.birth_date)
        sync_up(net, lower)
        rm = upper.members.get(status="unclear")
        assert rm.data["candidates"] == [bernd.person_id]
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{club.pk}/peering/couplings/{upper.pk}/members/{rm.pk}/resolve/",
                {"person": bernd.person_id},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        bernd.refresh_from_db()
        assert bernd.managed_by_id == upper.pk
        assert Membership.objects.filter(organization=club).count() == 3

        # Erika verlässt die Untereinheit: bleibt Vereinsmitglied, der Verein pflegt sie wieder
        with rls_bypass():
            period = MembershipPeriod.objects.get(membership=theirs)
            period.exit_date = period.entry_date
            period.exit_reason = "exit"
            period.save()
        sync_up(net, lower)
        erika.refresh_from_db()
        assert erika.managed_by_id is None and erika.current_period() is not None
        link = DepartmentMembership.objects.get(membership=erika, department=dept)
        assert link.valid_until is not None

    def test_schreibschutz_und_korrekturvorschlag(self, net, world, zug_im_verein):
        from portal.models import ChangeRequest

        club = world["club"]
        new, lower, upper = ausgegliedert(net, world, zug_im_verein)
        sync_up(net, lower)
        erika = zug_im_verein["erika"]
        assert upper.members.filter(membership_id=erika.pk).exists(), list(
            upper.members.values("uid", "membership_id", "status")
        )
        c = api(world["club_board"])
        with net.on(VEREIN):
            detail = c.get(f"/api/orgs/{club.pk}/members/{erika.pk}/").json()
            assert detail["managed_by"]["name"] == "Jägerzug"
            resp = c.patch(
                f"/api/orgs/{club.pk}/members/{erika.pk}/", {"city": "Anderswo"}, content_type=JSON
            )
            assert resp.status_code == 400
            # Mitgliedsnummer bleibt Sache des Vereins
            resp = c.patch(
                f"/api/orgs/{club.pk}/members/{erika.pk}/", {"club_number": "17"}, content_type=JSON
            )
            assert resp.status_code == 200
            resp = c.post(
                f"/api/orgs/{club.pk}/peering/members/{erika.pk}/suggest/",
                {"first_name": "Erica", "message": "Schreibweise laut Ausweis"},
                content_type=JSON,
            )
        assert resp.status_code == 202, resp.json()
        with rls_bypass():
            change = ChangeRequest.objects.get(organization=new)
        assert change.data == {"first_name": "Erica"}

    def test_weg_b_ohne_fernfuehrung(self, net, world, zug_im_verein):
        from members.models import Membership

        new, lower, upper = ausgegliedert(net, world, zug_im_verein, way="move")
        assert not Membership.objects.filter(managed_by=upper).exists()

    def test_weg_b_sammelaustritt(self, net, world, zug_im_verein):
        import datetime

        from members.models import Membership

        club = world["club"]
        new, lower, upper = ausgegliedert(net, world, zug_im_verein, way="move")
        spin = upper.spin_off
        c = api(world["club_board"])
        url = f"/api/orgs/{club.pk}/peering/spin-offs/{spin.pk}/exit/"
        with net.on(VEREIN):
            preview = c.get(url).json()["members"]
            assert [m["name"] for m in preview] == ["Muster, Erika"]
            resp = c.post(url, {}, content_type=JSON)
            assert resp.status_code == 200, resp.json()
            assert resp.json()["exited_count"] == 1
            assert c.post(url, {}, content_type=JSON).status_code == 400
        erika = Membership.objects.get(pk=zug_im_verein["erika"].pk)
        period = erika.periods.get()
        assert period.exit_date == datetime.date(2027, 1, 1)
        assert period.exit_reason == "transfer"
        # Bernd gehört nicht zur Untereinheit und bleibt
        bernd = Membership.objects.get(organization=club, person__first_name="Bernd")
        assert bernd.periods.get().exit_date is None

    def test_weg_a_kein_sammelaustritt(self, net, world, zug_im_verein):
        new, lower, upper = ausgegliedert(net, world, zug_im_verein)
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/spin-offs/{upper.spin_off.pk}/exit/",
                {},
                content_type=JSON,
            )
        assert resp.status_code == 400

    def test_loesen_gibt_mitglieder_zurueck(self, net, world, zug_im_verein):
        from members.models import Membership

        new, lower, upper = ausgegliedert(net, world, zug_im_verein)
        sync_up(net, lower)
        with net.on(VEREIN):
            services.end(upper, world["club_board"])
        assert not Membership.objects.filter(managed_by=upper).exists()
