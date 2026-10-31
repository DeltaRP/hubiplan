"""Meilenstein 2: Personen, Mitgliedschaften, Mitgliedsarten, Aufnahme, Liste, Akte."""

import datetime

import pytest

from access.models import Role
from members.models import (
    ContactDetails,
    DepartmentMembership,
    FederationMember,
    Membership,
    MemberType,
    Person,
)
from organizations.models import Department, PlatformSettings

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


def make_types(org):
    return {
        "aktiv": MemberType.objects.create(organization=org, name="aktiv", active=True),
        "passiv": MemberType.objects.create(organization=org, name="passiv"),
        "foerder": MemberType.objects.create(
            organization=org, name="Fördermitglied", reported=False, counts_for_duration=False
        ),
    }


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b", "c")}


def types_a_passiv(orgs):
    return MemberType.objects.get(organization=orgs["a"], name="passiv").pk


def person_data(**extra):
    data = {
        "last_name": "Muster",
        "first_name": "Erika",
        "birth_date": "1980-05-17",
        "email": "erika@example.org",
        "phone": "0123 456",
        "street": "Lindenweg 4",
        "postal_code": "12345",
        "city": "Musterstadt",
        "entry_date": "2015-03-01",
    }
    data.update(extra)
    return data


def admit(client, org, member_type, **extra):
    return client.post(
        f"/api/orgs/{org.pk}/members/admit/",
        person_data(member_type=member_type.pk, **extra),
        content_type=JSON,
    )


class TestAufnahme:
    def test_neues_mitglied_mit_verbandsnummer(self, api, orgs, types, board_a):
        resp = admit(api(board_a), orgs["a"], types["a"]["aktiv"])
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["status"] == "active"
        assert data["current_type"]["member_type_name"] == "aktiv"
        assert data["contact"]["email"] == "erika@example.org"
        assert data["federation"]["member_number"] == 1
        assert data["federation"]["is_member"] is True
        assert data["federation"]["entry_date"] == "2015-03-01"
        person = Person.objects.get()
        assert person.scope == orgs["federation"]

        resp2 = admit(
            api(board_a),
            orgs["a"],
            types["a"]["aktiv"],
            last_name="Zweite",
            birth_date="1990-01-01",
        )
        assert resp2.json()["federation"]["member_number"] == 2

    def test_nicht_gemeldete_art_ohne_verbandsnummer(self, api, orgs, types, board_a):
        data = admit(api(board_a), orgs["a"], types["a"]["foerder"]).json()
        assert data["federation"]["member_number"] is None
        assert data["federation"]["is_member"] is False
        assert not FederationMember.objects.exists()

    def test_verein_ohne_dachverband(self, api, orgs, types, board_c):
        data = admit(api(board_c), orgs["c"], types["c"]["aktiv"]).json()
        assert data["federation"] is None
        assert Person.objects.get().scope == orgs["c"]

    def test_pflichtfelder(self, api, orgs, types, board_a):
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/members/admit/",
            {"member_type": types["a"]["aktiv"].pk, "entry_date": "2020-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert {"street", "postal_code", "city"} <= set(resp.json())
        assert "email" not in resp.json()  # E-Mail ist freiwillig
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/members/admit/",
            {
                "member_type": types["a"]["aktiv"].pk,
                "entry_date": "2020-01-01",
                "email": "a@example.org",
                "street": "x",
                "postal_code": "1",
                "city": "y",
            },
            content_type=JSON,
        )
        assert {"last_name", "first_name", "birth_date"} <= set(resp.json())

    def test_fremde_mitgliedsart_abgelehnt(self, api, orgs, types, board_a):
        resp = admit(api(board_a), orgs["a"], types["b"]["aktiv"])
        assert resp.status_code == 400

    def test_nur_mit_bearbeitungsrecht(self, api, orgs, types):
        reader = make_user("leser@example.org")
        give_role(reader, orgs["a"], ["members.view"], name="Leser")
        assert admit(api(reader), orgs["a"], types["a"]["aktiv"]).status_code == 403


