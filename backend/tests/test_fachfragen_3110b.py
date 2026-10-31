"""Fachfragen aus dem Gesamtaudit 31.10.b, wie empfohlen umgesetzt (erfundene Daten)."""

import pytest
from django.core import mail

from core.tenancy import tenant_context
from portal.models import PortalAccess

from .factories import make_member

pytestmark = pytest.mark.django_db
JSON = "application/json"


# --- Frage 15: Zugang nur ausdrücklich auf eine neue Adresse übertragen ---


def test_neue_adresse_uebertraegt_zugang_nicht_von_selbst(orgs, api, board_a):
    club = orgs["a"]
    club.member_portal_enabled = True
    club.save()
    m = make_member(club, "Petra", "Post", "petra@example.org")
    c = api(board_a)
    assert c.post(f"/api/orgs/{club.pk}/members/{m.pk}/access/").status_code == 200
    with tenant_context(club.pk):
        contact = m.person.contacts.get()
        contact.email = "neu@example.org"
        contact.save()

    resp = c.post(f"/api/orgs/{club.pk}/members/{m.pk}/access/", {}, content_type=JSON)
    assert resp.status_code == 409
    assert "übertragen" in resp.json()["detail"]
    assert PortalAccess.objects.get(membership=m).user.email == "petra@example.org"

    mail.outbox.clear()
    resp = c.post(
        f"/api/orgs/{club.pk}/members/{m.pk}/access/", {"transfer": True}, content_type=JSON
    )
    assert resp.status_code == 200, resp.json()
    assert PortalAccess.objects.get(membership=m).user.email == "neu@example.org"
    to_old = [x for x in mail.outbox if x.to == ["petra@example.org"]]
    assert to_old and "übertragen" in to_old[0].subject
    assert "neu@example.org" not in to_old[0].body


# --- Frage 1: Pflicht-2FA für heikle Rechte nach 14 Tagen Übergang ---


def _totp(user):
    from allauth.mfa.models import Authenticator

    return Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={})


def test_pflicht_2fa_nach_uebergang(orgs, api, board_a):
    import datetime

    from django.utils import timezone

    from access.catalog import MEMBERS_VIEW, ROLES_MANAGE
    from access.permissions import permissions_in
    from accounts.models import User

    perms = permissions_in(board_a, orgs["a"])
    assert ROLES_MANAGE in perms
    board_a.refresh_from_db()
    due = board_a.mfa_required_by
    assert due and due - timezone.now() > datetime.timedelta(days=13)
    session = api(board_a).get("/_allauth/browser/v1/auth/session").json()["data"]["user"]
    assert session["mfa_required_by"] and session["mfa_overdue"] is False

    User.objects.filter(pk=board_a.pk).update(
        mfa_required_by=timezone.now() - datetime.timedelta(minutes=1)
    )
    board_a.refresh_from_db()
    perms = permissions_in(board_a, orgs["a"])
    assert ROLES_MANAGE not in perms and MEMBERS_VIEW in perms
    assert api(board_a).get(f"/api/orgs/{orgs['a'].pk}/roles/").status_code == 403
    session = api(board_a).get("/_allauth/browser/v1/auth/session").json()["data"]["user"]
    assert session["mfa_overdue"] is True

    _totp(board_a)
    fresh = User.objects.get(pk=board_a.pk)
    assert ROLES_MANAGE in permissions_in(fresh, orgs["a"])
    session = api(fresh).get("/_allauth/browser/v1/auth/session").json()["data"]["user"]
    assert "mfa_required_by" not in session


def test_zweite_person_setzt_2fa_zurueck(orgs, api, board_a, django_capture_on_commit_callbacks):
    from allauth.mfa.models import Authenticator

    from access.models import RoleAssignment
    from accounts.models import User

    from .factories import give_role, make_user

    kassierer = make_user("kasse@example.org")
    assignment = give_role(kassierer, orgs["a"])
    _totp(kassierer)
    url = f"/api/orgs/{orgs['a'].pk}/assignments/{assignment.pk}/reset-mfa/"
    # Ohne eigenen zweiten Faktor nicht
    assert api(board_a).post(url).status_code == 400
    _totp(board_a)
    board = User.objects.get(pk=board_a.pk)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        resp = api(board).post(url)
    assert resp.status_code == 200, resp.json()
    assert not Authenticator.objects.filter(user=kassierer).exists()
    assert any(m.to == ["kasse@example.org"] for m in mail.outbox)
    # Für sich selbst nie
    own = RoleAssignment.objects.filter(user=board_a, organization=orgs["a"]).first()
    resp = api(board).post(f"/api/orgs/{orgs['a'].pk}/assignments/{own.pk}/reset-mfa/")
    assert resp.status_code == 400


# --- Frage 16: Rollenvergabe durch die Plattform erfährt der Vorstand sofort ---


def test_plattform_vergibt_rolle_vorstand_erfaehrt_es(
    orgs, api, board_a, django_user_model, django_capture_on_commit_callbacks
):
    from audit.models import AuditEntry

    platform_admin = django_user_model.objects.create_superuser(
        email="admin@example.org", password="x"
    )

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        resp = api(platform_admin).post(
            f"/api/platform/orgs/{orgs['a'].pk}/board/",
            {"email": "fremd@example.org"},
            content_type=JSON,
        )
    assert resp.status_code == 201, resp.json()
    to_board = [m for m in mail.outbox if "vorstand-a@example.org" in m.to]
    assert to_board and "Plattform" in to_board[0].subject
    assert "fremd@example.org" in to_board[0].body
    entry = AuditEntry.objects.filter(organization=orgs["a"], action="create").latest("timestamp")
    assert "vergeben durch" in entry.changes


@pytest.mark.django_db
def test_datenschutzhinweise_nennen_geraetekalender(orgs):
    """Fachfrage 19: Termine im Gerätekalender sind für andere Apps mit Kalenderrecht lesbar."""
    from organizations.imprint_generator import unit_privacy

    text = unit_privacy(orgs["a"])
    assert "HUBIplan-App" in text
    assert "andere Apps auf Ihrem Gerät lesen" in text
