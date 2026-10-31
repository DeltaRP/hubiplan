"""Demodaten der Pilotorganisationen und Entfernen alter Demodaten."""

import io

import pytest
from django.core.management import call_command
from PIL import Image

from access.models import RoleAssignment
from accounts.models import User
from members.models import MemberPhoto, Membership, MemberType, Person
from organizations.models import Department, Organization

from .factories import give_role, make_org, make_user

# Demodaten anlegen dauert je Test einige Sekunden (siehe conftest: langsam = zuerst)
pytestmark = [pytest.mark.django_db, pytest.mark.langsam]

PILOT_FED = "Bürger-Schützenverein Neuss-Grimlinghausen von 1855 e.V."
PILOT_CLUB = "Hubertus-Schützenverein Neuss-Grimlinghausen von 1920"
ZUEGE = [
    "Herolde",
    "Strauchdiebe",
    "Hippelänger Prachtkerle",
    "Rose vom Rhein",
    "Drüje Fuchs",
    "Dörper Jonge",
    "Dööschtije Jonge",
    "Dicke Fründe",
    "Hippelänger Gömbötz",
    "Die härtesten unter der Sonne",
    "Wesse mer noch net",
    "Jot drop",
    "De Zojetrockene",
    "Hubertus Fanfaren-Corps",
]


def seed():
    call_command("seed_testdata", password="Test-Passwort-123", stdout=io.StringIO())


def test_pilotorganisationen_und_zuege():
    seed()
    fed = Organization.objects.get(name=PILOT_FED)
    club = Organization.objects.get(name=PILOT_CLUB)
    assert fed.type == "federation" and club.parent == fed
    assert (club.department_label, club.department_label_plural) == ("Zug", "Züge")
    assert (
        list(Department.objects.filter(organization=club).values_list("name", flat=True)) == ZUEGE
    )
    # Mitglieder sinnvoll auf die Züge verteilt
    for zug in Department.objects.filter(organization=club):
        assert zug.unit_memberships.count() >= 8
    assert Membership.objects.filter(organization=club).count() > 150
    assert MemberType.objects.filter(organization=club).count() == 4
    assert set(Organization.objects.exclude(type="unit").values_list("name", flat=True)) == {
        PILOT_FED,
        PILOT_CLUB,
        "HUBIplan",
    }


def test_nur_wenige_testzugaenge_alle_erfunden():
    seed()
    emails = set(User.objects.values_list("email", flat=True))
    assert emails == {
        "plattform@hubiplan.test",
        "vorstand@bsv-grimlinghausen.test",
        "vorstand@hubertus-grimlinghausen.test",
        "kasse@hubertus-grimlinghausen.test",
    }
    kasse = User.objects.get(email="kasse@hubertus-grimlinghausen.test")
    perms = RoleAssignment.objects.get(user=kasse).role.permissions
    assert "members.edit" not in perms and "members.view" in perms
    # Mitgliederdaten sind erfunden
    from members.models import ContactDetails

    assert all(c.email.endswith(".test") for c in ContactDetails.objects.all())


def test_wiederholbar():
    seed()
    counts = (Membership.objects.count(), Person.objects.count(), RoleAssignment.objects.count())
    seed()
    assert (
        Membership.objects.count(),
        Person.objects.count(),
        RoleAssignment.objects.count(),
    ) == counts


def test_zuege_in_der_api_in_reihenfolge(api):
    seed()
    user = User.objects.get(email="vorstand@hubertus-grimlinghausen.test")
    club = Organization.objects.get(name=PILOT_CLUB)
    names = [d["name"] for d in api(user).get(f"/api/orgs/{club.pk}/departments/").json()]
    assert names == ZUEGE


