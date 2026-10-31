# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 4: namentliche Meldung, Verbandsnummer, Klärfälle, Abfrage (erfundene Daten)."""

import datetime

import pytest
from rest_framework.exceptions import ValidationError

from billing import services as billing
from billing.models import BillingSettings
from core.tenancy import tenant_context
from members import workflows
from members.models import ContactDetails, FederationMember, Membership, MemberType
from members.serializers import member_detail
from peering import services
from peering.models import RemoteMember

from .factories import make_member, make_org
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .verbund_netz import release

pytestmark = pytest.mark.django_db
JSON = "application/json"
ANNA = datetime.date(1980, 5, 17)


@pytest.fixture
def members(net, world):
    club = world["club"]
    with net.on(VEREIN):
        with tenant_context(club.pk):
            passiv = MemberType.objects.create(organization=club, name="passiv", active=False)
            intern = MemberType.objects.create(organization=club, name="intern", reported=False)
        result = {
            "anna": make_member(club, "Anna", "Aktiv", birth_date=ANNA),
            "bert": make_member(club, "Bert", "Aktiv", birth_date=datetime.date(2012, 3, 2)),
            "paul": make_member(club, "Paul", "Passiv", member_type=passiv),
            "ingo": make_member(club, "Ingo", "Intern", member_type=intern),
        }
    return result


def named(net, world, level="b"):
    lower, upper = couple(net, world)
    with net.on(VEREIN):
        release(lower, {"unit": "on", "events": "on", "members": level})
    lower.refresh_from_db()
    upper.refresh_from_db()
    return lower, upper


def sync(net, lower):
    with net.on(VEREIN):
        services.sync(lower)


def register_of(upper):
    with tenant_context(upper.remote_unit.pk):
        return {
            f"{m.person.first_name} {m.person.last_name}": m
            for m in Membership.objects.filter(organization=upper.remote_unit).select_related(
                "person"
            )
        }


class TestNamentlicheMeldung:
    def test_minimum_und_verbandsnummer(self, net, world, members):
        lower, upper = named(net, world)
        reg = register_of(upper)
        assert sorted(reg) == ["Anna Aktiv", "Bert Aktiv", "Paul Passiv"]  # „intern“ nicht
        anna = reg["Anna Aktiv"]
        assert anna.person.birth_date == ANNA
        assert anna.person.scope_id == world["fed"].pk
        # Keine Kontaktdaten, nur Zeiträume und Art
        assert not ContactDetails.objects.filter(person=anna.person).exists()
        assert anna.current_type().member_type.active
        number = FederationMember.objects.get(person=anna.person).member_number
        # Die Nummer kommt beim Verein an und steht in der Mitgliedsakte
        rm = RemoteMember.objects.get(coupling=lower, uid=f"m{members['anna'].pk}")
        assert rm.number == number
        with tenant_context(world["club"].pk):
            detail = member_detail(members["anna"], world["club"])
        assert detail["federation"]["member_number"] == number
        assert detail["federation"]["name"] == "Bürgerbund Musterstadt"

    def test_berichtigung_austritt_und_loeschung(self, net, world, members):
        lower, upper = named(net, world)
        person = members["anna"].person
        person.last_name = "Aktiv-Neu"
        person.save()
        with tenant_context(world["club"].pk):
            workflows.exit_membership(members["bert"], datetime.date(2026, 6, 30), "exit")
        sync(net, lower)
        reg = register_of(upper)
        assert "Anna Aktiv-Neu" in reg
        bert = reg["Bert Aktiv"]
        assert bert.periods.get().exit_date == datetime.date(2026, 6, 30)
        # Löschfrist beim Verein: oben bleibt nur das Minimum
        with tenant_context(world["club"].pk):
            workflows.purge_membership(Membership.objects.get(pk=members["bert"].pk))
        sync(net, lower)
        bert.refresh_from_db()
        assert bert.purged_at is not None
        assert bert.periods.exists()

    def test_freigabe_entzogen_kuerzt_auf_minimum(self, net, world, members):
        lower, upper = named(net, world)
        with net.on(VEREIN):
            release(lower, {"unit": "on", "members": "a"})
        statuses = set(RemoteMember.objects.filter(coupling=upper).values_list("status", flat=True))
        assert statuses == {"withdrawn"}
        anna = register_of(upper)["Anna Aktiv"]
        assert anna.purged_at is not None
        assert anna.periods.get().exit_date is not None
        assert FederationMember.objects.filter(person=anna.person).exists()

    def test_beitragsrechnung_aus_der_namentlichen_meldung(self, net, world, members):
        from decimal import Decimal

        fed = world["fed"]
        lower, upper = named(net, world)
        with tenant_context(fed.pk):
            BillingSettings.objects.create(
                organization=fed, club_rate_active=Decimal("10"), club_rate_passive=Decimal("4")
            )
            items = billing.plan_federation_run(fed, billing.period(fed, 2026, "yearly", 1))
        item = next(i for i in items if i.club == upper.remote_unit)
        assert item.members == 3 and item.total == Decimal("24.00")