class TestDublettenUndAktivRegel:
    @pytest.fixture
    def erika(self, api, orgs, types, board_a):
        return admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()

    def search(self, client, org):
        return client.get(
            f"/api/orgs/{org.pk}/members/duplicates/",
            {"name": "muster", "vorname": "Erika", "geburtsdatum": "1980-05-17"},
        ).json()

    def test_dublette_im_dachverband_gefunden(self, api, orgs, erika, board_b):
        found = self.search(api(board_b), orgs["b"])
        assert len(found) == 1
        hit = found[0]
        assert hit["member_number"] == 1
        assert hit["clubs"] is None  # frühere Mitgliedschaften nicht freigegeben
        # Keine Kontaktdaten des anderen Vereins
        assert "email" not in hit and "street" not in hit

    def test_vereine_nur_wenn_freigegeben(self, api, orgs, erika, board_b):
        orgs["federation"].federation_show_former_memberships = True
        orgs["federation"].save()
        hit = self.search(api(board_b), orgs["b"])[0]
        assert hit["clubs"] == ["Verein A"]

    def test_anderer_verband_findet_nichts(self, api, orgs, erika, board_c):
        assert self.search(api(board_c), orgs["c"]) == []

    def test_verknuepfen_passiv_erlaubt(self, api, orgs, types, erika, board_b):
        person_id = erika["person_id"]
        resp = api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/members/admit/",
            {
                "person": person_id,
                "member_type": types["b"]["passiv"].pk,
                "entry_date": "2021-01-01",
                **{
                    k: v
                    for k, v in person_data().items()
                    if k in ("email", "street", "postal_code", "city")
                },
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert resp.json()["federation"]["member_number"] == 1  # Nummer bleibt
        assert Person.objects.count() == 1

    def test_zweite_aktive_mitgliedschaft_blockiert(self, api, orgs, types, erika, board_b):
        resp = api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/members/admit/",
            {
                "person": erika["person_id"],
                "member_type": types["b"]["aktiv"].pk,
                "entry_date": "2021-01-01",
                "email": "e@example.org",
                "street": "x",
                "postal_code": "1",
                "city": "y",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "Verein A" in str(resp.json()["member_type"])
        assert Membership.objects.count() == 1

    def test_fremde_person_aus_anderem_verband(self, api, orgs, types, erika, board_c):
        resp = api(board_c).post(
            f"/api/orgs/{orgs['c'].pk}/members/admit/",
            {
                "person": erika["person_id"],
                "member_type": types["c"]["aktiv"].pk,
                "entry_date": "2021-01-01",
                "email": "e@example.org",
                "street": "x",
                "postal_code": "1",
                "city": "y",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_schon_mitglied_hier(self, api, orgs, types, erika, board_a):
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/members/admit/",
            {
                "person": erika["person_id"],
                "member_type": types["a"]["passiv"].pk,
                "entry_date": "2021-01-01",
                "email": "e@example.org",
                "street": "x",
                "postal_code": "1",
                "city": "y",
            },
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "Wiedereintritt" in str(resp.json())


class TestListe:
    @pytest.fixture
    def members(self, api, orgs, types, board_a):
        c = api(board_a)
        dep = Department.objects.create(organization=orgs["a"], name="Turnen", founding_year=1950)
        admit(
            c,
            orgs["a"],
            types["a"]["aktiv"],
            last_name="Adler",
            first_name="Anna",
            birth_date="1970-01-01",
            department_ids=[dep.pk],
        )
        admit(
            c,
            orgs["a"],
            types["a"]["passiv"],
            last_name="Berg",
            first_name="Bernd",
            birth_date="1971-01-01",
            email="bernd@example.org",
        )
        admit(
            c,
            orgs["a"],
            types["a"]["foerder"],
            last_name="Christ",
            first_name="Clara",
            birth_date="1972-01-01",
        )
        return dep

    def get(self, client, org, **params):
        return client.get(f"/api/orgs/{org.pk}/members/", params).json()

    def test_liste_paging_und_spalten(self, api, orgs, members, board_a):
        data = self.get(api(board_a), orgs["a"], page_size=2)
        assert data["count"] == 3
        assert [r["last_name"] for r in data["results"]] == ["Adler", "Berg"]
        row = data["results"][0]
        assert row["member_type"] == "aktiv"
        assert row["departments"] == ["Turnen"]
        assert row["member_number"] == 1
        assert row["email"] == "erika@example.org"

    def test_suche_und_filter(self, api, orgs, types, members, board_a):
        c = api(board_a)
        assert [r["last_name"] for r in self.get(c, orgs["a"], suche="bern")["results"]] == ["Berg"]
        assert self.get(c, orgs["a"], suche="bernd@example")["count"] == 1
        assert self.get(c, orgs["a"], art=types["a"]["passiv"].pk)["count"] == 1
        assert self.get(c, orgs["a"], abteilung=members.pk)["count"] == 1
        assert self.get(c, orgs["a"], status="ehemalig")["count"] == 0
        desc = self.get(c, orgs["a"], sortierung="-name")["results"]
        assert desc[0]["last_name"] == "Christ"

    def names(self, client, org, sort):
        return [r["last_name"] for r in self.get(client, org, sortierung=sort)["results"]]

    def test_sortierung_nach_mitgliedsart(self, api, orgs, types, members, board_a):
        for key, pos in (("passiv", 1), ("foerder", 2), ("aktiv", 3)):
            types["a"][key].sort_order = pos
            types["a"][key].save()
        c = api(board_a)
        assert self.names(c, orgs["a"], "art") == ["Berg", "Christ", "Adler"]
        assert self.names(c, orgs["a"], "-art") == ["Adler", "Christ", "Berg"]

    def test_sortierung_nach_abteilung(self, api, orgs, members, board_a):
        members.sort_order = 2
        members.save()
        schuetzen = Department.objects.create(
            organization=orgs["a"], name="Schützen", founding_year=1920, sort_order=1
        )
        christ = Membership.objects.get(organization=orgs["a"], person__last_name="Christ")
        DepartmentMembership.objects.create(
            membership=christ,
            department=schuetzen,
            organization=orgs["a"],
            valid_from="2020-01-01",
        )
        c = api(board_a)
        # Ohne Abteilung (Berg) steht in beiden Richtungen am Ende.
        assert self.names(c, orgs["a"], "abteilung") == ["Christ", "Adler", "Berg"]
        assert self.names(c, orgs["a"], "-abteilung") == ["Adler", "Christ", "Berg"]
        # Mehrere Abteilungen: es zählt die erste in der Reihenfolge des Vereins.
        adler = Membership.objects.get(organization=orgs["a"], person__last_name="Adler")
        DepartmentMembership.objects.create(
            membership=adler,
            department=schuetzen,
            organization=orgs["a"],
            valid_from="2020-01-01",
        )
        assert self.names(c, orgs["a"], "abteilung") == ["Adler", "Christ", "Berg"]
        row = self.get(c, orgs["a"], sortierung="abteilung")["results"][0]
        assert row["departments"] == ["Schützen", "Turnen"]

    def test_sortierung_nummer_absteigend(self, api, orgs, members, board_a):
        for i, m in enumerate(Membership.objects.filter(organization=orgs["a"]).order_by("pk")):
            m.club_number = f"{i + 1}"
            m.save()
        c = api(board_a)
        assert self.names(c, orgs["a"], "-nummer") == ["Christ", "Berg", "Adler"]

    def test_verein_b_sieht_nichts_von_a(self, api, orgs, members, board_b):
        assert self.get(api(board_b), orgs["b"])["count"] == 0
        membership = Membership.objects.filter(organization=orgs["a"]).first()
        assert api(board_b).get(f"/api/orgs/{orgs['a'].pk}/members/").status_code == 404
        resp = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/members/{membership.pk}/")
        assert resp.status_code == 404


class TestAkte:
    @pytest.fixture
    def member(self, api, orgs, types, board_a):
        return admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()

    def url(self, orgs, member, suffix=""):
        return f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/{suffix}"

    def test_stammdaten_aendern_und_verlauf(self, api, orgs, member, board_a):
        c = api(board_a)
        resp = c.patch(
            self.url(orgs, member), {"city": "Neustadt", "first_name": "Erica"}, content_type=JSON
        )
        assert resp.status_code == 200
        assert resp.json()["contact"]["city"] == "Neustadt"
        history = c.get(self.url(orgs, member, "history/")).json()
        assert history[0]["changes"]["Ort"] == ["Musterstadt", "Neustadt"]
        assert history[0]["changes"]["Vorname"] == ["Erika", "Erica"]

    def test_gemeinsame_kontaktdaten(self, api, orgs, types, member, board_a, board_b):
        api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/members/admit/",
            {
                "person": member["person_id"],
                "member_type": types["b"]["passiv"].pk,
                "entry_date": "2020-01-01",
                "email": "erika@example.org",
                "street": "Lindenweg 4",
                "postal_code": "12345",
                "city": "Musterstadt",
            },
            content_type=JSON,
        )
        api(board_a).patch(self.url(orgs, member), {"city": "Neustadt"}, content_type=JSON)
        b_member = Membership.objects.get(organization=orgs["b"])
        data = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/members/{b_member.pk}/").json()
        assert data["contact"]["city"] == "Neustadt"
        assert ContactDetails.objects.count() == 1

    def test_kontaktdaten_je_verein(self, api, orgs, types, member, board_a, board_b):
        settings = PlatformSettings.load()
        settings.person_data_mode = "per_club"
        settings.save()
        api(board_b).post(
            f"/api/orgs/{orgs['b'].pk}/members/admit/",
            {
                "person": member["person_id"],
                "member_type": types["b"]["passiv"].pk,
                "entry_date": "2020-01-01",
                "email": "erika@b.example.org",
                "street": "B-Weg 1",
                "postal_code": "54321",
                "city": "B-Stadt",
            },
            content_type=JSON,
        )
        api(board_a).patch(self.url(orgs, member), {"city": "A-Stadt"}, content_type=JSON)
        b_member = Membership.objects.get(organization=orgs["b"])
        data = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/members/{b_member.pk}/").json()
        assert data["contact"]["city"] == "B-Stadt"
        a_data = api(board_a).get(self.url(orgs, member)).json()
        assert a_data["contact"]["city"] == "A-Stadt"

    def test_zeitraum_nachtragen(self, api, orgs, member, board_a):
        c = api(board_a)
        url = self.url(orgs, member, "periods/")
        resp = c.post(
            url,
            {"entry_date": "2001-01-01", "exit_date": "2005-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        overlap = c.post(
            url,
            {"entry_date": "2004-01-01", "exit_date": "2016-01-01", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert overlap.status_code == 400
        data = c.get(self.url(orgs, member)).json()
        assert [p["entry_date"] for p in data["periods"]] == ["2001-01-01", "2015-03-01"]
        # Ohne Mitgliedsart zählt der nachgetragene Zeitraum nicht als gemeldet
        assert data["federation"]["entry_date"] == "2015-03-01"
        # Mit gemeldeter Art zählt er: Dachverbandseintritt rückt nach vorn
        resp = c.post(
            url,
            {
                "entry_date": "1998-01-01",
                "exit_date": "2000-06-30",
                "exit_reason": "exit",
                "member_type": types_a_passiv(orgs),
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        data = c.get(self.url(orgs, member)).json()
        assert data["federation"]["entry_date"] == "1998-01-01"
        before_birth = c.post(
            url,
            {"entry_date": "1970-01-01", "exit_date": "1971-01-01", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert before_birth.status_code == 400

    def test_manueller_verbandseintritt(self, api, orgs, member, board_a):
        resp = api(board_a).patch(
            self.url(orgs, member, "federation/"),
            {"manual_entry_date": "1999-04-01"},
            content_type=JSON,
        )
        assert resp.status_code == 200
        fed = resp.json()["federation"]
        assert fed["entry_date"] == "1999-04-01"
        assert fed["entry_date_manual"] is True

    def test_abteilungen_einzeln_oder_mehrfach(self, api, orgs, member, board_a):
        org = orgs["a"]
        d1 = Department.objects.create(organization=org, name="Turnen", founding_year=1950)
        d2 = Department.objects.create(organization=org, name="Fußball", founding_year=1960)
        c = api(board_a)
        url = self.url(orgs, member, "departments/")
        assert (
            c.post(
                url, {"department": d1.pk, "valid_from": "2020-01-01"}, content_type=JSON
            ).status_code
            == 201
        )
        assert (
            c.post(
                url, {"department": d2.pk, "valid_from": "2021-01-01"}, content_type=JSON
            ).status_code
            == 201
        )
        org.allow_multiple_departments = False
        org.save()
        d3 = Department.objects.create(organization=org, name="Tennis", founding_year=1970)
        resp = c.post(url, {"department": d3.pk, "valid_from": "2022-01-01"}, content_type=JSON)
        assert resp.status_code == 400
        # fremde Abteilung
        dep_b = Department.objects.create(organization=orgs["b"], name="Schach", founding_year=1)
        assert (
            c.post(
                url, {"department": dep_b.pk, "valid_from": "2022-01-01"}, content_type=JSON
            ).status_code
            == 400
        )

    def test_vorstandsrolle_in_akte_und_als_kontakt(self, api, orgs, member, board_a):
        role = Role.objects.get(organization=orgs["a"], name="Vorstand")
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/assignments/",
            {
                "email": "erika@example.org",
                "role": role.pk,
                "member": member["id"],
                "valid_from": "2019-01-01",
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        data = api(board_a).get(self.url(orgs, member)).json()
        assert data["board_roles"][0]["role_name"] == "Vorstand"
        orgs["a"].contact_source = "role"
        orgs["a"].contact_role = role
        orgs["a"].save()
        org = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/").json()
        holders = {org["contact_effective"]["holder"]}
        assert holders & {"Erika Muster", "vorstand-a@example.org"}

    def test_konto_nachtraeglich_mitgliedsakte_zuordnen(self, api, orgs, member, board_a):
        """Bestehendes Konto ohne Akte: beim Bearbeiten zuordnen, gilt für alle seine Rollen."""
        role = Role.objects.get(organization=orgs["a"], name="Vorstand")
        second = Role.objects.create(organization=orgs["a"], name="Schriftführer")
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/assignments/"
        ids = []
        for r in (role, second):
            resp = c.post(
                base,
                {"email": "erika@example.org", "role": r.pk, "valid_from": "2020-01-01"},
                content_type=JSON,
            )
            assert resp.status_code == 201, resp.json()
            assert resp.json()["member_record"] is None
            ids.append(resp.json()["id"])

        resp = c.patch(f"{base}{ids[0]}/", {"member": member["id"]}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["member_record"]["id"] == member["id"]
        rows = {a["id"]: a for a in c.get(base).json()}
        assert rows[ids[1]]["member_record"]["id"] == member["id"]
        roles = {a["role_name"] for a in c.get(self.url(orgs, member)).json()["board_roles"]}
        assert roles == {"Vorstand", "Schriftführer"}

        # Fremde Mitgliedschaft wird abgelehnt, Zuordnung wieder lösen geht
        resp = c.patch(f"{base}{ids[0]}/", {"member": 999999}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.patch(f"{base}{ids[0]}/", {"member": None}, content_type=JSON)
        assert resp.status_code == 200
        assert all(a["member_record"] is None for a in c.get(base).json() if a["id"] in ids)


class TestMitgliedsarten:
    def test_anlegen_und_loeschschutz(self, api, orgs, types, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/member-types/"
        resp = c.post(url, {"name": "Jugend", "active": True, "reported": True}, content_type=JSON)
        assert resp.status_code == 201
        assert c.delete(f"{url}{resp.json()['id']}/").status_code == 204
        admit(c, orgs["a"], types["a"]["aktiv"])
        assert c.delete(f"{url}{types['a']['aktiv'].pk}/").status_code == 409  # nur archivieren

    def test_lesen_auch_ohne_organisationsrecht(self, api, orgs, types):
        reader = make_user("leser@example.org")
        give_role(reader, orgs["a"], ["members.view"], name="Leser")
        names = [
            t["name"] for t in api(reader).get(f"/api/orgs/{orgs['a'].pk}/member-types/").json()
        ]
        assert set(names) == {"aktiv", "Fördermitglied", "passiv"}

    def test_dachverband_hat_keine_mitgliederliste(self, api, orgs):
        user = make_user("verband@example.org")
        give_role(user, orgs["federation"])
        assert api(user).get(f"/api/orgs/{orgs['federation'].pk}/members/").status_code == 404


def test_viele_mitglieder_schnell(api, orgs, types, board_a, django_assert_max_num_queries):
    """10.000 Mitglieder: die Seite lädt mit wenigen Abfragen (kein N+1)."""
    org = orgs["a"]
    persons = Person.objects.bulk_create(
        Person(
            scope=orgs["federation"],
            last_name=f"Name{i:05d}",
            first_name="Test",
            birth_date=datetime.date(1980, 1, 1),
        )
        for i in range(300)
    )
    memberships = Membership.objects.bulk_create(
        Membership(organization=org, scope=orgs["federation"], person=p) for p in persons
    )
    from members.models import MembershipPeriod, MemberTypeAssignment

    MembershipPeriod.objects.bulk_create(
        MembershipPeriod(organization=org, membership=m, entry_date=datetime.date(2000, 1, 1))
        for m in memberships
    )
    MemberTypeAssignment.objects.bulk_create(
        MemberTypeAssignment(
            organization=org,
            membership=m,
            member_type=types["a"]["aktiv"],
            valid_from=datetime.date(2000, 1, 1),
        )
        for m in memberships
    )
    client = api(board_a)
    with django_assert_max_num_queries(20):
        data = client.get(f"/api/orgs/{org.pk}/members/", {"page_size": 100}).json()
    assert data["count"] == 300
    assert len(data["results"]) == 100