class TestAlteDemodatenEntfernen:
    @pytest.fixture
    def legacy(self, settings, tmp_path):
        """Nachbau der früheren Demodaten mit Mitglied, Foto und Testzugang."""
        settings.PRIVATE_ROOT = tmp_path / "private"
        settings.MEDIA_ROOT = tmp_path / "media"
        fed = make_org("Schützenbund Musterland e. V.", "federation")
        sv = make_org("Schützenverein Musterstadt 1890 e. V.", parent=fed)
        chess = make_org("Schachfreunde Testdorf")
        board = make_user("vorstand@sv-musterstadt.test")
        give_role(board, sv)
        give_role(make_user("schach@schachfreunde.test"), chess)
        mt = MemberType.objects.create(organization=sv, name="aktiv", active=True)
        from members import services

        m = services.admit(
            sv,
            {
                "last_name": "Alt",
                "first_name": "Anna",
                "birth_date": "1980-01-01",
                "member_type": mt,
                "entry_date": "2000-01-01",
                "email": "anna@beispiel.test",
                "street": "s",
                "postal_code": "1",
                "city": "c",
            },
        )
        from members import photos

        buf = io.BytesIO()
        Image.new("RGB", (300, 400)).save(buf, "JPEG")
        buf.seek(0)
        buf.name = "f.jpg"
        buf.size = len(buf.getvalue())
        photo = photos.store(m, photos.process(buf), "approved", "board")
        return {"photo_path": photo.image.path}

    @pytest.fixture
    def others(self, db, django_user_model):
        """Was nicht gelöscht werden darf: Admin, echte Organisation, eigener Zugang."""
        admin = django_user_model.objects.create_superuser(
            email="admin@hubiplan.test", password="x"
        )
        real = make_org("Echter Verein")
        person = make_user("ralf@example.org")
        give_role(person, real)
        return admin, real

    def test_probelauf_loescht_nichts(self, legacy, others):
        seed()
        out = io.StringIO()
        call_command("seed_testdata", remove_legacy_demo=True, dry_run=True, stdout=out)
        assert "Schützenverein Musterstadt" in out.getvalue()
        assert "vorstand@sv-musterstadt.test" in out.getvalue()
        assert Organization.objects.filter(name="Schachfreunde Testdorf").exists()
        assert User.objects.filter(email="vorstand@sv-musterstadt.test").exists()

    def test_entfernt_nur_alte_demodaten(self, legacy, others, django_capture_on_commit_callbacks):
        import os

        seed()
        pilot_members = Membership.objects.filter(organization__name=PILOT_CLUB).count()
        # Fotodateien verschwinden erst nach dem Commit
        with django_capture_on_commit_callbacks(execute=True):
            call_command("seed_testdata", remove_legacy_demo=True, stdout=io.StringIO())
        names = set(Organization.objects.exclude(type="unit").values_list("name", flat=True))
        assert names == {PILOT_FED, PILOT_CLUB, "HUBIplan", "Echter Verein"}
        assert not User.objects.filter(
            email__in=["vorstand@sv-musterstadt.test", "schach@schachfreunde.test"]
        ).exists()
        assert not Person.objects.filter(last_name="Alt").exists()
        assert not MemberPhoto.objects.exists()
        assert not os.path.exists(legacy["photo_path"])  # Datei ist weg
        # Unangetastet: Admin, echte Organisation samt Zugang, Pilotdaten und ihre Zugänge
        assert User.objects.filter(email="admin@hubiplan.test", is_superuser=True).exists()
        assert User.objects.filter(email="ralf@example.org").exists()
        assert User.objects.filter(email="vorstand@hubertus-grimlinghausen.test").exists()
        assert User.objects.filter(email="plattform@hubiplan.test").exists()
        assert Membership.objects.filter(organization__name=PILOT_CLUB).count() == pilot_members

    def test_entfernt_auch_kassendaten(self, legacy, others):
        import datetime

        from finance.models import Account, Booking, Category

        sv = Organization.objects.get(name="Schützenverein Musterstadt 1890 e. V.")
        acc = Account.objects.create(
            organization=sv, name="Giro", opening_date=datetime.date(2026, 1, 1)
        )
        cat = Category.objects.create(organization=sv, name="Beiträge", kind="income")
        Booking.objects.create(
            organization=sv,
            year=2026,
            number=1,
            date=datetime.date(2026, 2, 1),
            kind="income",
            amount=10,
            account=acc,
            category=cat,
            text="Beitrag",
        )
        call_command("seed_testdata", remove_legacy_demo=True, stdout=io.StringIO())
        assert not Booking.objects.exists()
        assert not Account.objects.exists()
        assert not Organization.objects.filter(pk=sv.pk).exists()

    def test_nichts_zu_tun(self, db):
        out = io.StringIO()
        call_command("seed_testdata", remove_legacy_demo=True, stdout=out)
        assert "Keine alten Demodaten" in out.getvalue()


ZUG_ROLLEN = ["Oberleutnant", "Leutnant", "Spieß", "Kassierer", "Schriftführer"]


