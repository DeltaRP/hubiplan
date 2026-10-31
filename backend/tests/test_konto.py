"""Mein Konto: Name, Passwort und Anmelde-E-Mail selbst ändern."""

import re

import pytest
from allauth.account.models import EmailAddress
from django.core import mail as djmail
from django.test import Client

from accounts.models import EmailChange, User

from .factories import PASSWORD, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
SESSION = "/_allauth/browser/v1/auth/session"


def test_name_aendern(api):
    u = make_user("karla@example.org")
    resp = api(u).patch("/api/me/account/", {"first_name": "Karla"}, content_type=JSON)
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Karla"
    assert resp.json()["has_password"] is True


def test_passwort_aendern_bleibt_angemeldet(api):
    u = make_user("karla@example.org")
    c = api(u)
    r = c.post(
        "/api/me/password/", {"current_password": "falsch", "new_password": "x"}, content_type=JSON
    )
    assert r.status_code == 400 and "current_password" in r.json()
    r = c.post(
        "/api/me/password/",
        {"current_password": PASSWORD, "new_password": "kurz"},
        content_type=JSON,
    )
    assert r.status_code == 400 and "new_password" in r.json()
    r = c.post(
        "/api/me/password/",
        {"current_password": PASSWORD, "new_password": "Ganz-Neues-Passwort-42"},
        content_type=JSON,
    )
    assert r.status_code == 200
    assert c.get("/api/me/").status_code == 200  # Sitzung bleibt gültig
    u.refresh_from_db()
    assert u.check_password("Ganz-Neues-Passwort-42")
    assert any(u.email in m.to for m in djmail.outbox)


def test_passwort_erstmals_festlegen(api):
    u = User.objects.create_user(email="link@example.org", password=None)
    r = api(u).get("/api/me/account/")
    assert r.json()["has_password"] is False
    r = api(u).post(
        "/api/me/password/", {"new_password": "Ganz-Neues-Passwort-42"}, content_type=JSON
    )
    assert r.status_code == 200 and r.json()["has_password"] is True


def test_email_aendern_mit_bestaetigung(api):
    u = make_user("alt@example.org")
    EmailAddress.objects.create(user=u, email="alt@example.org", primary=True, verified=True)
    make_user("vergeben@example.org")
    c = api(u)
    r = c.post(
        "/api/me/email/", {"email": "vergeben@example.org", "password": PASSWORD}, content_type=JSON
    )
    assert r.status_code == 400
    r = c.post(
        "/api/me/email/", {"email": "neu@example.org", "password": "falsch"}, content_type=JSON
    )
    assert r.status_code == 400 and "password" in r.json()
    r = c.post(
        "/api/me/email/", {"email": "Neu@Example.org", "password": PASSWORD}, content_type=JSON
    )
    assert r.status_code == 201, r.json()
    assert r.json()["pending_email"] == "neu@example.org"
    u.refresh_from_db()
    assert u.email == "alt@example.org"  # erst nach Bestätigung
    confirm = next(m for m in djmail.outbox if "neu@example.org" in m.to)
    token = re.search(r"/konto/email/([\w-]+)", confirm.body).group(1)
    assert any("alt@example.org" in m.to for m in djmail.outbox)

    anon = Client()
    assert anon.post("/api/public/email-confirm/falsch/").status_code == 404
    r = anon.post(f"/api/public/email-confirm/{token}/")
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.email == "neu@example.org"
    assert not EmailAddress.objects.filter(email="alt@example.org").exists()
    assert anon.post(f"/api/public/email-confirm/{token}/").status_code == 404
    assert EmailChange.objects.get().used_at is not None

    # Anmeldung mit neuer Adresse klappt, mit alter nicht
    login = "/_allauth/browser/v1/auth/login"
    assert (
        Client()
        .post(login, {"email": "neu@example.org", "password": PASSWORD}, content_type=JSON)
        .status_code
        == 200
    )
    assert (
        Client()
        .post(login, {"email": "alt@example.org", "password": PASSWORD}, content_type=JSON)
        .status_code
        == 400
    )


def test_ohne_anmeldung_kein_zugriff():
    c = Client()
    assert c.get("/api/me/account/").status_code in (401, 403)
    assert c.post("/api/me/password/", {}, content_type=JSON).status_code in (401, 403)
