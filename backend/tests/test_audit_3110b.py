"""Gesamtaudit 31.10.b: Anmeldung, Geräte, Rückgängig, Startpasswort, Verbund (erfundene Daten)."""

import datetime

import pytest
from django.db import connection
from django.utils import timezone

from access.permissions import inherited_permissions, is_platform_admin
from accounts.models import User
from accounts.tasks import expire_initial_passwords
from core.tenancy import set_rls, tenant_context
from devices.models import Device
from members.models import DepartmentMembership
from organizations.models import Department, Organization
from peering import sso
from portal.models import PortalAccess
from portal.services import has_admin_access

from .factories import give_role, make_member, make_user
from .test_m7_access import club, kassierer, zug  # noqa: F401
from .test_rls import as_app_role

pytestmark = pytest.mark.django_db
JSON = "application/json"
postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="Row-Level Security gibt es nur in PostgreSQL"
)


# --- AT-S01: Rollen eines noch nicht angemeldeten Kontos unter RLS ---


@postgres_only
def test_verbund_faktorpflicht_sieht_rollen_ohne_anmeldung(orgs, board_a):
    plain = make_user("mitglied@example.org")
    set_rls(None, None, False)  # wie eine anonyme Anfrage
    with as_app_role():
        assert has_admin_access(board_a)
        assert sso.needs_local_factor(board_a)
        assert not sso.needs_local_factor(plain)


@postgres_only
def test_plattformrolle_unter_rls_erkannt(orgs):
    admin = make_user("plattform@example.org")
    give_role(admin, Organization.platform())
    set_rls(None, None, False)
    with as_app_role():
        assert is_platform_admin(admin)


# --- AT-F01: Zugang in einem Verein löschen, Geräte für den anderen bleiben ---


@postgres_only
def test_zugang_loeschen_meldet_geraete_fuer_anderen_verein_nicht_ab(orgs, api, board_a, board_c):
    for org, board in ((orgs["a"], board_a), (orgs["c"], board_c)):
        org.member_portal_enabled = True
        org.save()
        m = make_member(org, "Gerda", "Geteilt", "gerda@example.org")
        resp = api(board).post(f"/api/orgs/{org.pk}/members/{m.pk}/access/")
        assert resp.status_code in (200, 201), resp.json()
    user = User.objects.get(email="gerda@example.org")
    device = Device.objects.create(user=user, name="Telefon", token_hash="d" * 64)
    access_a = PortalAccess.objects.get(organization=orgs["a"])
    with as_app_role(), tenant_context(orgs["a"].pk, board_a.pk):
        access_a.delete()
    device.refresh_from_db()
    assert device.revoked_at is None
    # Letzter Zugang weg: dann sind die Geräte abgemeldet
    with as_app_role(), tenant_context(orgs["c"].pk, board_c.pk):
        PortalAccess.objects.get(organization=orgs["c"]).delete()
    device.refresh_from_db()
    assert device.revoked_at is not None


# --- AT-F02: Passwörter unverändert ---