class TestZugrollen:
    def test_jeder_zug_hat_die_fuenf_rollen_in_reihenfolge(self):
        seed()
        club = Organization.objects.get(name=PILOT_CLUB)
        for zug in Department.objects.filter(organization=club):
            assert [r.name for r in zug.unit_roles.all()] == ZUG_ROLLEN
            # nur zur Information: ohne Rechte
            assert all(r.permissions == [] for r in zug.unit_roles.all())

    def test_besetzung_mit_mehrfachrollen_und_luecken(self):
        from members.models import DepartmentRoleHolder

        seed()
        club = Organization.objects.get(name=PILOT_CLUB)
        doppelt = frei = 0
        for zug in Department.objects.filter(organization=club):
            holders = DepartmentRoleHolder.objects.filter(role__department=zug)
            # Inhaber sind Mitglieder dieses Zugs
            for h in holders:
                assert h.membership.department_memberships.filter(department=zug).exists()
            people = [h.membership_id for h in holders]
            doppelt += len(people) != len(set(people))
            frei += holders.count() < len(ZUG_ROLLEN)
        assert doppelt >= 3 and frei >= 2

    def test_wiederholbar_und_alte_rolle_wird_oberleutnant(self):
        from members.models import DepartmentRoleHolder

        seed()
        club = Organization.objects.get(name=PILOT_CLUB)
        herolde = Department.objects.get(organization=club, name="Herolde")
        ol = herolde.unit_roles.get(name="Oberleutnant")
        holder = DepartmentRoleHolder.objects.get(role=ol)
        # Stand der früheren Demodaten nachstellen: Rolle hieß „Zugführer“
        ol.name = "Zugführer"
        ol.save()
        count = DepartmentRoleHolder.objects.count()
        seed()
        ol.refresh_from_db()
        assert ol.name == "Oberleutnant"
        assert DepartmentRoleHolder.objects.get(role=ol) == holder
        assert DepartmentRoleHolder.objects.count() == count

    def test_hoechstens_zwei_rollen_je_person_auch_bei_alten_daten(self):
        """Früherer Stand: nur Oberleutnant und Spieß besetzt, der Rest wird ergänzt."""
        from collections import Counter

        from members.models import DepartmentRoleHolder

        seed()
        club = Organization.objects.get(name=PILOT_CLUB)
        DepartmentRoleHolder.objects.filter(
            role__department__organization=club,
            role__name__in=["Leutnant", "Kassierer", "Schriftführer"],
        ).delete()
        seed()
        for zug in Department.objects.filter(organization=club):
            per_person = Counter(
                DepartmentRoleHolder.objects.filter(role__department=zug).values_list(
                    "membership_id", flat=True
                )
            )
            assert max(per_person.values()) <= 2, zug.name

    def test_zugansicht_zeigt_inhaber(self, api):
        seed()
        user = User.objects.get(email="vorstand@hubertus-grimlinghausen.test")
        club = Organization.objects.get(name=PILOT_CLUB)
        deps = api(user).get(f"/api/orgs/{club.pk}/departments/").json()
        roles = deps[0]["roles"]
        assert [r["name"] for r in roles] == ZUG_ROLLEN
        assert roles[0]["holders"] and roles[0]["holders"][0]["name"]


