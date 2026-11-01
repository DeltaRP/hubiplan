"""Anmeldung an der Nextcloud mit dem HUBIplan-Konto (App oidc, OpenID Connect)."""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.test import Client as HttpClient

from access.models import RoleAssignment
from core.tenancy import tenant_context
from oidc import keys
from oidc.models import Client
from organizations.models import Department, DepartmentRole
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user

JSON = "application/json"
CLOUD = "https://cloud.example.org"
REDIRECT = f"{CLOUD}/apps/user_oidc/code"


@pytest.fixture(autouse=True)
def _key(tmp_path_factory, settings):
    # Ein Schlüssel für alle Tests (RSA anlegen dauert)
    settings.OIDC_KEY_FILE = str(tmp_path_factory.getbasetemp() / "oidc-signing.pem")
    settings.FRONTEND_URL = "https://verein.example.org"
    settings.OIDC_ISSUER = ""
    keys.reset_cache()


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_jwt(token: str) -> dict:
    head, body, sig = token.split(".")
    jwk = HttpClient().get("/api/oidc/jwks").json()["keys"][0]
    assert json.loads(b64d(head))["kid"] == jwk["kid"]
    public = rsa.RSAPublicNumbers(
        int.from_bytes(b64d(jwk["e"]), "big"), int.from_bytes(b64d(jwk["n"]), "big")
    ).public_key()
    public.verify(b64d(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return json.loads(b64d(body))


def make_client(org, **extra) -> tuple[Client, str]:
    with tenant_context(org.pk):
        client = Client(organization=org, base_url=CLOUD, **extra)
        secret = client.set_secret()
        client.save()
    return client, secret


def start(c, client, **extra) -> dict:
    params = {
        "client_id": client.client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": "openid profile email groups",
        "state": "zustand-1",
        "nonce": "einmal-1",
        **extra,
    }
    return c.post("/api/oidc/authorize/", params, content_type=JSON)


def code_of(resp) -> str:
    assert resp.status_code == 200, resp.content
    url = resp.json()["redirect"]
    assert url.startswith(REDIRECT + "?")
    query = parse_qs(urlsplit(url).query)
    assert query["state"] == ["zustand-1"]
    assert query["iss"] == ["https://verein.example.org/api/oidc"]
    return query["code"][0]


def redeem(client, secret, code, **extra):
    auth = base64.b64encode(f"{client.client_id}:{secret}".encode()).decode()
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, **extra}
    return HttpClient(enforce_csrf_checks=True).post(
        "/api/oidc/token", data, HTTP_AUTHORIZATION=f"Basic {auth}"
    )


def test_discovery_und_schluessel(db):
    data = HttpClient().get("/api/oidc/.well-known/openid-configuration").json()
    assert data["issuer"] == "https://verein.example.org/api/oidc"
    assert data["authorization_endpoint"] == "https://verein.example.org/oidc/anmelden"
    assert data["token_endpoint"] == "https://verein.example.org/api/oidc/token"
    assert data["code_challenge_methods_supported"] == ["S256"]
    jwk = HttpClient().get("/api/oidc/jwks").json()["keys"][0]
    assert jwk["kty"] == "RSA" and jwk["alg"] == "RS256" and "d" not in jwk


def test_vorstand_meldet_sich_an(api, orgs, board_a):
    client, secret = make_client(orgs["a"])
    give_role(board_a, orgs["a"], [], name="Kassierer")
    resp = redeem(client, secret, code_of(start(api(board_a), client)))
    assert resp.status_code == 200, resp.content
    assert "no-store" in resp["Cache-Control"]
    data = resp.json()
    assert data["token_type"] == "Bearer" and "refresh_token" not in data
    claims = verify_jwt(data["id_token"])
    assert claims["iss"] == "https://verein.example.org/api/oidc"
    assert claims["aud"] == client.client_id
    assert claims["nonce"] == "einmal-1"
    assert claims["email"] == "vorstand-a@example.org"
    assert claims["groups"] == ["Vorstand", "Kassierer"]
    assert len(claims["sub"]) == 32 and str(board_a.pk) != claims["sub"]

    info = HttpClient().get(
        "/api/oidc/userinfo", HTTP_AUTHORIZATION=f"Bearer {data['access_token']}"
    )
    assert info.status_code == 200
    assert info.json()["sub"] == claims["sub"]
    assert info.json()["groups"] == ["Vorstand", "Kassierer"]
    client.refresh_from_db()
    assert client.last_used_at is not None


def test_kennung_je_dienst_verschieden(api, orgs, board_a):
    one, s1 = make_client(orgs["a"])
    two, s2 = make_client(orgs["a"], name="Zweite")
    c = api(board_a)
    sub1 = verify_jwt(redeem(one, s1, code_of(start(c, one))).json()["id_token"])["sub"]
    sub2 = verify_jwt(redeem(two, s2, code_of(start(c, two))).json()["id_token"])["sub"]
    again = verify_jwt(redeem(one, s1, code_of(start(c, one))).json()["id_token"])["sub"]
    assert sub1 != sub2 and sub1 == again


def test_code_nur_einmal_und_nur_mit_richtigem_geheimnis(api, orgs, board_a):
    client, secret = make_client(orgs["a"])
    code = code_of(start(api(board_a), client))
    wrong = redeem(client, "falsch", code)
    assert wrong.status_code == 401 and wrong.json()["error"] == "invalid_client"
    assert redeem(client, secret, code, redirect_uri=f"{CLOUD}/anders").status_code == 400
    # Ein Fehlversuch mit falscher Rückleitung verbraucht den Code
    assert redeem(client, secret, code).json()["error"] == "invalid_grant"
    code = code_of(start(api(board_a), client))
    assert redeem(client, secret, code).status_code == 200
    assert redeem(client, secret, code).json()["error"] == "invalid_grant"


def test_geheimnis_im_formular(api, orgs, board_a):
    client, secret = make_client(orgs["a"])
    code = code_of(start(api(board_a), client))
    resp = HttpClient().post(
        "/api/oidc/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client.client_id,
            "client_secret": secret,
        },
    )
    assert resp.status_code == 200, resp.content