class TestKlaerfaelle:
    def local_anna(self, net, world):
        with net.on(VERBAND):
            nachbar = make_org("Nachbarverein Musterstadt", parent=world["fed"])
            return make_member(nachbar, "Anna", "Aktiv", birth_date=ANNA)

    def test_gleiche_person_zusammenfuehren(self, net, world, members):
        local = self.local_anna(net, world)
        lower, upper = named(net, world)
        rm = RemoteMember.objects.get(coupling=upper, uid=f"m{members['anna'].pk}")
        assert rm.status == "unclear" and rm.membership is None
        with net.on(VERBAND):
            c = api(world["fed_board"])
            base = f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}"
            data = c.get(f"{base}/").json()
            case = data["register"]["unclear"][0]
            assert case["candidates"][0]["units"] == ["Nachbarverein Musterstadt"]
            resp = c.post(
                f"{base}/members/{rm.pk}/resolve/",
                {"person": case["candidates"][0]["id"]},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        rm.refresh_from_db()
        assert rm.membership.person_id == local.person_id
        # Doppelt aktiv: als Hinweis für den Dachverband
        assert rm.data["active_elsewhere"] == "Nachbarverein Musterstadt"
        assert resp.json()["register"]["conflicts"][0]["active_elsewhere"] == (
            "Nachbarverein Musterstadt"
        )
        # Die vorhandene Verbandsnummer gilt jetzt auch beim Verein
        number = FederationMember.objects.get(person_id=local.person_id).member_number
        assert RemoteMember.objects.get(coupling=lower, uid=rm.uid).number == number

    def test_nur_verbundrecht_ohne_namen(self, net, world, members):
        # Gesamtaudit 30.10.a (BSEC-V02): Namen nur mit „Mitglieder ansehen“
        from access.catalog import MEMBERS_VIEW, PEERING_MANAGE

        from .factories import give_role, make_user

        self.local_anna(net, world)
        lower, upper = named(net, world)
        rm = RemoteMember.objects.get(coupling=upper, uid=f"m{members['anna'].pk}")
        fed = world["fed"]
        base = f"/api/orgs/{fed.pk}/peering/couplings/{upper.pk}"
        with net.on(VERBAND):
            nur = make_user("verbund@verband.example")
            give_role(nur, fed, [PEERING_MANAGE], name="Verbundpflege")
            data = api(nur).get(f"{base}/").json()
            assert data["register"]["unclear"] == [] and data["register"]["counts"]["unclear"]
            assert "names" in data["hidden"]
            resp = api(nur).post(f"{base}/members/{rm.pk}/resolve/", {}, content_type=JSON)
            assert resp.status_code == 403
            # mit „Mitglieder ansehen“ sichtbar, Entscheiden bleibt beim Bearbeiten-Recht
            lesen = make_user("lesen@verband.example")
            give_role(lesen, fed, [PEERING_MANAGE, MEMBERS_VIEW], name="Verbund lesen")
            data = api(lesen).get(f"{base}/").json()
            assert len(data["register"]["unclear"]) == 1 and "names" not in data["hidden"]
            resp = api(lesen).post(f"{base}/members/{rm.pk}/resolve/", {}, content_type=JSON)
            assert resp.status_code == 403

    def test_andere_person(self, net, world, members):
        local = self.local_anna(net, world)
        lower, upper = named(net, world)
        rm = RemoteMember.objects.get(coupling=upper, uid=f"m{members['anna'].pk}")
        with net.on(VERBAND):
            resp = api(world["fed_board"]).post(
                f"/api/orgs/{world['fed'].pk}/peering/couplings/{upper.pk}/members/{rm.pk}/resolve/",
                {"person": None},
                content_type=JSON,
            )
        assert resp.status_code == 200
        rm.refresh_from_db()
        assert rm.membership.person_id != local.person_id


class TestAbfrageAktiv:
    def test_aufnahme_prueft_beim_fernen_dachverband(self, net, world, members):
        with net.on(VERBAND):
            nachbar = make_org("Nachbarverein Musterstadt", parent=world["fed"])
            make_member(nachbar, "Gerd", "Gewechselt", birth_date=datetime.date(1975, 1, 1))
        named(net, world)
        with net.on(VEREIN):
            with pytest.raises(ValidationError) as exc:
                make_member(
                    world["club"], "Gerd", "Gewechselt", birth_date=datetime.date(1975, 1, 1)
                )
        assert "Nachbarverein Musterstadt" in str(exc.value)

    def test_ohne_verbindung_keine_sperre(self, net, world, members):
        with net.on(VERBAND):
            nachbar = make_org("Nachbarverein Musterstadt", parent=world["fed"])
            make_member(nachbar, "Gerd", "Gewechselt", birth_date=datetime.date(1975, 1, 1))
        named(net, world)
        net.down.add(VERBAND)
        with net.on(VEREIN):
            make_member(world["club"], "Gerd", "Gewechselt", birth_date=datetime.date(1975, 1, 1))

    def test_stufe_a_fragt_nicht(self, net, world, members):
        named(net, world, level="a")
        calls = len(net.calls)
        with net.on(VEREIN):
            make_member(world["club"], "Neu", "Mitglied", birth_date=datetime.date(1990, 1, 1))
        assert not any(path.endswith("/query/") for _, path in net.calls[calls:])