def test_mehrere_rollen_je_person_in_derselben_abteilung(api):
    """Eine Person kann z. B. Spieß und Kassierer zugleich sein."""
    from members.models import DepartmentRoleHolder

    from .factories import make_member

    club = make_org("Verein")
    board = make_user("board@example.org")
    give_role(board, club)
    zug = Department.objects.create(organization=club, name="1. Zug", founding_year=1990)
    spiess = zug.unit_roles.create(organization=club, name="Spieß")
    kasse = zug.unit_roles.create(organization=club, name="Kassierer")
    assert (spiess.position, kasse.position) == (1, 2)
    m = make_member(club, "Sina", "Spieß", "sina@example.org", departments=[zug])
    for role in (spiess, kasse):
        resp = api(board).post(
            f"/api/orgs/{club.pk}/members/{m.pk}/department-roles/",
            {"role": role.pk, "valid_from": "2024-01-01"},
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.json()
    assert DepartmentRoleHolder.objects.filter(membership=m).count() == 2
    deps = api(board).get(f"/api/orgs/{club.pk}/departments/").json()
    assert [r["holders"][0]["name"] for r in deps[0]["roles"]] == ["Sina Spieß", "Sina Spieß"]


class TestKassendaten:
    @pytest.fixture(autouse=True)
    def heute(self, monkeypatch):
        import datetime

        monkeypatch.setattr(
            "finance.seed.timezone.localdate", lambda *a: datetime.date(2026, 10, 24)
        )

    def test_konten_kategorien_buchungen(self):
        from finance import services
        from finance.models import Account, Booking, Category

        seed()
        club = Organization.objects.get(name=PILOT_CLUB)
        fed = Organization.objects.get(name=PILOT_FED)
        assert list(Account.objects.filter(organization=club).values_list("name", flat=True)) == [
            "Girokonto",
            "Barkasse",
            "Sparkonto Rücklage",
        ]
        beitraege = Category.objects.get(organization=club, name="Mitgliedsbeiträge")
        assert beitraege.kind == Category.Kind.INCOME
        bookings = Booking.objects.filter(organization=club)
        assert 40 <= bookings.count() <= 80
        assert set(bookings.values_list("kind", flat=True)) == {"income", "expense", "transfer"}
        # lückenlose Nummern, alle im laufenden Geschäftsjahr und nicht in der Zukunft
        assert sorted(bookings.values_list("number", flat=True)) == list(
            range(1, bookings.count() + 1)
        )
        assert all(b.year == 2026 and b.date.isoformat() <= "2026-10-24" for b in bookings)
        assert bookings.filter(membership__isnull=False).exists()
        assert bookings.filter(department__name="Hubertus Fanfaren-Corps").exists()
        # Bestände plausibel (keine Barkasse im Minus)
        for account in Account.objects.filter(organization=club):
            assert services.balance(account) > 0
        assert Booking.objects.filter(organization=fed).count() >= 4
        # Steuerbereiche nur beim Verein (eingeschaltet), nicht beim Dachverband
        assert not Category.objects.filter(organization=fed).exclude(tax_area="").exists()
        overview = services.overview(club, 2026)
        assert overview["tax_areas"]
        # Beispiel-Veranstaltung mit den Festbuchungen
        from finance.models import Project
        from finance.projects import evaluation

        fest = Project.objects.get(organization=club)
        assert fest.name == "Schützenfest 2026"
        assert fest.series.name == "Schützenfest"
        result = evaluation(fest)
        assert result["booking_count"] >= 8
        assert {c["name"] for c in result["categories"]} >= {
            "Schützenfest Festzelt",
            "Schützenfest Getränke",
        }

    def test_wiederholbar(self):
        from finance.models import Account, Booking

        seed()
        counts = (Booking.objects.count(), Account.objects.count())
        seed()
        assert (Booking.objects.count(), Account.objects.count()) == counts

    def test_kassen_api_fuer_kassierer(self, api):
        seed()
        kasse = User.objects.get(email="kasse@hubertus-grimlinghausen.test")
        club = Organization.objects.get(name=PILOT_CLUB)
        resp = api(kasse).get(f"/api/orgs/{club.pk}/finance/accounts/")
        assert resp.status_code == 200


def test_webseite_des_demovereins(settings):
    from django.test import Client

    from honors.models import Reign
    from website import privacy
    from website.models import Website

    seed()
    club = Organization.objects.get(name=PILOT_CLUB)
    site = Website.objects.get(organization=club)
    assert site.state == "maintenance" and "website" in club.enabled_modules
    assert site.domains.get().hostname.endswith(".test")
    assert site.privacy_text
    assert privacy.facts(site)["honors"]
    assert Reign.objects.filter(organization=club).count() > 10
    # wiederholbar
    counts = (Reign.objects.count(), RoleAssignment.objects.count(), club.social_links.count())
    seed()
    assert (
        Reign.objects.count(),
        RoleAssignment.objects.count(),
        club.social_links.count(),
    ) == counts
    # Öffentliche Sicht (nur im Test auf „öffentlich“ geschaltet)
    site.state = "public"
    site.save()
    c = Client()
    info = c.get(f"/api/public/site/v1/{site.public_key}/").json()
    assert info["unit_label_plural"] == "Züge"
    assert {"instagram", "facebook", "tiktok", "x"} <= {s["kind"] for s in info["social"]}
    board = c.get(f"/api/public/site/v1/{site.public_key}/board/").json()
    assert [r["name"] for r in board["roles"]][:2] == ["1. Brudermeister", "2. Brudermeister"]
    assert len(board["chronicle"][0]["holders"]) == 2
    honors = c.get(f"/api/public/site/v1/{site.public_key}/honors/").json()["dignities"]
    assert [d["name"] for d in honors] == ["König", "Prinz", "Schülerprinz"]
