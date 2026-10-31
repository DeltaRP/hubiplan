# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 4b: Wechsel über Instanzen und Korrekturvorschläge (erfundene Daten)."""

import datetime

import pytest

from core.tenancy import tenant_context
from members import workflows
from members.models import Membership, MemberType, TransferRequest
from peering import services
from peering.models import RemoteMember, RemoteTransfer
from portal.models import ChangeRequest

from .factories import give_role, make_member, make_org, make_user
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .verbund_netz import release

pytestmark = pytest.mark.django_db
JSON = "application/json"
ANNA = datetime.date(1980, 5, 17)
GERD = datetime.date(1975, 1, 1)
ENTRY = datetime.date(2026, 11, 1)


@pytest.fixture
def setup(net, world):
    """Verein „verein.example“ (fern) mit Anna; Nachbarverein beim Dachverband mit Gerd."""
    club, fed = world["club"], world["fed"]
    with net.on(VEREIN):
        with tenant_context(club.pk):
            MemberType.objects.create(organization=club, name="passiv", active=False)
        anna = make_member(club, "Anna", "Aktiv", birth_date=ANNA)
    with net.on(VERBAND):
        fed.federation_member_access = "read"
        fed.save()
        nachbar = make_org("Nachbarverein Musterstadt", parent=fed)
        nachbar_board = make_user("vorstand@nachbar.example")
        give_role(nachbar_board, nachbar)
        gerd = make_member(nachbar, "Gerd", "Gewechselt", birth_date=GERD)
    lower, upper = couple(net, world)
    with net.on(VEREIN):
        release(lower, {"unit": "on", "members": "b"})
    lower.refresh_from_db()
    upper.refresh_from_db()
    return {
        "anna": anna,
        "gerd": gerd,
        "nachbar": nachbar,
        "nachbar_board": nachbar_board,
        "lower": lower,
        "upper": upper,
    }


def placeholder_membership(setup, first_name):
    with tenant_context(setup["upper"].remote_unit.pk):
        return Membership.objects.select_related("person").get(
            organization=setup["upper"].remote_unit, person__first_name=first_name
        )


class TestKorrekturvorschlag:
    def test_vorschlag_landet_als_aenderungsmeldung(self, net, world, setup):
        m = placeholder_membership(setup, "Anna")
        with net.on(VERBAND):
            c = api(world["fed_board"])
            detail = c.get(f"/api/orgs/{world['fed'].pk}/federation/members/{m.pk}/").json()
            assert detail["remote"] and detail["readonly"]
            # Direkt ändern geht nicht, nur vorschlagen
            resp = c.post(
                f"/api/orgs/{world['fed'].pk}/peering/members/{m.pk}/suggest/",
                {"last_name": "Aktiv-Muster", "message": "Schreibweise laut Ausweis"},
                content_type=JSON,
            )
        assert resp.status_code == 202, resp.json()
        cr = ChangeRequest.objects.get(membership=setup["anna"])
        assert cr.data == {"last_name": "Aktiv-Muster"}
        assert cr.previous == {"last_name": "Aktiv"}
        assert "Bürgerbund Musterstadt" in cr.message and "Ausweis" in cr.message
        # Die Person bleibt unverändert, bis der Verein übernimmt
        m.person.refresh_from_db()
        assert m.person.last_name == "Aktiv"


