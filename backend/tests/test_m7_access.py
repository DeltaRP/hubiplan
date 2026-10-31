"""Meilenstein 7: Postausgang, Mitgliederbereich, Abteilungszugang, Anmeldelinks."""

import re

import pytest
from django.core import mail
from django.test import Client, override_settings

from members.models import ContactDetails, DepartmentRoleHolder
from organizations.models import Department, DepartmentRole
from outbox.models import OutgoingMail
from portal.models import ChangeRequest, LoginLink, PortalAccess

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
SESSION = "/_allauth/browser/v1/auth/session"


def link_token(body: str) -> str:
    return re.search(r"/anmelden/link/([\w-]+)", body).group(1)


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


class TestPostausgang:
    @override_settings(EMAIL_BACKEND="outbox.backend.OutboxBackend")
    def test_mail_wird_gespeichert(self, orgs, api, board_a):
        from outbox import mail as outbox_mail

        outbox_mail.send(
            "erika@example.org",
            "Hallo",
            "Text",
            organization=orgs["a"],
            kind="test",
            attachments=[("rechnung.pdf", b"%PDF-1.4", "application/pdf")],
        )
        m = OutgoingMail.objects.get()
        assert m.organization == orgs["a"]
        assert m.status == "stored"
        assert m.attachments[0]["name"] == "rechnung.pdf"

        resp = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/outbox/")
        assert resp.status_code == 200
        assert resp.json()["results"][0]["subject"] == "Hallo"
        resp = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/outbox/{m.pk}/attachments/0/")
        assert resp.status_code == 200
        assert b"".join(resp.streaming_content) == b"%PDF-1.4"
        # anderer Verein sieht die Mail nicht
        assert api(board_a).get(f"/api/orgs/{orgs['b'].pk}/outbox/").status_code == 404

    @override_settings(EMAIL_BACKEND="outbox.backend.OutboxBackend")
    def test_test_postfach_nur_fuer_plattform(self, orgs, api, board_a, django_user_model):
        from outbox import mail as outbox_mail

        outbox_mail.send("x@example.org", "Ohne Verein", "Text")
        assert api(board_a).get("/api/platform/outbox/").status_code == 403
        admin = django_user_model.objects.create_superuser("admin@example.org", "x")
        resp = api(admin).get("/api/platform/outbox/")
        assert resp.status_code == 200
        assert resp.json()["results"][0]["subject"] == "Ohne Verein"


