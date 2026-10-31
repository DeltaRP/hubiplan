"""Meilenstein 3: Art wechseln, Austritt, Wiedereintritt, Wechselanfrage, Löschfrist."""

import datetime

import pytest

from audit.models import AuditEntry
from members.models import (
    ContactDetails,
    FederationMember,
    Membership,
    MemberType,
    TransferRequest,
)
from members.workflows import purge_expired
from organizations.models import Department, PlatformSettings

from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b", "c")}


@pytest.fixture
def member(api, orgs, types, board_a):
    return admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()


def url(orgs, member, suffix):
    return f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/{suffix}"


class TestArtWechseln:
    def test_alte_art_endet_am_vortag(self, api, orgs, types, member, board_a):
        resp = api(board_a).post(
            url(orgs, member, "change-type/"),
            {"member_type": types["a"]["passiv"].pk, "valid_from": "2020-07-01"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        history = resp.json()["type_history"]
        assert [(t["member_type_name"], t["valid_from"], t["valid_until"]) for t in history] == [
            ("aktiv", "2015-03-01", "2020-06-30"),
            ("passiv", "2020-07-01", None),
        ]
        assert len(resp.json()["periods"]) == 1  # Zeitraum läuft weiter

    def test_wechsel_zu_aktiv_mit_pruefung(self, api, orgs, types, member, board_a, board_b):
        # Erika wird in B passiv aufgenommen und will dort aktiv werden
        b = (
            api(board_b)
            .post(
                f"/api/orgs/{orgs['b'].pk}/members/admit/",
                {
                    "person": member["person_id"],
                    "member_type": types["b"]["passiv"].pk,
                    "entry_date": "2020-01-01",
                    "email": "e@example.org",
                    "street": "x",
                    "postal_code": "1",
                    "city": "y",
                },
                content_type=JSON,
            )
            .json()
        )
        resp = api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/members/{b['id']}/change-type/",
            {"member_type": types["b"]["aktiv"].pk, "valid_from": "2022-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "Verein A" in str(resp.json())


class TestAustrittUndWiedereintritt:
    def test_austritt_schliesst_alles(self, api, orgs, types, member, board_a):
        dep = Department.objects.create(organization=orgs["a"], name="Turnen", founding_year=1950)
        c = api(board_a)
        c.post(
            url(orgs, member, "departments/"),
            {"department": dep.pk, "valid_from": "2016-01-01"},
            content_type=JSON,
        )
        resp = c.post(
            url(orgs, member, "exit/"),
            {"exit_date": "2023-12-31", "exit_reason": "exit", "note": "Umzug"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["status"] == "former"
        assert data["periods"][0]["exit_reason_label"] == "Austritt"
        assert data["type_history"][0]["valid_until"] == "2023-12-31"
        assert data["departments"][0]["valid_until"] == "2023-12-31"
        assert data["federation"]["is_member"] is False  # letzte gemeldete endete
        assert data["purge_due"] == "2025-12-31"  # Standard-Löschfrist 24 Monate
        # Archiv: in der Liste unter „ehemalig“
        listing = c.get(f"/api/orgs/{orgs['a'].pk}/members/", {"status": "ehemalig"}).json()
        assert listing["count"] == 1

    def test_doppelter_austritt(self, api, orgs, member, board_a):
        c = api(board_a)
        body = {"exit_date": "2023-12-31", "exit_reason": "death"}
        c.post(url(orgs, member, "exit/"), body, content_type=JSON)
        assert c.post(url(orgs, member, "exit/"), body, content_type=JSON).status_code == 400

    def test_wiedereintritt_neuer_zeitraum(self, api, orgs, types, member, board_a):
        c = api(board_a)
        c.post(
            url(orgs, member, "exit/"),
            {"exit_date": "2018-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        early = c.post(
            url(orgs, member, "reentry/"),
            {"entry_date": "2018-06-01", "member_type": types["a"]["aktiv"].pk},
            content_type=JSON,
        )
        assert early.status_code == 400
        resp = c.post(
            url(orgs, member, "reentry/"),
            {"entry_date": "2021-04-01", "member_type": types["a"]["passiv"].pk},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["status"] == "active"
        assert [(p["entry_date"], p["exit_date"]) for p in data["periods"]] == [
            ("2015-03-01", "2018-12-31"),
            ("2021-04-01", None),
        ]
        assert data["federation"]["member_number"] == 1  # Nummer bleibt
        assert data["federation"]["entry_date"] == "2015-03-01"

    def test_wiedereintritt_nur_fuer_ehemalige(self, api, orgs, types, member, board_a):
        resp = api(board_a).post(
            url(orgs, member, "reentry/"),
            {"entry_date": "2024-01-01", "member_type": types["a"]["aktiv"].pk},
            content_type=JSON,
        )
        assert resp.status_code == 400


class TestWechselanfrage:
    @pytest.fixture
    def request_b(self, api, orgs, types, member, board_b):
        return api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/transfers/",
            {
                "person": member["person_id"],
                "member_type": types["b"]["aktiv"].pk,
                "entry_date": "2024-07-01",
                "message": "Bitte um Freigabe",
                "email": "erika.neu@example.org",
                "street": "Neuweg 1",
                "postal_code": "54321",
                "city": "B-Stadt",
            },
            content_type=JSON,
        )

    def test_anfrage_sichtbar_fuer_beide(self, api, orgs, request_b, board_a, board_b, board_c):
        assert request_b.status_code == 201, request_b.json()
        incoming = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/transfers/").json()
        assert incoming[0]["direction"] == "incoming"
        assert incoming[0]["to_org_name"] == "Verein B"
        outgoing = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/transfers/").json()
        assert outgoing[0]["direction"] == "outgoing"
        assert api(board_c).get(f"/api/orgs/{orgs['c'].pk}/transfers/").json() == []

    def test_austritt_bestaetigen_und_aktiv_aufnehmen(self, api, orgs, request_b, board_a):
        tid = request_b.json()["id"]
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/transfers/{tid}/decide/",
            {"decision": "exit"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "accepted"
        old = Membership.objects.get(organization=orgs["a"])
        period = old.periods.get()
        assert period.exit_date == datetime.date(2024, 6, 30)
        assert period.exit_reason == "transfer"
        new = Membership.objects.get(organization=orgs["b"])
        assert new.current_type(datetime.date(2024, 7, 1)).member_type.active
        assert new.person == old.person
        # Kontaktdaten aus der Anfrage übernommen (gemeinsam gepflegt)
        assert ContactDetails.objects.get(person=new.person).city == "B-Stadt"

    def test_wechsel_zu_passiv_bestaetigen(self, api, orgs, types, request_b, board_a):
        tid = request_b.json()["id"]
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/transfers/{tid}/decide/",
            {"decision": "change_type", "member_type": types["a"]["passiv"].pk},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        old = Membership.objects.get(organization=orgs["a"])
        assert old.current_period(datetime.date(2024, 7, 1)) is not None  # bleibt Mitglied
        assert old.current_type(datetime.date(2024, 7, 1)).member_type.name == "passiv"
        assert Membership.objects.filter(organization=orgs["b"]).exists()

    def test_ablehnen(self, api, orgs, request_b, board_a):
        tid = request_b.json()["id"]
        api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/transfers/{tid}/decide/",
            {"decision": "reject", "response": "Beitrag offen"},
            content_type=JSON,
        )
        t = TransferRequest.objects.get()
        assert t.status == "rejected" and t.response == "Beitrag offen"
        assert not Membership.objects.filter(organization=orgs["b"]).exists()

    def test_nur_alter_verein_entscheidet(self, api, orgs, request_b, board_b):
        tid = request_b.json()["id"]
        resp = api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/transfers/{tid}/decide/",
            {"decision": "exit"},
            content_type=JSON,
        )
        assert resp.status_code == 404

    def test_zurueckziehen(self, api, orgs, request_b, board_b):
        tid = request_b.json()["id"]
        resp = api(board_b).post(f"/api/orgs/{orgs['b'].pk}/transfers/{tid}/cancel/")
        assert resp.json()["status"] == "cancelled"

    def test_unnoetige_anfrage(self, api, orgs, types, member, board_a, board_b):
        api(board_a).post(
            url(orgs, member, "exit/"),
            {"exit_date": "2023-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        resp = api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/transfers/",
            {
                "person": member["person_id"],
                "member_type": types["b"]["aktiv"].pk,
                "entry_date": "2024-07-01",
                "email": "e@example.org",
                "street": "x",
                "postal_code": "1",
                "city": "y",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400


class TestLoeschfrist:
    def test_nach_frist_nur_minimum(self, api, orgs, types, member, board_a):
        c = api(board_a)
        c.patch(
            url(orgs, member, ""), {"club_number": "4711", "city": "Neustadt"}, content_type=JSON
        )
        c.post(
            url(orgs, member, "exit/"),
            {"exit_date": "2020-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert purge_expired(datetime.date(2022, 12, 31)) == 0  # Frist (24 Monate) noch nicht um
        assert purge_expired(datetime.date(2023, 1, 1)) == 1
        membership = Membership.objects.get(organization=orgs["a"])
        assert membership.purged_at is not None
        assert membership.club_number == ""
        assert not ContactDetails.objects.exists()
        assert membership.periods.count() == 1  # Zeiträume bleiben
        person = membership.person
        assert (person.last_name, person.first_name) == ("Muster", "Erika")
        # Gesamtaudit 31.10.b, Frage 6: nur das Geburtsjahr, keine Verbandsnummer mehr
        person.refresh_from_db()
        assert person.birth_year_only and (person.birth_date.month, person.birth_date.day) == (1, 1)
        assert not FederationMember.objects.filter(person=person).exists()
        assert all(e.changes == {} for e in AuditEntry.objects.filter(person_id=person.pk))
        data = c.get(url(orgs, member, "")).json()
        assert data["purged"] is True
        assert data["contact"] is None

    def test_gemeinsame_daten_bleiben_wenn_noch_mitglied(
        self, api, orgs, types, member, board_a, board_b
    ):
        api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/members/admit/",
            {
                "person": member["person_id"],
                "member_type": types["b"]["passiv"].pk,
                "entry_date": "2020-01-01",
                "email": "e@example.org",
                "street": "x",
                "postal_code": "1",
                "city": "y",
            },
            content_type=JSON,
        )
        api(board_a).post(
            url(orgs, member, "exit/"),
            {"exit_date": "2020-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert purge_expired(datetime.date(2024, 1, 1)) == 1
        assert ContactDetails.objects.count() == 1  # B braucht die Daten noch
        person = Membership.objects.get(organization=orgs["a"]).person
        person.refresh_from_db()
        assert not person.birth_year_only  # noch Mitglied in B: Geburtsdatum bleibt

    def test_frist_einstellbar(self, api, orgs, member, board_a):
        settings = PlatformSettings.load()
        settings.deletion_period_months = 6
        settings.save()
        api(board_a).post(
            url(orgs, member, "exit/"),
            {"exit_date": "2023-01-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert purge_expired(datetime.date(2023, 8, 1)) == 1

    def test_wiedereintritt_nach_loeschung(self, api, orgs, types, member, board_a):
        c = api(board_a)
        c.post(
            url(orgs, member, "exit/"),
            {"exit_date": "2015-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        purge_expired(datetime.date(2020, 1, 1))
        without = c.post(
            url(orgs, member, "reentry/"),
            {"entry_date": "2024-01-01", "member_type": types["a"]["aktiv"].pk},
            content_type=JSON,
        )
        assert without.status_code == 400  # Kontaktdaten fehlen
        resp = c.post(
            url(orgs, member, "reentry/"),
            {
                "entry_date": "2024-01-01",
                "member_type": types["a"]["aktiv"].pk,
                "email": "erika@example.org",
                "street": "Neu 1",
                "postal_code": "1",
                "city": "x",
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["purged"] is False

    def test_job_ueber_celery(self, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        from members.tasks import purge_expired_members

        assert purge_expired_members.delay().get() == 0


def test_mitgliedsart_nicht_aus_anderem_verein(api, orgs, types, member, board_a):
    resp = api(board_a).post(
        url(orgs, member, "change-type/"),
        {"member_type": types["b"]["passiv"].pk, "valid_from": "2020-01-01"},
        content_type=JSON,
    )
    assert resp.status_code == 400


def test_fremder_verein_kann_nicht_austreten_lassen(api, orgs, member, board_b):
    resp = api(board_b).post(
        f"/api/orgs/{orgs['b'].pk}/members/{member['id']}/exit/",
        {"exit_date": "2023-12-31", "exit_reason": "exit"},
        content_type=JSON,
    )
    assert resp.status_code == 404
    assert MemberType.objects.exists()
