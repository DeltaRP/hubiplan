"""Android-App, Schritt A8/B1: Vorstandszugang und offene Aufgaben in der App."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import datetime

import pytest
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.test import Client
from django.utils import timezone

from core.tenancy import tenant_context
from devices.models import Device
from portal.models import ChangeRequest

from .factories import PASSWORD, give_role
from .test_app_devices import APP, app, pair, pairing_code
from .test_auth import totp_code
from .test_m12_events import JSON, cal, member_with_access  # noqa: F401

pytestmark = pytest.mark.django_db
ADMIN = f"{APP}admin/"


@pytest.fixture
def board(cal, api):
    """Vorstand von Verein a, selbst Mitglied, mit App und 2FA."""
    m, user, access = member_with_access(cal["a"], "Vera")
    give_role(user, cal["a"], ["members.view", "members.edit"], name="Schriftführung")
    secret = generate_totp_secret()
    TOTP.activate(user, secret)
    resp = pair(pairing_code(api(user)))
    assert resp.status_code == 201, resp.json()
    return {"user": user, "membership": m, "token": resp.json()["token"], "secret": secret}


def fresh_code(secret: str) -> str:
    """Code nicht kurz vor dem Wechsel des 30-Sekunden-Fensters (sonst ungültig beim Prüfen)."""
    import time

    if time.time() % 30 > 28:
        time.sleep(30 - time.time() % 30 + 0.1)
    return totp_code(secret)


def unlock(board, password=PASSWORD, code=None):
    return app(board["token"]).post(
        f"{ADMIN}unlock/",
        {"password": password, "code": code or fresh_code(board["secret"])},
        content_type=JSON,
    )


@pytest.fixture
def admin_token(board):
    from django.core.cache import cache

    # Begrenzung und genutzte Codes liegen im Cache: jeder Test fängt frisch an
    cache.clear()
    resp = unlock(board)
    assert resp.status_code == 201, resp.json()
    return resp.json()["token"]


class TestUeberblick:
    def test_einheiten_mit_rechten(self, board, cal):
        data = app(board["token"]).get(ADMIN).json()
        assert data["two_factor"] is True and data["unlocked"] is False
        unit = next(u for u in data["units"] if u["id"] == cal["a"].pk)
        assert unit["permissions"] == ["members.edit", "members.view"]

    def test_mitglied_ohne_rechte(self, cal, api):
        _, user, _ = member_with_access(cal["a"], "Otto")
        token = pair(pairing_code(api(user))).json()["token"]
        assert app(token).get(ADMIN).json()["units"] == []
        resp = app(token).post(
            f"{ADMIN}unlock/", {"password": PASSWORD, "code": "1"}, content_type=JSON
        )
        assert resp.status_code == 400


class TestFreischalten:
    def test_passwort_und_code(self, board, admin_token):
        assert admin_token.startswith("hpa_")
        device = Device.objects.get(user=board["user"])
        assert device.admin_active
        assert device.admin_until > timezone.now() + datetime.timedelta(days=29)
        assert app(board["token"]).get(ADMIN).json()["unlocked"] is True

    def test_falsches_passwort_oder_code(self, board):
        assert unlock(board, password="falsch").status_code == 400
        assert unlock(board, code="000000").status_code == 400
        assert not Device.objects.get(user=board["user"]).admin_token_hash

    def test_ohne_2fa_nicht(self, board):
        from allauth.mfa.models import Authenticator

        Authenticator.objects.filter(user=board["user"]).delete()
        resp = unlock(board)
        assert resp.status_code == 400
        assert "Zwei-Faktor" in resp.json()["detail"]

    def test_mail_bei_freischaltung_und_fehlversuchen(
        self, board, django_capture_on_commit_callbacks
    ):
        from django.core import mail
        from django.core.cache import cache

        cache.clear()
        mail.outbox.clear()
        for _ in range(4):
            unlock(board, password="falsch")
        subjects = [m.subject for m in mail.outbox]
        assert "Fehlgeschlagene Freischaltung der Verwaltung" in subjects
        mail.outbox.clear()
        cache.clear()
        with django_capture_on_commit_callbacks(execute=True):
            assert unlock(board).status_code == 201
        assert [m.subject for m in mail.outbox] == ["Verwaltung in der App freigeschaltet"]

    def test_versuche_begrenzt(self, board):
        for _ in range(5):
            unlock(board, password="falsch")
        assert unlock(board).status_code == 429


class TestVorstandsschluessel:
    def test_nur_mit_geraeteschluessel(self, board, admin_token, cal, api):
        url = f"{ADMIN}u/{cal['a'].pk}/tasks/"
        assert app(admin_token, with_device=False).get(url).status_code == 401
        other = pair(pairing_code(api(board["user"]))).json()["token"]
        c = Client(HTTP_AUTHORIZATION=f"Bearer {admin_token}", HTTP_X_HUBIPLAN_DEVICE=other)
        assert c.get(url).status_code == 401
        assert app(admin_token).get(url).status_code == 200

    def test_offene_aufgaben(self, board, admin_token, cal):
        with tenant_context(cal["a"].pk):
            ChangeRequest.objects.create(
                organization=cal["a"], membership=board["membership"], data={"city": "Neustadt"}
            )
        resp = app(admin_token).get(f"{ADMIN}u/{cal['a'].pk}/tasks/")
        assert resp.status_code == 200, resp.json()
        assert len(resp.json()["items"]) == 1

    def test_fremde_einheit_nicht(self, admin_token, cal):
        assert app(admin_token).get(f"{ADMIN}u/{cal['b'].pk}/tasks/").status_code == 404

    def test_geraeteschluessel_reicht_nicht(self, board, cal):
        resp = app(board["token"]).get(f"{ADMIN}u/{cal['a'].pk}/tasks/")
        assert resp.status_code == 401

    def test_vorstandsschluessel_nur_fuer_verwaltung(self, admin_token):
        assert app(admin_token).get(f"{APP}me/").status_code in (401, 403)
        assert app(admin_token).get("/api/me/contexts/").status_code in (401, 403)

    def test_abgelaufen_und_ungenutzt(self, board, admin_token, cal):
        url = f"{ADMIN}u/{cal['a'].pk}/tasks/"
        Device.objects.update(admin_until=timezone.now() - datetime.timedelta(minutes=1))
        resp = app(admin_token).get(url)
        assert resp.status_code == 401
        assert "freischalten" in resp.json()["detail"]
        Device.objects.update(
            admin_until=timezone.now() + datetime.timedelta(days=10),
            admin_used_at=timezone.now() - datetime.timedelta(days=15),
        )
        assert app(admin_token).get(url).status_code == 401

    def test_rolle_entzogen(self, board, admin_token, cal):
        from access.models import RoleAssignment

        RoleAssignment.objects.filter(user=board["user"]).delete()
        assert app(admin_token).get(f"{ADMIN}u/{cal['a'].pk}/tasks/").status_code == 404

    def test_sperren_in_der_app_und_im_browser(self, board, admin_token, cal, api):
        url = f"{ADMIN}u/{cal['a'].pk}/tasks/"
        assert app(board["token"]).delete(f"{ADMIN}unlock/").json()["unlocked"] is False
        assert app(admin_token).get(url).status_code == 401
        # erneut freischalten (ein Code gilt nur einmal: Speicher der genutzten Codes leeren)
        from django.core.cache import cache

        cache.clear()
        token = unlock(board).json()["token"]
        device = Device.objects.get(user=board["user"])
        listed = api(board["user"]).get(f"{APP}devices/").json()
        assert listed[0]["admin_until"] is not None
        resp = api(board["user"]).delete(f"{APP}devices/{device.pk}/admin/")
        assert resp.status_code == 200 and resp.json()["admin_until"] is None
        assert app(token).get(url).status_code == 401
        # Gerät bleibt für den Mitgliederbereich angemeldet
        assert app(board["token"]).get(f"{APP}me/").status_code == 200

    def test_geraet_abgemeldet(self, board, admin_token, cal):
        Device.objects.update(revoked_at=timezone.now())
        assert app(admin_token).get(f"{ADMIN}u/{cal['a'].pk}/tasks/").status_code == 401