class TestZugangUndAnmeldelink:
    def test_zugang_einrichten_und_mit_link_anmelden(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        resp = api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        assert resp.status_code == 200, resp.json()
        assert resp.json()["sent"] == "link"
        access = PortalAccess.objects.get()
        assert access.user.email == "erika@example.org"
        assert not access.user.has_usable_password()
        token = link_token(mail.outbox[-1].body)

        browser = Client()
        resp = browser.post(f"/api/public/login-link/{token}/", content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert browser.get(SESSION).status_code == 200
        # einmal nutzbar
        assert Client().post(f"/api/public/login-link/{token}/").status_code == 404

        contexts = browser.get("/api/me/contexts/").json()
        assert [p["club_name"] for p in contexts["portal"]] == ["Verein A"]
        detail = browser.get(f"/api/portal/{access.pk}/").json()
        assert detail["first_name"] == "Erika"
        assert detail["contact"]["email"] == "erika@example.org"
        # fremder Zugang: nicht gefunden
        assert browser.get(f"/api/portal/{access.pk + 99}/").status_code == 404

    def test_ohne_freischaltung_kein_zugang(self, orgs, api, board_a):
        m = make_member(orgs["a"], "Erika", "Muster")
        resp = api(board_a).post(f"/api/orgs/{orgs['a'].pk}/members/{m.pk}/access/")
        assert resp.status_code == 400

    def test_mitgliederbereich_abgeschaltet(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        access = PortalAccess.objects.get()
        club.member_portal_enabled = False
        club.save()
        member = api(access.user)
        assert member.get("/api/me/contexts/").json()["portal"] == []
        assert member.get(f"/api/portal/{access.pk}/").status_code == 404

    def test_vorstand_bekommt_keinen_link_nur_hinweis(self, club, api, board_a):
        m = make_member(club, "Vera", "Vorstand", "vorstand-a@example.org")
        resp = api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        assert resp.json()["sent"] == "password"
        # Kein Passwort- oder Anmeldelink aus dem Mitgliederbereich (Gesamtaudit A-S01)
        body = mail.outbox[-1].body
        assert "/passwort-zuruecksetzen/" not in body
        assert "/anmelden/link/" not in body
        assert "Passwort vergessen" in body
        # ein (alter) Anmeldelink hilft einem Vorstand nicht
        from portal.services import create_login_link

        token = create_login_link(board_a).rsplit("/", 1)[-1]
        assert Client().post(f"/api/public/login-link/{token}/").status_code == 403

    def test_link_anfordern(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        before = len(mail.outbox)
        resp = Client().post(
            "/api/public/login-link/", {"email": "ERIKA@example.org"}, content_type=JSON
        )
        assert resp.status_code == 200
        assert len(mail.outbox) == before + 1
        assert LoginLink.objects.count() == 2
        # unbekannte Adresse: gleiche Antwort, keine Mail
        resp2 = Client().post(
            "/api/public/login-link/", {"email": "niemand@example.org"}, content_type=JSON
        )
        assert resp2.json() == resp.json()
        assert len(mail.outbox) == before + 1

    def test_zugang_entfernen(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        resp = api(board_a).delete(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        assert resp.status_code == 204
        assert not PortalAccess.objects.exists()


class TestAenderungsmeldung:
    def test_kontaktdaten_sofort_name_mit_bestaetigung(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        access = PortalAccess.objects.get()
        member = api(access.user)
        resp = member.post(
            f"/api/portal/{access.pk}/change-requests/",
            {"street": "Neue Straße 9", "last_name": "Neu", "message": "geheiratet"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert resp.json()["applied"] == {"street": "Neue Straße 9"}
        assert resp.json()["request"]["data"] == {"last_name": "Neu"}
        assert ContactDetails.objects.get().street == "Neue Straße 9"
        # zweite Meldung mit Bestätigung erst nach Bearbeitung, Kontaktdaten gehen weiter
        resp = member.post(
            f"/api/portal/{access.pk}/change-requests/", {"first_name": "Eri"}, content_type=JSON
        )
        assert resp.status_code == 400
        resp = member.post(
            f"/api/portal/{access.pk}/change-requests/", {"city": "Neustadt"}, content_type=JSON
        )
        assert resp.status_code == 200 and resp.json()["request"] is None

        board = api(board_a)
        pending = board.get(f"/api/orgs/{club.pk}/change-requests/").json()
        assert len(pending) == 1
        resp = board.post(
            f"/api/orgs/{club.pk}/change-requests/{pending[0]['id']}/decide/",
            {"accept": True},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        m.person.refresh_from_db()
        assert m.person.last_name == "Neu"
        assert ChangeRequest.objects.get().status == "accepted"

    def test_verein_verlangt_bestaetigung(self, club, api, board_a):
        club.contact_changes_need_approval = True
        club.save()
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        access = PortalAccess.objects.get()
        resp = api(access.user).post(
            f"/api/portal/{access.pk}/change-requests/",
            {"email": "neu@example.org"},
            content_type=JSON,
        )
        assert resp.status_code == 201
        assert resp.json()["applied"] == {}
        cr = ChangeRequest.objects.get()
        api(board_a).post(
            f"/api/orgs/{club.pk}/change-requests/{cr.pk}/decide/",
            {"accept": True},
            content_type=JSON,
        )
        assert ContactDetails.objects.get().email == "neu@example.org"
        # Die Anmelde-E-Mail ändert sich erst nach Bestätigung durch das neue Postfach
        access.user.refresh_from_db()
        assert access.user.email == "erika@example.org"
        from accounts.models import EmailChange

        change = EmailChange.objects.get(user=access.user)
        assert change.new_email == "neu@example.org" and change.used_at is None
        assert any("neu@example.org" in m.to for m in mail.outbox)

    def test_nichts_geaendert(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        access = PortalAccess.objects.get()
        resp = api(access.user).post(
            f"/api/portal/{access.pk}/change-requests/", {"first_name": "Erika"}, content_type=JSON
        )
        assert resp.status_code == 400

    def test_ablehnen(self, club, api, board_a):
        m = make_member(club, "Erika", "Muster")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        access = PortalAccess.objects.get()
        api(access.user).post(
            f"/api/portal/{access.pk}/change-requests/", {"first_name": "Eri"}, content_type=JSON
        )
        cr = ChangeRequest.objects.get()
        resp = api(board_a).post(
            f"/api/orgs/{club.pk}/change-requests/{cr.pk}/decide/",
            {"accept": False, "response": "Bitte persönlich melden"},
            content_type=JSON,
        )
        assert resp.json()["status"] == "rejected"
        m.person.refresh_from_db()
        assert m.person.first_name == "Erika"


@pytest.fixture
def kassierer(club, zug, api, board_a):
    """Mitglied des Zugs mit der Rolle Zugkassierer und eingerichtetem Zugang."""
    role = DepartmentRole.objects.create(
        organization=club,
        department=zug,
        name="Zugkassierer",
        permissions=["dept.members.view", "dept.members.edit", "dept.access.manage"],
    )
    m = make_member(club, "Karl", "Kasse", "karl@example.org", departments=[zug])
    DepartmentRoleHolder.objects.create(
        organization=club, membership=m, role=role, valid_from="2020-01-01"
    )
    api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
    user = PortalAccess.objects.get(membership=m).user
    user.set_password("Sicheres-Passwort-123")
    user.save()
    return user


class TestAbteilungszugang:
    def test_kassierer_sieht_nur_seinen_zug(self, club, zug, kassierer, api):
        anderer = Department.objects.create(
            self_managed=True, organization=club, name="Schützenzug", founding_year=1960
        )
        make_member(club, "Zora", "Zug", departments=[zug])
        make_member(club, "Otto", "Ohne")
        fremd = make_member(club, "Sina", "Schütz", departments=[anderer])

        c = api(kassierer)
        ctx = c.get("/api/me/contexts/").json()
        assert [d["name"] for d in ctx["departments"]] == ["Jägerzug"]
        rows = c.get(f"/api/depts/{zug.pk}/members/").json()["results"]
        assert sorted(r["first_name"] for r in rows) == ["Karl", "Zora"]
        assert c.get(f"/api/depts/{zug.pk}/members/{fremd.pk}/").status_code == 404
        assert c.get(f"/api/depts/{anderer.pk}/members/").status_code == 404
        # Vereinsbereich bleibt verschlossen
        assert c.get(f"/api/orgs/{club.pk}/members/").status_code == 404

    def test_kassierer_aendert_daten(self, club, zug, kassierer, api):
        m = make_member(club, "Zora", "Zug", departments=[zug])
        resp = api(kassierer).patch(
            f"/api/depts/{zug.pk}/members/{m.pk}/", {"phone": "0171 1"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["contact"]["phone"] == "0171 1"

    def test_kassierer_nimmt_eigene_aenderung_zurueck(self, club, zug, kassierer, api, board_a):
        m = make_member(club, "Zora", "Zug", departments=[zug])
        c = api(kassierer)
        resp = c.patch(
            f"/api/depts/{zug.pk}/members/{m.pk}/", {"phone": "0171 1"}, content_type=JSON
        )
        assert resp["X-Change-Undoable"] == "1"
        change_set = resp["X-Change-Set"]
        undo = c.post(f"/api/depts/{zug.pk}/changes/{change_set}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert c.get(f"/api/depts/{zug.pk}/members/{m.pk}/").json()["contact"]["phone"] == ""
        # Fremde Änderungen (hier vom Vorstand) nicht
        other = api(board_a).patch(
            f"/api/orgs/{club.pk}/members/{m.pk}/", {"phone": "2"}, content_type=JSON
        )["X-Change-Set"]
        resp = c.post(f"/api/depts/{zug.pk}/changes/{other}/undo/", {}, content_type=JSON)
        assert resp.status_code == 403

    def test_ohne_aenderungsrecht(self, club, zug, kassierer, api):
        role = DepartmentRole.objects.get()
        role.permissions = ["dept.members.view"]
        role.save()
        m = make_member(club, "Zora", "Zug", departments=[zug])
        resp = api(kassierer).patch(
            f"/api/depts/{zug.pk}/members/{m.pk}/", {"phone": "1"}, content_type=JSON
        )
        assert resp.status_code == 403

    def test_abteilungszugang_abgeschaltet(self, club, zug, kassierer, api):
        club.department_access_enabled = False
        club.save()
        assert api(kassierer).get(f"/api/depts/{zug.pk}/members/").status_code == 404

    def test_kein_anmeldelink_fuer_kassierer(self, kassierer):
        from portal.services import link_login_allowed

        assert link_login_allowed(kassierer) is False

    def test_rollen_der_abteilung_verwalten(self, club, zug, kassierer, api):
        role = DepartmentRole.objects.get()
        role.permissions = [*role.permissions, "dept.roles.manage"]
        role.save()
        c = api(kassierer)
        data = c.get(f"/api/depts/{zug.pk}/roles/").json()
        assert data["roles"][0]["name"] == "Zugkassierer"
        assert data["catalog"][0]["permissions"][0]["code"] == "dept.members.view"

        resp = c.post(
            f"/api/depts/{zug.pk}/roles/",
            {"name": "Zugführer", "permissions": ["dept.members.view"]},
            content_type=JSON,
        )
        assert resp.status_code == 201
        new_role = resp.json()["id"]
        m = make_member(club, "Zora", "Zug", departments=[zug])
        resp = c.post(
            f"/api/depts/{zug.pk}/holders/", {"member": m.pk, "role": new_role}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        # sich selbst die Rollenverwaltung entziehen geht nicht
        resp = c.patch(
            f"/api/depts/{zug.pk}/roles/{role.pk}/",
            {"permissions": ["dept.members.view"]},
            content_type=JSON,
        )
        assert resp.status_code == 400
        own = DepartmentRoleHolder.objects.get(role=role)
        assert c.post(f"/api/depts/{zug.pk}/holders/{own.pk}/end/").status_code == 400
        # unbekannte Rechte werden abgelehnt
        resp = c.post(
            f"/api/depts/{zug.pk}/roles/",
            {"name": "X", "permissions": ["members.edit"]},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_zugang_fuer_zugmitglied(self, club, zug, kassierer, api):
        m = make_member(club, "Zora", "Zug", "zora@example.org", departments=[zug])
        resp = api(kassierer).post(f"/api/depts/{zug.pk}/members/{m.pk}/access/")
        assert resp.status_code == 200, resp.json()
        assert resp.json()["sent"] == "link"

    def test_verein_pflegt_rechte_der_abteilungsrollen(self, club, zug, api, board_a):
        role = DepartmentRole.objects.create(organization=club, department=zug, name="Zugführer")
        resp = api(board_a).patch(
            f"/api/orgs/{club.pk}/department-roles/{role.pk}/",
            {"permissions": ["dept.members.view", "dept.roles.manage"]},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        role.refresh_from_db()
        assert role.permissions == ["dept.members.view", "dept.roles.manage"]


def test_zwei_faktor_sperrt_anmeldelink(club, api, board_a):
    from allauth.mfa.models import Authenticator

    m = make_member(club, "Erika", "Muster")
    api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
    user = PortalAccess.objects.get().user
    Authenticator.objects.create(user=user, type="totp", data={})
    token = link_token(mail.outbox[-1].body)
    assert Client().post(f"/api/public/login-link/{token}/").status_code == 403


@pytest.mark.skipif(
    __import__("django.db").db.connection.vendor != "postgresql", reason="nur PostgreSQL"
)
def test_rls_zugaenge(club, orgs, api, board_a):
    """Zugänge und Meldungen sieht nur der eigene Verein – und der Benutzer selbst."""
    from core.tenancy import set_rls

    from .test_rls import as_app_role

    m = make_member(club, "Erika", "Muster")
    api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
    access = PortalAccess.objects.get()
    ChangeRequest.objects.create(organization=club, membership=m, data={"city": "X"})
    other = make_user("fremd@example.org")
    give_role(other, orgs["b"])
    with as_app_role():
        set_rls(orgs["b"].pk, other.pk)
        assert not PortalAccess.objects.exists()
        assert not ChangeRequest.objects.exists()
        set_rls(None, access.user_id)
        assert PortalAccess.objects.count() == 1
        assert not ChangeRequest.objects.exists()
        set_rls(club.pk, board_a.pk)
        assert ChangeRequest.objects.count() == 1


def test_vergebene_abteilungsrolle_loeschen_entfernt_inhaber(club, kassierer, api, board_a):
    from audit.models import AuditEntry

    role = DepartmentRole.objects.get(name="Zugkassierer")
    resp = api(board_a).delete(f"/api/orgs/{club.pk}/department-roles/{role.pk}/")
    assert resp.status_code == 204
    assert not DepartmentRole.objects.filter(pk=role.pk).exists()
    assert not DepartmentRoleHolder.objects.filter(role_id=role.pk).exists()
    assert AuditEntry.objects.filter(action="delete", person_id__isnull=False).exists()


def test_abteilung_loescht_vergebene_rolle(club, zug, kassierer, api):
    role = DepartmentRole.objects.get(name="Zugkassierer")
    role.permissions = [*role.permissions, "dept.roles.manage"]
    role.save()
    spiess = DepartmentRole.objects.create(organization=club, department=zug, name="Spieß")
    m = make_member(club, "Sven", "Spieß", departments=[zug])
    DepartmentRoleHolder.objects.create(
        organization=club, membership=m, role=spiess, valid_from="2021-01-01"
    )
    resp = api(kassierer).delete(f"/api/depts/{zug.pk}/roles/{spiess.pk}/")
    assert resp.status_code == 204
    assert not DepartmentRoleHolder.objects.filter(membership=m).exists()
    assert DepartmentRoleHolder.objects.filter(role=role).exists()
