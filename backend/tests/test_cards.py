"""Mitgliedsausweis mit QR-Code: Verwaltung, öffentliche Seite, PDF, Rechte, RLS."""

import datetime

import pytest
from django.db import connection
from django.test import Client

from access.models import Role
from cards.models import MemberCard
from core.rls import APP_ROLE
from core.tenancy import set_rls, tenant_context
from members.models import MemberPhoto, Membership, MembershipPeriod
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess

from .factories import audit_with, give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.FRONTEND_URL = "https://verein.example"


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.member_portal_enabled = True
    club.department_access_enabled = True
    club.save()
    return club


@pytest.fixture
def zug(club):
    return Department.objects.create(
        self_managed=True, organization=club, name="Jägerzug", founding_year=1950
    )


@pytest.fixture
def erika(club, zug):
    return make_member(club, "Erika", "Muster", "erika@example.org", departments=[zug])


def card_url(club, m):
    return f"/api/orgs/{club.pk}/members/{m.pk}/card/"


def token_of(m) -> str:
    with tenant_context(m.organization_id):
        return MemberCard.objects.get(membership=m).token


def scan(token):
    return Client().get(f"/api/public/card/{token}/")


def store_photo(m):
    from django.core.files.base import ContentFile

    with tenant_context(m.organization_id):
        MemberPhoto.objects.create(
            organization_id=m.organization_id,
            membership=m,
            image=ContentFile(b"\xff\xd8bild", name="b.jpg"),
            thumbnail=ContentFile(b"\xff\xd8klein", name="t.jpg"),
        )