def test_pkce(api, orgs, board_a):
    client, secret = make_client(orgs["a"])
    verifier = "v" * 50
    challenge = keys.b64url(hashlib.sha256(verifier.encode()).digest())
    c = api(board_a)
    plain = start(c, client, code_challenge=verifier, code_challenge_method="plain")
    assert plain.status_code == 400 and "error=invalid_request" in plain.json()["redirect"]
    code = code_of(start(c, client, code_challenge=challenge, code_challenge_method="S256"))
    assert redeem(client, secret, code, code_verifier="falsch").status_code == 400
    code = code_of(start(c, client, code_challenge=challenge, code_challenge_method="S256"))
    assert redeem(client, secret, code, code_verifier=verifier).status_code == 200


def test_fremde_rueckleitung_nie(api, orgs, board_a):
    client, _ = make_client(orgs["a"])
    resp = start(api(board_a), client, redirect_uri="https://boese.example.org/code")
    assert resp.status_code == 400
    assert resp.json()["redirect"] == ""
    assert (
        api(board_a)
        .get("/api/oidc/authorize/", {"client_id": client.client_id, "redirect_uri": "https://x/"})
        .status_code
        == 400
    )


def test_nur_angemeldet(orgs):
    client, _ = make_client(orgs["a"])
    c = HttpClient()
    assert c.get(
        "/api/oidc/authorize/", {"client_id": client.client_id, "redirect_uri": REDIRECT}
    ).status_code in (401, 403)


def test_beschreibung_fuer_die_seite(api, orgs, board_a):
    client, _ = make_client(orgs["a"])
    resp = api(board_a).get(
        "/api/oidc/authorize/", {"client_id": client.client_id, "redirect_uri": REDIRECT}
    )
    assert resp.json() == {"name": "Nextcloud", "organization": "Verein A", "url": CLOUD}


def test_vorstand_eines_anderen_vereins_kommt_nicht_hinein(api, orgs, board_b):
    client, _ = make_client(orgs["a"])
    resp = start(api(board_b), client)
    assert resp.status_code == 400
    assert "keinen Zugang" in resp.json()["detail"]
    assert resp.json()["back"] == CLOUD


def test_beendete_rolle_zaehlt_nicht(api, orgs):
    client, _ = make_client(orgs["a"])
    user = make_user("frueher@example.org")
    give_role(
        user,
        orgs["a"],
        name="Altvorstand",
        valid_until=datetime.date.today() - datetime.timedelta(days=1),
    )
    assert start(api(user), client).status_code == 400


