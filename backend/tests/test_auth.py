"""Anmeldung per E-Mail/Passwort und optionale 2FA per TOTP über die Headless-API."""

import time

import pytest
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, hotp_value

from .conftest import csrf_headers

AUTH = "/_allauth/browser/v1"


def totp_code(secret: str) -> str:
    return format_hotp_value(hotp_value(secret, int(time.time()) // 30))


def login(client, email, password):
    return client.post(
        f"{AUTH}/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
        headers=csrf_headers(client),
    )


def pending_flow(response) -> str | None:
    flows = response.json().get("data", {}).get("flows", [])
    return next((f["id"] for f in flows if f.get("is_pending")), None)


@pytest.mark.django_db
class TestLogin:
    def test_login_ohne_2fa(self, client, user, password):
        response = login(client, "kassenwart@example.org", password)
        assert response.status_code == 200
        assert response.json()["meta"]["is_authenticated"] is True

        me = client.get("/api/me/")
        assert me.status_code == 200
        assert me.json()["email"] == "kassenwart@example.org"

    def test_email_gross_klein_egal(self, client, user, password):
        response = login(client, "Kassenwart@Example.org", password)
        assert response.status_code == 200

    def test_falsches_passwort(self, client, user):
        response = login(client, "kassenwart@example.org", "falsch")
        assert response.status_code == 400
        assert client.get("/api/me/").status_code == 403

    def test_unbekannte_email(self, client, db, password):
        response = login(client, "niemand@example.org", password)
        assert response.status_code == 400

    def test_ohne_csrf_abgelehnt(self, client, user, password):
        response = client.post(
            f"{AUTH}/auth/login",
            {"email": "kassenwart@example.org", "password": password},
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_abmelden(self, client, user, password):
        login(client, "kassenwart@example.org", password)
        response = client.delete(f"{AUTH}/auth/session", headers=csrf_headers(client))
        assert response.status_code == 401
        assert client.get("/api/me/").status_code == 403

    def test_selbstregistrierung_gesperrt(self, client, db, password):
        response = client.post(
            f"{AUTH}/auth/signup",
            {"email": "neu@example.org", "password": password},
            content_type="application/json",
            headers=csrf_headers(client),
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestZweiFaktor:
    @pytest.fixture
    def totp_secret(self, user) -> str:
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        TOTP.activate(user, secret)
        return secret

    def test_login_verlangt_2fa(self, client, user, password, totp_secret):
        response = login(client, "kassenwart@example.org", password)
        assert response.status_code == 401
        assert pending_flow(response) == "mfa_authenticate"
        # Noch nicht angemeldet
        assert client.get("/api/me/").status_code == 403

        response = client.post(
            f"{AUTH}/auth/2fa/authenticate",
            {"code": totp_code(totp_secret)},
            content_type="application/json",
            headers=csrf_headers(client),
        )
        assert response.status_code == 200
        assert response.json()["meta"]["is_authenticated"] is True
        assert client.get("/api/me/").status_code == 200

    def test_falscher_code(self, client, user, password, totp_secret):
        login(client, "kassenwart@example.org", password)
        response = client.post(
            f"{AUTH}/auth/2fa/authenticate",
            {"code": "000000"},
            content_type="application/json",
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert client.get("/api/me/").status_code == 403

    def test_2fa_einrichten(self, client, user, password, settings):
        # Code und Prüfung können in verschiedene 30-Sekunden-Fenster fallen
        # (lokal einmal rot): ein Fenster Toleranz macht den Test zeitunabhängig.
        settings.MFA_TOTP_TOLERANCE = 1
        login(client, "kassenwart@example.org", password)

        response = client.get(f"{AUTH}/account/authenticators/totp")
        assert response.status_code == 404  # noch nicht eingerichtet
        meta = response.json()["meta"]
        secret = meta["secret"]
        assert meta["totp_url"].startswith("otpauth://totp/")

        activate = {
            "path": f"{AUTH}/account/authenticators/totp",
            "data": {"code": totp_code(secret)},
            "content_type": "application/json",
        }
        # Sicherheitsänderung: erst Passwort erneut bestätigen
        response = client.post(**activate, headers=csrf_headers(client))
        assert response.status_code == 401
        assert pending_flow(response) is None
        flows = [f["id"] for f in response.json()["data"]["flows"]]
        assert "reauthenticate" in flows

        response = client.post(
            f"{AUTH}/auth/reauthenticate",
            {"password": password},
            content_type="application/json",
            headers=csrf_headers(client),
        )
        assert response.status_code == 200

        # Code frisch berechnen: dazwischen kann ein 30-Sekunden-Fenster enden
        activate["data"] = {"code": totp_code(secret)}
        response = client.post(**activate, headers=csrf_headers(client))
        assert response.status_code == 200
        assert Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists()
        # Wiederherstellungscodes werden automatisch erzeugt
        assert Authenticator.objects.filter(
            user=user, type=Authenticator.Type.RECOVERY_CODES
        ).exists()
