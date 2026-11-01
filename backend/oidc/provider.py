"""HUBIplan als Anmeldedienst nach OpenID Connect (Authorization Code Flow).

Bewusst klein gehalten, damit es sich prüfen lässt:

- nur ``response_type=code``, nur vertrauliche Clients (mit Geheimnis),
- Rückleitung nur an die eingetragene Nextcloud (genauer Vergleich),
- PKCE nur mit S256 (``plain`` wird abgelehnt), optional wie in OAuth 2.0 für Clients
  mit Geheimnis,
- Code 60 Sekunden gültig und nur einmal einlösbar, Zugriffsschlüssel 5 Minuten,
  keine Refresh-Token; beides nur im Cache, nie in der Datenbank,
- ID-Token mit RS256 (``keys``), Angaben siehe ``claims``.

Die Bestätigung, wie sich die Sitzung angemeldet hat (``amr``, ``auth_time``), kommt aus
der Sitzung wie beim Verbund (``peering.sso.session_auth``). Ist beim Dienst die
Zwei-Faktor-Anmeldung verlangt, muss die Sitzung mit zweitem Faktor entstanden sein.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext

from core.tenancy import rls_bypass

from . import claims, keys
from .models import Client

CODE_SECONDS = 60
TOKEN_SECONDS = 300
SCOPES = ("openid", "profile", "email", "groups")
CODE_PREFIX = "oidc:code:"
TOKEN_PREFIX = "oidc:token:"  # noqa: S105 (Cache-Schlüssel, kein Passwort)
MAX_PARAM = 500


class AuthorizeError(Exception):
    """Fehler bei der Anmeldung.

    ``redirect``: Adresse, an die der Browser mit dem Fehler zurück soll (leer: Rückleitung
    nicht vertrauenswürdig, dann nur Meldung in HUBIplan anzeigen).
    """

    def __init__(self, message: str, redirect: str = "", back: str = ""):
        super().__init__(message)
        self.message = message
        self.redirect = redirect
        # Adresse der Nextcloud für den Knopf „Zurück“
        self.back = back


class TokenError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status = status


def issuer() -> str:
    base = getattr(settings, "OIDC_ISSUER", "") or f"{settings.FRONTEND_URL.rstrip('/')}/api/oidc"
    return base.rstrip("/")


def discovery() -> dict:
    iss = issuer()
    front = settings.FRONTEND_URL.rstrip("/")
    return {
        "issuer": iss,
        "authorization_endpoint": f"{front}/oidc/anmelden",
        "token_endpoint": f"{iss}/token",
        "userinfo_endpoint": f"{iss}/userinfo",
        "jwks_uri": f"{iss}/jwks",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["pairwise"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": list(SCOPES),
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": [
            "sub",
            "iss",
            "aud",
            "exp",
            "iat",
            "auth_time",
            "nonce",
            "amr",
            "name",
            "given_name",
            "family_name",
            "preferred_username",
            "email",
            "groups",
        ],
        "authorization_response_iss_parameter_supported": True,
    }


def jwks() -> dict:
    return {"keys": [keys.signing_key().jwk()]}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def find_client(client_id: str) -> Client | None:
    client_id = str(client_id or "")[:64]
    if not client_id:
        return None
    with rls_bypass():
        return (
            Client.objects.select_related("organization")
            .filter(client_id=client_id, is_active=True, organization__is_active=True)
            .first()
        )


def _with_query(url: str, params: dict) -> str:
    parts = urlsplit(url)
    query = urlencode({k: v for k, v in params.items() if v})
    joined = f"{parts.query}&{query}" if parts.query else query
    return urlunsplit((parts.scheme, parts.netloc, parts.path, joined, ""))


def _param(params, name: str) -> str:
    value = params.get(name)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")[:MAX_PARAM]


def describe(params) -> dict:
    """Für die Seite in HUBIplan: welcher Dienst fragt an?"""
    client = find_client(_param(params, "client_id"))
    if client is None or _param(params, "redirect_uri") not in client.redirect_uris:
        raise AuthorizeError(gettext("Diese Anmeldung kennt HUBIplan nicht."))
    return {"name": client.name, "organization": client.organization.name, "url": client.base_url}


def authorize(request, params) -> str:
    """Anmeldung für den angemeldeten Benutzer bestätigen; liefert die Rückleitung mit Code."""
    from peering.sso import session_auth

    client = find_client(_param(params, "client_id"))
    redirect_uri = _param(params, "redirect_uri")
    if client is None or redirect_uri not in client.redirect_uris:
        # Unbekannte Rückleitung nie benutzen (offene Weiterleitung)
        raise AuthorizeError(gettext("Diese Anmeldung kennt HUBIplan nicht."))
    state = _param(params, "state")

    def back(error: str, description: str = "") -> AuthorizeError:
        url = _with_query(
            redirect_uri,
            {"error": error, "error_description": description, "state": state, "iss": issuer()},
        )
        return AuthorizeError(description or error, redirect=url, back=client.base_url)

    if _param(params, "response_type") != "code":
        raise back("unsupported_response_type")
    scopes = _param(params, "scope").split()
    if "openid" not in scopes:
        raise back("invalid_scope", "openid fehlt")
    challenge = _param(params, "code_challenge")
    method = _param(params, "code_challenge_method") or ("plain" if challenge else "")
    if challenge and method != "S256":
        raise back("invalid_request", "Nur PKCE mit S256")
    if _param(params, "prompt") == "none" and not request.user.is_authenticated:
        raise back("login_required")

    user = request.user
    try:
        claims.profile(client, user)
    except claims.NotAllowed as exc:
        raise AuthorizeError(str(exc), back=client.base_url) from exc
    auth = session_auth(request)
    if client.require_mfa and "mfa" not in auth["amr"]:
        from accounts.mfa_policy import has_mfa

        if has_mfa(user):
            message = gettext(
                "Für „{name}“ ist die Zwei-Faktor-Anmeldung nötig. Bitte melde dich bei "
                "HUBIplan ab und mit Passwort und Code wieder an."
            )
        else:
            message = gettext(
                "Für „{name}“ ist die Zwei-Faktor-Anmeldung nötig. Richte sie unter "
                "„Mein Konto“ ein und versuche es dann erneut."
            )
        raise AuthorizeError(message.format(name=client.name), back=client.base_url)

    code = secrets.token_urlsafe(32)
    cache.set(
        CODE_PREFIX + _hash(code),
        {
            "client_id": client.client_id,
            "user_id": user.pk,
            "redirect_uri": redirect_uri,
            "nonce": _param(params, "nonce"),
            "challenge": challenge,
            "scope": [s for s in scopes if s in SCOPES],
            "auth_time": auth["auth_time"] or int(time.time()),
            "amr": auth["amr"],
        },
        CODE_SECONDS,
    )
    return _with_query(redirect_uri, {"code": code, "state": state, "iss": issuer()})


def _client_credentials(request) -> tuple[str, str]:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.lower().startswith("basic "):
        try:
            raw = base64.b64decode(header[6:].strip(), validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenError("invalid_client", status=401) from exc
        client_id, _, secret = raw.partition(":")
        # RFC 6749 2.3.1: beide Teile sind formular-kodiert
        return unquote(client_id.replace("+", " ")), unquote(secret.replace("+", " "))
    return str(request.POST.get("client_id") or ""), str(request.POST.get("client_secret") or "")


def _authenticate_client(request) -> Client:
    client_id, secret = _client_credentials(request)
    client = find_client(client_id)
    if client is None or not client.check_secret(secret):
        raise TokenError("invalid_client", status=401)
    return client


def _user(user_id):
    from accounts.models import User

    return User.objects.filter(pk=user_id, is_active=True).first()


def _pkce_ok(challenge: str, verifier: str) -> bool:
    if not challenge:
        return True
    digest = keys.b64url(hashlib.sha256(verifier.encode()).digest())
    return secrets.compare_digest(digest, challenge)


def token(request) -> dict:
    client = _authenticate_client(request)
    if request.POST.get("grant_type") != "authorization_code":
        raise TokenError("unsupported_grant_type")
    code = str(request.POST.get("code") or "")[:MAX_PARAM]
    key = CODE_PREFIX + _hash(code)
    data = cache.get(key) if code else None
    # Nur einmal einlösbar: Wer den Eintrag nicht selbst löscht, war zu spät
    if data is None or not cache.delete(key):
        raise TokenError("invalid_grant")
    if data["client_id"] != client.client_id or data["redirect_uri"] != str(
        request.POST.get("redirect_uri") or ""
    ):
        raise TokenError("invalid_grant")
    if not _pkce_ok(data["challenge"], str(request.POST.get("code_verifier") or "")):
        raise TokenError("invalid_grant")
    user = _user(data["user_id"])
    if user is None:
        raise TokenError("invalid_grant")
    try:
        prof = claims.profile(client, user)
    except claims.NotAllowed as exc:
        raise TokenError("invalid_grant") from exc

    now = int(time.time())
    id_claims = {
        "iss": issuer(),
        "sub": claims.subject(client, user),
        "aud": client.client_id,
        "azp": client.client_id,
        "iat": now,
        "exp": now + TOKEN_SECONDS,
        "auth_time": data["auth_time"],
        "amr": data["amr"],
        **_scoped(prof, data["scope"]),
    }
    if data["nonce"]:
        id_claims["nonce"] = data["nonce"]
    access = secrets.token_urlsafe(32)
    cache.set(
        TOKEN_PREFIX + _hash(access),
        {"client_id": client.client_id, "user_id": user.pk, "scope": data["scope"]},
        TOKEN_SECONDS,
    )
    with rls_bypass():
        Client.objects.filter(pk=client.pk).update(last_used_at=timezone.now())
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": TOKEN_SECONDS,
        "scope": " ".join(data["scope"]),
        "id_token": keys.jwt(id_claims),
    }


def _scoped(prof: claims.Profile, scope: list[str]) -> dict:
    out: dict = {}
    if "profile" in scope:
        out.update(name=prof.name, given_name=prof.given_name, family_name=prof.family_name)
        if prof.username:
            out["preferred_username"] = prof.username
    if "email" in scope:
        out["email"] = prof.email
    if "groups" in scope:
        out["groups"] = prof.groups
    return out


def userinfo(request) -> dict:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        raise TokenError("invalid_token", status=401)
    data = cache.get(TOKEN_PREFIX + _hash(header[7:].strip()))
    if data is None:
        raise TokenError("invalid_token", status=401)
    client = find_client(data["client_id"])
    user = _user(data["user_id"])
    if client is None or user is None:
        raise TokenError("invalid_token", status=401)
    try:
        prof = claims.profile(client, user)
    except claims.NotAllowed as exc:
        raise TokenError("invalid_token", status=401) from exc
    return {"sub": claims.subject(client, user), **_scoped(prof, data["scope"])}