@pytest.fixture
def zug(orgs):
    with tenant_context(orgs["a"].pk):
        return Department.objects.create(organization=orgs["a"], name="Jäger", founding_year=1950)


@pytest.fixture
def mitglied(orgs, zug):
    membership = make_member(orgs["a"], "Erika", "Muster", departments=[zug])
    user = make_user("erika@example.org")
    with tenant_context(orgs["a"].pk):
        PortalAccess.objects.create(organization=orgs["a"], membership=membership, user=user)
    return {"user": user, "membership": membership}


def test_mitglieder_nur_wenn_eingestellt(api, orgs, mitglied):
    board_only, _ = make_client(orgs["a"])
    resp = start(api(mitglied["user"]), board_only)
    assert resp.status_code == 400
    members, secret = make_client(orgs["a"], audience=Client.Audience.MEMBERS, name="Alle")
    claims = verify_jwt(
        redeem(members, secret, code_of(start(api(mitglied["user"]), members))).json()["id_token"]
    )
    assert claims["groups"] == ["Jäger", "Mitglieder"]
    assert claims["name"] == "Erika Muster"
    assert claims["given_name"] == "Erika" and claims["family_name"] == "Muster"


def test_amt_einer_untereinheit_reicht(api, orgs, zug, mitglied):
    client, secret = make_client(orgs["a"], groups_units=False)
    with tenant_context(orgs["a"].pk):
        role = DepartmentRole.objects.create(department=zug, name="Zugführer")
        RoleAssignment.all_objects.create(
            organization=orgs["a"],
            role=role,
            membership=mitglied["membership"],
            valid_from=datetime.date(2020, 1, 1),
        )
    claims = verify_jwt(
        redeem(client, secret, code_of(start(api(mitglied["user"]), client))).json()["id_token"]
    )
    assert claims["groups"] == ["Zugführer (Jäger)", "Mitglieder"]


def test_zwei_faktor_pflicht(api, orgs, board_a):
    client, _ = make_client(orgs["a"], require_mfa=True)
    resp = start(api(board_a), client)
    assert resp.status_code == 400
    assert "Zwei-Faktor" in resp.json()["detail"]


def test_ausgeschaltet(api, orgs, board_a):
    client, _ = make_client(orgs["a"], is_active=False)
    assert start(api(board_a), client).json()["redirect"] == ""


# --- Einstellungen ---


def test_einstellungen_anlegen_und_geheimnis_erneuern(api, orgs, board_a, board_b):
    c = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}/nextcloud/"
    resp = c.post(
        base, {"name": "Vereinscloud", "base_url": "https://Cloud.example.org/index.php/"}, JSON
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()
    assert data["base_url"] == "https://cloud.example.org"
    assert data["redirect_uri"] == REDIRECT
    assert data["discovery_url"].endswith("/api/oidc/.well-known/openid-configuration")
    secret = data["client_secret"]
    stored = Client.objects.get(pk=data["id"])
    assert stored.check_secret(secret) and secret not in stored.secret_hash
    assert "client_secret" not in c.get(base).json()[0]

    renewed = c.post(f"{base}{data['id']}/secret/").json()["client_secret"]
    stored.refresh_from_db()
    assert stored.check_secret(renewed) and not stored.check_secret(secret)

    # Andere Einheit sieht nichts
    assert api(board_b).get(f"/api/orgs/{orgs['b'].pk}/nextcloud/").json() == []
    assert api(board_b).get(f"{base}").status_code == 404


def test_einstellungen_nur_https(api, orgs, board_a):
    resp = api(board_a).post(
        f"/api/orgs/{orgs['a'].pk}/nextcloud/", {"base_url": "http://cloud.example.org"}, JSON
    )
    assert resp.status_code == 400


def test_einstellungen_brauchen_rollenverwaltung(api, orgs):
    user = make_user("kasse@example.org")
    give_role(user, orgs["a"], ["finance.view"], name="Kasse")
    assert api(user).get(f"/api/orgs/{orgs['a'].pk}/nextcloud/").status_code == 403


def test_mitglieder_nur_bei_vereinen(api, orgs):
    user = make_user("bund@example.org")
    give_role(user, orgs["federation"])
    resp = api(user).post(
        f"/api/orgs/{orgs['federation'].pk}/nextcloud/",
        {"base_url": CLOUD, "audience": "members"},
        JSON,
    )
    assert resp.status_code == 400