class TestWechselNachUnten:
    """Nachbarverein (Dachverbandsinstanz) möchte Anna, die im fernen Verein aktiv ist."""

    def request(self, setup):
        person = placeholder_membership(setup, "Anna").person
        nachbar = setup["nachbar"]
        with tenant_context(nachbar.pk):
            aktiv = MemberType.objects.get(organization=nachbar, name="aktiv")
            return workflows.create_transfer(
                nachbar,
                setup["nachbar_board"],
                {"person": person, "member_type": aktiv, "entry_date": ENTRY, "message": "Umzug"},
            )

    def test_austritt_bestaetigt(self, net, world, setup):
        with net.on(VERBAND):
            tr = self.request(setup)
        rt = RemoteTransfer.objects.get(coupling=setup["lower"])
        assert rt.role == "from" and rt.membership_id == setup["anna"].pk
        assert rt.data["to_unit"] == "Nachbarverein Musterstadt"
        with net.on(VEREIN):
            c = api(world["club_board"])
            base = f"/api/orgs/{world['club'].pk}/peering/couplings/{setup['lower'].pk}"
            listed = c.get(f"{base}/").json()["transfers"]
            assert listed[0]["name"] == "Anna Aktiv"
            resp = c.post(
                f"{base}/transfers/{rt.pk}/decide/", {"decision": "exit"}, content_type=JSON
            )
        assert resp.status_code == 200, resp.json()
        # Unten ausgetreten (Wechsel), oben bestätigt und im Nachbarverein aufgenommen
        assert setup["anna"].periods.get().exit_date == ENTRY - datetime.timedelta(days=1)
        tr.refresh_from_db()
        assert tr.status == TransferRequest.Status.ACCEPTED
        with tenant_context(setup["nachbar"].pk):
            new = Membership.objects.get(organization=setup["nachbar"], person=tr.person)
            assert new.current_type(ENTRY).member_type.active
        ph = placeholder_membership(setup, "Anna")
        assert ph.periods.get().exit_date == ENTRY - datetime.timedelta(days=1)

    def test_abgelehnt(self, net, world, setup):
        with net.on(VERBAND):
            tr = self.request(setup)
        rt = RemoteTransfer.objects.get(coupling=setup["lower"])
        with net.on(VEREIN):
            resp = api(world["club_board"]).post(
                f"/api/orgs/{world['club'].pk}/peering/couplings/{setup['lower'].pk}"
                f"/transfers/{rt.pk}/decide/",
                {"decision": "reject", "response": "Beitrag noch offen"},
                content_type=JSON,
            )
        assert resp.status_code == 200
        tr.refresh_from_db()
        assert tr.status == TransferRequest.Status.REJECTED
        assert tr.response == "Beitrag noch offen"
        assert setup["anna"].current_period() is not None

    def test_zurueckgezogen(self, net, world, setup):
        with net.on(VERBAND):
            tr = self.request(setup)
            workflows.cancel_transfer(tr)
        assert RemoteTransfer.objects.get(coupling=setup["lower"]).status == "cancelled"


class TestWechselNachOben:
    """Der ferne Verein möchte Gerd, der im Nachbarverein aktiv ist."""

    def ask(self, net, world, setup, **extra):
        club = world["club"]
        with tenant_context(club.pk):
            aktiv = MemberType.objects.get(organization=club, name="aktiv")
        data = {
            "last_name": "Gewechselt",
            "first_name": "Gerd",
            "birth_date": GERD.isoformat(),
            "member_type": aktiv.pk,
            "entry_date": ENTRY.isoformat(),
            "message": "Zieht zu uns",
            **extra,
        }
        with net.on(VEREIN):
            return api(world["club_board"]).post(
                f"/api/orgs/{club.pk}/peering/couplings/{setup['lower'].pk}/transfers/",
                data,
                content_type=JSON,
            )

    def test_bisheriger_verein_bestaetigt(self, net, world, setup):
        resp = self.ask(net, world, setup)
        assert resp.status_code == 201, resp.json()
        tr = TransferRequest.objects.get(to_org=setup["upper"].remote_unit)
        assert tr.from_org == setup["nachbar"] and tr.status == "pending"
        with net.on(VERBAND):
            with tenant_context(setup["nachbar"].pk):
                workflows.decide_transfer(tr, setup["nachbar_board"], "exit")
        rt = RemoteTransfer.objects.get(coupling=setup["lower"], role="to")
        assert rt.status == "accepted", rt.response
        gerd = rt.membership
        assert gerd.organization == world["club"]
        assert gerd.person.first_name == "Gerd"
        # Verbandsnummer bleibt dieselbe und steht gleich beim Verein
        rm = RemoteMember.objects.get(coupling=setup["lower"], uid=f"m{gerd.pk}")
        assert rm.number == setup["gerd"].person.federation.member_number
        # Mit dem nächsten Stand erkennt der Dachverband die Person an der Nummer
        with net.on(VEREIN):
            services.sync(setup["lower"])
        upper_rm = RemoteMember.objects.get(coupling=setup["upper"], uid=f"m{gerd.pk}")
        assert upper_rm.status == "active"
        assert upper_rm.membership.person_id == setup["gerd"].person_id

    def test_nicht_anderswo_aktiv_direkt_aufnehmen(self, net, world, setup):
        resp = self.ask(net, world, setup, last_name="Neu", first_name="Nora")
        assert resp.status_code == 201
        rt = RemoteTransfer.objects.get(coupling=setup["lower"], role="to")
        assert rt.status == "accepted"
        assert rt.membership.person.first_name == "Nora"
        assert not TransferRequest.objects.exists()

    def test_abgelehnt(self, net, world, setup):
        self.ask(net, world, setup)
        tr = TransferRequest.objects.get(to_org=setup["upper"].remote_unit)
        with net.on(VERBAND):
            with tenant_context(setup["nachbar"].pk):
                workflows.decide_transfer(tr, setup["nachbar_board"], "reject", "Nein")
        rt = RemoteTransfer.objects.get(coupling=setup["lower"], role="to")
        assert rt.status == "rejected" and rt.response == "Nein"
        assert rt.membership is None