class TestVerwaltung:
    def test_erstellen_scannen_erneuern_sperren(self, club, erika, api, board_a):
        c = api(board_a)
        assert c.get(card_url(club, erika)).json() == {"state": "none"}
        resp = c.post(card_url(club, erika), {"action": "create"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["state"] == "active"
        assert data["url"].startswith("https://verein.example/ausweis/")
        assert data["qr"].startswith("data:image/svg+xml;base64,")
        token = token_of(erika)
        assert len(token) >= 30

        seite = scan(token).json()
        assert seite["first_name"] == "Erika"
        assert seite["last_name"] == "Muster"
        assert seite["status"] == "active"
        assert seite["member_type"] == "aktiv"
        assert seite["club"] == "Verein A"
        assert seite["federation"] == "Testbund"
        assert seite["departments"] == ["Jägerzug"]
        assert seite["photo_url"] is None
        # Keine weiteren Daten
        assert set(seite) == {
            "first_name",
            "last_name",
            "status",
            "status_label",
            "member_type",
            "club",
            "federation",
            "department_label",
            "departments",
            "photo_url",
            "logo_url",
            "theme",
            "checked_at",
            "club_label",
            "federation_label",
            "imprint_key",
        }

        c.post(card_url(club, erika), {"action": "renew"}, content_type=JSON)
        assert scan(token).status_code == 404
        neu = token_of(erika)
        assert scan(neu).status_code == 200

        c.post(card_url(club, erika), {"action": "revoke"}, content_type=JSON)
        assert c.get(card_url(club, erika)).json()["state"] == "revoked"
        assert scan(neu).status_code == 404
        c.post(card_url(club, erika), {"action": "restore"}, content_type=JSON)
        assert scan(neu).status_code == 200
        assert len(audit_with("Mitgliedsausweis", organization=club)) == 4

    def test_unbekannter_schluessel(self, db):
        assert scan("gibt-es-nicht").status_code == 404

    def test_ohne_recht(self, club, erika, api):
        user = make_user("schrift@example.org")
        give_role(user, club, permissions=["members.view"], name="Schriftführer")
        c = api(user)
        assert c.get(card_url(club, erika)).status_code == 403
        assert c.get(f"/api/orgs/{club.pk}/cards/pdf/").status_code == 403

    def test_vorstandsrollen_bekommen_recht(self):
        from importlib import import_module

        from django.apps import apps as django_apps

        mig = import_module("cards.migrations.0002_rls_und_rechte")
        from organizations.models import Organization

        org = Organization.objects.create(name="X", type="club", parent=Organization.platform())
        role = Role.objects.create(organization=org, name="Vorstand", permissions=["roles.manage"])
        other = Role.objects.create(organization=org, name="Lesen", permissions=["members.view"])
        mig.forwards(django_apps, connection.schema_editor())
        role.refresh_from_db()
        other.refresh_from_db()
        assert "cards.manage" in role.permissions
        assert "cards.manage" not in other.permissions

    def test_fremder_verein(self, club, erika, api, board_b):
        assert api(board_b).get(card_url(club, erika)).status_code == 404


class TestOeffentlicheSeite:
    def test_foto_nur_mit_einwilligung(self, club, erika, api, board_a):
        store_photo(erika)
        api(board_a).post(card_url(club, erika), {"action": "create"}, content_type=JSON)
        token = token_of(erika)
        assert scan(token).json()["photo_url"] is None
        assert Client().get(f"/api/public/card/{token}/photo/").status_code == 404

        Membership.objects.filter(pk=erika.pk).update(photo_consent_at=datetime.date(2026, 1, 1))
        url = scan(token).json()["photo_url"]
        assert url.startswith(f"/api/public/card/{token}/photo/")
        resp = Client().get(url)
        assert resp.status_code == 200
        assert b"".join(resp.streaming_content) == b"\xff\xd8bild"

    def test_ausgetreten(self, club, erika, api, board_a):
        Membership.objects.filter(pk=erika.pk).update(photo_consent_at=datetime.date(2026, 1, 1))
        store_photo(erika)
        api(board_a).post(card_url(club, erika), {"action": "create"}, content_type=JSON)
        with tenant_context(club.pk):
            MembershipPeriod.objects.filter(membership=erika).update(
                exit_date=datetime.date(2025, 12, 31), exit_reason="exit"
            )
        seite = scan(token_of(erika)).json()
        assert seite["status"] == "inactive"
        assert seite["status_label"] == "Keine gültige Mitgliedschaft"
        assert seite["member_type"] is None
        assert seite["departments"] == []
        assert seite["photo_url"] is None

    def test_nach_loeschfrist_ungueltig(self, club, erika, api, board_a):
        api(board_a).post(card_url(club, erika), {"action": "create"}, content_type=JSON)
        token = token_of(erika)
        Membership.objects.filter(pk=erika.pk).update(purged_at=datetime.datetime.now(datetime.UTC))
        assert scan(token).status_code == 404

    def test_ratenbegrenzung(self, db, settings):
        from cards import views

        for _ in range(views.RATE[0]):
            scan("x")
        assert scan("x").status_code == 429


class TestPdf:
    def test_verein_alle_und_abteilung(self, club, zug, erika, api, board_a):
        make_member(club, "Otto", "Ohne")
        c = api(board_a)
        resp = c.get(f"/api/orgs/{club.pk}/cards/pdf/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        with tenant_context(club.pk):
            assert MemberCard.objects.count() == 2
        c.get(f"/api/orgs/{club.pk}/cards/pdf/?abteilung={zug.pk}")
        c.get(f"/api/orgs/{club.pk}/cards/pdf/?mitglied={erika.pk}")

    def test_gesperrte_nicht_drucken(self, club, erika, api, board_a):
        c = api(board_a)
        c.post(card_url(club, erika), {"action": "revoke"}, content_type=JSON)
        resp = c.get(f"/api/orgs/{club.pk}/cards/pdf/?mitglied={erika.pk}")
        assert resp.status_code == 200
        with tenant_context(club.pk):
            assert MemberCard.objects.get().revoked_at is not None

    def test_dachverband(self, orgs, club, erika, api):
        fed = orgs["federation"]
        make_member(orgs["b"], "Berta", "Bund")
        user = make_user("bund@example.org")
        give_role(user, fed)
        c = api(user)
        assert c.get(f"/api/orgs/{fed.pk}/cards/pdf/").status_code == 403
        fed.federation_member_access = "read"
        fed.save()
        resp = c.get(f"/api/orgs/{fed.pk}/cards/pdf/")
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")
        with tenant_context(club.pk):
            assert MemberCard.objects.filter(organization=club).count() == 1
        with tenant_context(orgs["b"].pk):
            assert MemberCard.objects.filter(organization=orgs["b"]).count() == 1
        resp = c.get(f"/api/orgs/{fed.pk}/cards/pdf/?verein={club.pk}")
        assert resp.status_code == 200


class TestAbteilungUndMitglied:
    def test_abteilung_mit_recht(self, club, zug, erika, api, board_a):
        role = DepartmentRole.objects.create(
            organization=club,
            department=zug,
            name="Spieß",
            permissions=["dept.members.view", "dept.cards.manage"],
        )
        m = make_member(club, "Karl", "Spieß", "karl@example.org", departments=[zug])
        from members.models import DepartmentRoleHolder

        DepartmentRoleHolder.objects.create(
            organization=club, membership=m, role=role, valid_from="2020-01-01"
        )
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        spiess = PortalAccess.objects.get(membership=m).user
        fremd = make_member(club, "Otto", "Ohne")
        c = api(spiess)
        resp = c.post(
            f"/api/depts/{zug.pk}/members/{erika.pk}/card/", {"action": "create"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert c.get(f"/api/depts/{zug.pk}/members/{fremd.pk}/card/").status_code == 404
        resp = c.get(f"/api/depts/{zug.pk}/cards/pdf/")
        assert resp.status_code == 200
        with tenant_context(club.pk):
            assert set(MemberCard.objects.values_list("membership_id", flat=True)) == {
                erika.pk,
                m.pk,
            }
        role.permissions = ["dept.members.view"]
        role.save()
        assert c.get(f"/api/depts/{zug.pk}/cards/pdf/").status_code == 403

    def test_mitglied_sieht_eigenen_ausweis(self, club, erika, api, board_a):
        api(board_a).post(f"/api/orgs/{club.pk}/members/{erika.pk}/access/")
        access = PortalAccess.objects.get(membership=erika)
        c = api(access.user)
        data = c.get(f"/api/portal/{access.pk}/card/").json()
        assert data["state"] == "active"
        assert "token" not in data
        assert data["qr"].startswith("data:image/svg+xml")
        # Angaben für die App
        display = data["display"]
        assert display["first_name"] == "Erika" and display["status"] == "active"
        assert display["departments"] == ["Jägerzug"]
        assert "club_number" in display and display["photo_url"] is None
        assert c.get(f"/api/portal/{access.pk}/card/pdf/").content.startswith(b"%PDF")
        assert c.get(f"/api/portal/{access.pk + 9}/card/").status_code == 404
        # gesperrt: keine Angaben für die App
        api(board_a).post(card_url(club, erika), {"action": "revoke"}, content_type=JSON)
        data = c.get(f"/api/portal/{access.pk}/card/").json()
        assert data["state"] == "revoked" and "display" not in data


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_rls_ausweise(orgs, club, erika, api, board_a):
    api(board_a).post(card_url(club, erika), {"action": "create"}, content_type=JSON)
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        set_rls(orgs["b"].pk)
        assert MemberCard.objects.count() == 0
        set_rls(club.pk)
        assert MemberCard.objects.count() == 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)