def test_passwort_mit_leerzeichen_am_rand(api, user, password):
    c = api(user)
    resp = c.post(
        "/api/me/password/",
        {"current_password": password, "new_password": "  Lange Passphrase 2026  "},
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()
    user.refresh_from_db()
    assert user.check_password("  Lange Passphrase 2026  ")
    assert not user.check_password("Lange Passphrase 2026")


# --- AT-S03: Rückgängig nur im heutigen Bereich ---


def test_rueckgaengig_nach_wechsel_aus_dem_zug_gesperrt(club, zug, kassierer, api):  # noqa: F811
    m = make_member(club, "Zora", "Zug", departments=[zug])
    c = api(kassierer)
    resp = c.patch(f"/api/depts/{zug.pk}/members/{m.pk}/", {"phone": "0171 1"}, content_type=JSON)
    change_set = resp["X-Change-Set"]
    anderer = Department.objects.create(
        self_managed=True, organization=club, name="Schützenzug", founding_year=1960
    )
    with tenant_context(club.pk):
        DepartmentMembership.objects.filter(membership=m).update(department=anderer)
    undo = c.post(f"/api/depts/{zug.pk}/changes/{change_set}/undo/", {}, content_type=JSON)
    assert undo.status_code == 403
    assert "außerhalb" in undo.json()["detail"]
    with tenant_context(club.pk):
        assert m.person.contacts.get().phone == "0171 1"


def test_rueckgaengig_im_zug_geht_weiter(club, zug, kassierer, api):  # noqa: F811
    m = make_member(club, "Zora", "Zug", departments=[zug])
    c = api(kassierer)
    resp = c.patch(f"/api/depts/{zug.pk}/members/{m.pk}/", {"phone": "0171 1"}, content_type=JSON)
    undo = c.post(
        f"/api/depts/{zug.pk}/changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON
    )
    assert undo.status_code == 200, undo.json()


# --- AT-S04: Startpasswort läuft ab und muss ersetzt werden ---


def set_initial_password(user) -> str:
    """Altes Startpasswort wie vor der Umstellung auf Einladungen (FQ-16)."""
    password = "Start-Passwort-2026"
    user.set_password(password)
    user.initial_password_expires = timezone.now() + datetime.timedelta(days=7)
    return password


def test_startpasswort_muss_ersetzt_werden_und_laeuft_ab(api):
    """Noch ausgegebene Startpasswörter (vor der Umstellung auf Einladungen)."""
    new_user = make_user("neu@example.org")
    start = set_initial_password(new_user)
    new_user.save()
    assert new_user.must_change_password and new_user.check_password(start)
    session = api(new_user).get("/_allauth/browser/v1/auth/session").json()
    assert session["data"]["user"]["must_change_password"] is True

    # Nach Ablauf unbrauchbar
    User.objects.filter(pk=new_user.pk).update(
        initial_password_expires=timezone.now() - datetime.timedelta(minutes=1)
    )
    assert expire_initial_passwords() == 1
    new_user.refresh_from_db()
    assert not new_user.has_usable_password() and not new_user.must_change_password


def test_eigenes_passwort_ersetzt_startpasswort(api):
    chef = make_user("chef@example.org")
    start = set_initial_password(chef)
    chef.save()
    resp = api(chef).post(
        "/api/me/password/",
        {"current_password": start, "new_password": "Eigenes-Passwort-2026"},
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()
    chef.refresh_from_db()
    assert not chef.must_change_password
    assert expire_initial_passwords() == 0


def test_alte_startpasswoerter_umstellen(api):
    """FQ-16 (Ralf 01.11.2026): nur zählen; mit --umstellen Link statt Startpasswort."""
    from io import StringIO

    from django.core import mail
    from django.core.management import call_command

    old = make_user("alt@example.org")
    start = set_initial_password(old)
    old.save()
    make_user("normal@example.org")

    out = StringIO()
    call_command("startpasswoerter", stdout=out)
    assert "1 Konten" in out.getvalue() and "alt@" not in out.getvalue()
    old.refresh_from_db()
    assert old.check_password(start)

    out = StringIO()
    call_command("startpasswoerter", "--umstellen", stdout=out)
    assert "1 umgestellt, 1 Links verschickt" in out.getvalue()
    old.refresh_from_db()
    assert not old.has_usable_password() and not old.must_change_password
    assert [m.to for m in mail.outbox] == [["alt@example.org"]]
    assert "Passwort festlegen" in mail.outbox[0].subject


# --- Frage 2: Einladungslink statt Startpasswort ---


def test_neues_konto_bekommt_einladung_statt_startpasswort(api, orgs, board_a):
    from django.core import mail

    from accounts.tokens import InvitationTokenGenerator

    c = api(board_a)
    role = c.post(
        f"/api/orgs/{orgs['a'].pk}/roles/",
        {"name": "Kassierer", "permissions": ["members.view"]},
        content_type=JSON,
    ).json()
    data = c.post(
        f"/api/orgs/{orgs['a'].pk}/assignments/",
        {"email": "neu@example.org", "role": role["id"], "valid_from": "2024-01-01"},
        content_type=JSON,
    ).json()
    assert data["new_account"] and data["invited"]
    user = User.objects.get(email="neu@example.org")
    assert not user.has_usable_password()
    body = mail.outbox[-1].body
    assert "gültig 7 Tage" in body
    token = body.split("/")[-1].split()[0].split("-", 1)[1]
    gen = InvitationTokenGenerator()
    assert gen.check_token(user, token)
    # Nach 6 Tagen gilt die Einladung noch, nach 8 nicht mehr
    now = gen._now()
    gen._now = lambda: now + datetime.timedelta(days=6)
    assert gen.check_token(user, token)
    gen._now = lambda: now + datetime.timedelta(days=8)
    assert not gen.check_token(user, token)


def test_passwort_vergessen_bleibt_bei_der_normalen_frist(settings):
    from accounts.tokens import InvitationTokenGenerator

    user = make_user("aktiv@example.org")
    user.last_login = timezone.now()
    user.save()
    gen = InvitationTokenGenerator()
    token = gen.make_token(user)
    now = gen._now()
    gen._now = lambda: now + datetime.timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 60)
    assert not gen.check_token(user, token)


# --- AT-V01: keine Rechte aus stillgelegten Einheiten darüber ---


def test_keine_geerbten_rechte_aus_inaktiver_einheit(orgs, board_a):
    unit = Department.objects.create(
        organization=orgs["a"], name="Jugend", founding_year=1990, own_workspace=True
    )
    assert inherited_permissions(board_a, unit)
    orgs["a"].is_active = False
    orgs["a"].save(update_fields=["is_active"])
    unit.refresh_from_db()
    assert inherited_permissions(board_a, unit) == set()


# --- AT-V02: Schritt zwei der Verbundanmeldung prüft den Zustand erneut ---


def test_verbund_schritt_zwei_nach_ende_der_anmeldung(rf, board_a, monkeypatch):
    from django.contrib.sessions.backends.signed_cookies import SessionStore
    from django.core.exceptions import PermissionDenied

    request = rf.post("/")
    request.session = SessionStore()
    request.session[sso.STEPUP_KEY] = {
        "user": board_a.pk,
        "peer": "00000000-0000-0000-0000-000000000000",
        "next": "/",
        "until": int(timezone.now().timestamp()) + 60,
    }
    monkeypatch.setattr(sso, "check_second_factor", lambda user, code: True)
    with pytest.raises(PermissionDenied):
        sso.finish_stepup(request, "123456")
