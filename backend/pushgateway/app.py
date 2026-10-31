"""Push-Gateway: nimmt verschlüsselte Web-Pushes von HUBIplan-Instanzen an und reicht sie an
Firebase Cloud Messaging (FCM) weiter.

Nur die Play-Fassung der App braucht es: FCM nimmt Nachrichten nur mit dem Schlüssel des
App-Herausgebers an, und den sollen die einzelnen Instanzen nicht kennen. Das Gateway sieht
keinen Inhalt (der Web-Push ist für das Gerät verschlüsselt, RFC 8291) und speichert nichts;
das Protokoll enthält nur Statuscodes.

Schnittstelle (RFC 8030): ``POST /fcm/<FCM-Token>/<Kennung>`` mit ``Content-Encoding:
aes128gcm``, ``Urgency``, ``TTL`` und gültigem VAPID-Kopf (RFC 8292). Antwort 201, bei
unbekanntem Gerät 410 (dann entfernt die Instanz den Endpunkt).

Die Kennung sind die ersten 16 Zeichen (hex) von SHA-256 über den öffentlichen
VAPID-Schlüssel der Instanz, mit der sich das Gerät verbunden hat (Härtung H5). Nur
Nachrichten mit genau diesem Schlüssel gehen weiter: Wer den Endpunkt kennt, kann damit
keine eigenen Nachrichten an das Telefon schicken. Endpunkte ohne Kennung (App vor 0.14)
nimmt das Gateway an, solange ``PUSH_GATEWAY_ALLOW_UNBOUND`` nicht ``0`` ist.

Start: ``gunicorn pushgateway.app:application``. Einstellungen über Umgebungsvariablen:

- ``PUSH_GATEWAY_PUBLIC_URL``: eigene Adresse (``https://push.example.org``), Pflicht für die
  VAPID-Prüfung (``aud``)
- ``PUSH_GATEWAY_FCM_CREDENTIALS``: Datei mit dem Dienstkonto-Schlüssel (JSON) des
  Firebase-Projekts
- ``PUSH_GATEWAY_RATE``: Nachrichten je Minute und Absender (VAPID-Schlüssel), Standard 600
- ``PUSH_GATEWAY_RATE_TOKEN``: je Minute und Gerät, Standard 30
- ``PUSH_GATEWAY_RATE_IP``: je Minute und IP, Standard 1200
- ``PUSH_GATEWAY_TRUST_PROXY``: ``1``, wenn ein Webserver davor ``X-Forwarded-For`` setzt
- ``PUSH_GATEWAY_ALLOW_UNBOUND``: ``0`` lehnt Endpunkte ohne Kennung ab (Standard ``1``)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

logger = logging.getLogger("pushgateway")

# Größter verschlüsselter Inhalt: base64 muss in die 4 KB Daten einer FCM-Nachricht passen
MAX_BODY = 2800
MAX_TTL = 4 * 24 * 60 * 60
# VAPID-Token dürfen höchstens 24 Stunden gelten (RFC 8292, Abschnitt 2)
MAX_JWT_LIFETIME = 24 * 60 * 60
TOKEN_RE = re.compile(r"^[A-Za-z0-9_:\-]{20,400}$")
KID_RE = re.compile(r"^[0-9a-f]{16}$")
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TIMEOUT = 10


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- VAPID prüfen (RFC 8292) ---


class Rejected(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def check_vapid(header: str, audience: str, now: float | None = None) -> str:
    """Prüft ``Authorization: vapid t=…, k=…``; gibt den öffentlichen Schlüssel ``k`` zurück."""
    if not header.lower().startswith("vapid "):
        raise Rejected(401, "VAPID fehlt")
    params = {}
    for part in header[6:].split(","):
        name, _, value = part.strip().partition("=")
        params[name.strip()] = value.strip()
    token, key = params.get("t", ""), params.get("k", "")
    try:
        raw_key = _unb64(key)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw_key)
        head, body, sig = token.split(".")
        claims = json.loads(_unb64(body))
        signature = _unb64(sig)
        if json.loads(_unb64(head)).get("alg") != "ES256" or len(signature) != 64:
            raise ValueError("alg")
    except (ValueError, TypeError) as exc:
        raise Rejected(401, "VAPID ungültig") from exc
    der = encode_dss_signature(
        int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    )
    try:
        public.verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise Rejected(401, "VAPID-Signatur falsch") from exc
    now = time.time() if now is None else now
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp < now or exp > now + MAX_JWT_LIFETIME:
        raise Rejected(401, "VAPID abgelaufen")
    if claims.get("aud") != audience:
        raise Rejected(401, "VAPID für andere Adresse")
    return key


def key_id(vapid_key: str) -> str:
    """Kennung eines VAPID-Schlüssels (b64url, 65 Byte) für den Endpunkt."""
    return hashlib.sha256(_unb64(vapid_key)).hexdigest()[:16]


# --- Begrenzung je Absender ---


class RateLimit:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            if len(self.hits) > 10_000:
                self.hits.clear()
            q = self.hits.setdefault(key, deque())
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


# --- FCM (HTTP v1) ---


@dataclass
class FcmResult:
    status: int
    # Gerät unbekannt oder abgemeldet: Instanz soll den Endpunkt löschen
    gone: bool = False


class Fcm:
    """Zugriff auf FCM mit einem Dienstkonto; das Zugriffstoken wird zwischengespeichert."""

    def __init__(self, credentials: dict):
        self.project = credentials["project_id"]
        self.email = credentials["client_email"]
        self.token_uri = credentials.get("token_uri") or "https://oauth2.googleapis.com/token"
        self.key = serialization.load_pem_private_key(
            credentials["private_key"].encode(), password=None
        )
        self._token = ""
        self._until = 0.0
        self.lock = threading.Lock()

    @classmethod
    def from_file(cls, path: str) -> Fcm:
        with open(path) as fh:
            return cls(json.load(fh))

    def _assertion(self, now: int) -> str:
        head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = {
            "iss": self.email,
            "scope": FCM_SCOPE,
            "aud": self.token_uri,
            "iat": now,
            "exp": now + 3600,
        }
        body = _b64(json.dumps(claims).encode())
        sig = self.key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{body}.{_b64(sig)}"

    def access_token(self) -> str:
        with self.lock:
            if self._token and time.time() < self._until:
                return self._token
            now = int(time.time())
            form = urllib.parse.urlencode(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": self._assertion(now),
                }
            ).encode()
            status, data = http_post(
                self.token_uri, {"Content-Type": "application/x-www-form-urlencoded"}, form
            )
            if status != 200 or "access_token" not in data:
                raise RuntimeError(f"Google-Anmeldung fehlgeschlagen (HTTP {status})")
            self._token = data["access_token"]
            self._until = now + int(data.get("expires_in", 3600)) - 300
            return self._token

    def send(self, token: str, body: bytes, *, urgent: bool, ttl: int) -> FcmResult:
        message = {
            "message": {
                "token": token,
                "data": {"b": base64.b64encode(body).decode()},
                "android": {"priority": "HIGH" if urgent else "NORMAL", "ttl": f"{ttl}s"},
            }
        }
        url = f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send"
        headers = {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": "application/json",
        }
        status, data = http_post(url, headers, json.dumps(message).encode())
        if status == 200:
            return FcmResult(201)
        code = ""
        for detail in (data.get("error") or {}).get("details") or []:
            code = detail.get("errorCode") or code
        if status == 404 or code == "UNREGISTERED":
            return FcmResult(410, gone=True)
        if code == "INVALID_ARGUMENT" or status == 400:
            return FcmResult(404, gone=True)
        if status in (429, 503):
            return FcmResult(429)
        return FcmResult(502)


def http_post(url: str, headers: dict, body: bytes) -> tuple[int, dict]:
    """HTTP-Aufruf zu Google (in Tests ersetzt)."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:  # noqa: S310
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return 503, {}
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {}


# --- WSGI-Anwendung ---


class Gateway:
    def __init__(
        self,
        public_url: str,
        fcm: Fcm | None,
        rate: int = 600,
        *,
        rate_token: int = 30,
        rate_ip: int = 1200,
        allow_unbound: bool = True,
        trust_proxy: bool = False,
    ):
        parts = urllib.parse.urlsplit(public_url)
        self.audience = f"{parts.scheme}://{parts.netloc}"
        self.fcm = fcm
        self.limit = RateLimit(rate)
        self.limit_token = RateLimit(rate_token)
        self.limit_ip = RateLimit(rate_ip)
        self.allow_unbound = allow_unbound
        self.trust_proxy = trust_proxy

    def handle(
        self, method: str, path: str, headers: dict, body: bytes, ip: str = ""
    ) -> tuple[int, dict]:
        if path == "/health":
            return 200, {"status": "ok", "fcm": self.fcm is not None}
        if not path.startswith("/fcm/"):
            return 404, {}
        if method != "POST":
            return 405, {}
        token, _, kid = path[len("/fcm/") :].partition("/")
        if not TOKEN_RE.match(token) or (kid and not KID_RE.match(kid)):
            return 404, {}
        if not kid and not self.allow_unbound:
            return 404, {}
        if ip and not self.limit_ip.allow(f"ip:{ip}"):
            return 429, {}
        if len(body) > MAX_BODY:
            return 413, {}
        if headers.get("content-encoding", "").lower() != "aes128gcm" or len(body) < 103:
            return 415, {}
        try:
            sender = check_vapid(headers.get("authorization", ""), self.audience)
        except Rejected as exc:
            return exc.status, {"reason": exc.reason}
        if kid and key_id(sender) != kid:
            # Endpunkt gehört zu einer anderen Instanz
            return 403, {"reason": "anderer Absender"}
        if not self.limit.allow(sender) or not self.limit_token.allow(f"t:{token}"):
            return 429, {}
        if self.fcm is None:
            return 503, {}
        try:
            ttl = max(0, min(int(headers.get("ttl", "0")), MAX_TTL))
        except ValueError:
            return 400, {}
        urgent = headers.get("urgency", "normal").lower() == "high"
        try:
            result = self.fcm.send(token, body, urgent=urgent, ttl=ttl)
        except RuntimeError as exc:
            logger.warning("%s", exc)
            return 503, {}
        return result.status, {}

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        headers = {
            k[5:].replace("_", "-").lower(): v for k, v in environ.items() if k.startswith("HTTP_")
        }
        if environ.get("CONTENT_TYPE"):
            headers["content-type"] = environ["CONTENT_TYPE"]
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        body = environ["wsgi.input"].read(min(length, MAX_BODY + 1)) if length else b""
        if length > MAX_BODY:
            body = b"x" * (MAX_BODY + 1)
        ip = environ.get("REMOTE_ADDR", "")
        if self.trust_proxy and headers.get("x-forwarded-for"):
            ip = headers["x-forwarded-for"].split(",")[-1].strip()
        status, data = self.handle(method, path, headers, body, ip)
        if path.startswith("/fcm/"):
            logger.info("%s %s", method, status)
        payload = json.dumps(data).encode()
        reason = {200: "OK", 201: "Created"}.get(status, "")
        start_response(
            f"{status} {reason}".strip(),
            [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))],
        )
        return [payload]


def create() -> Gateway:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    public_url = os.environ.get("PUSH_GATEWAY_PUBLIC_URL", "")
    if not public_url.startswith("https://"):
        raise RuntimeError("PUSH_GATEWAY_PUBLIC_URL muss eine https-Adresse sein.")
    path = os.environ.get("PUSH_GATEWAY_FCM_CREDENTIALS", "")
    fcm = Fcm.from_file(path) if path else None
    if fcm is None:
        logger.warning("Kein FCM-Dienstkonto: Nachrichten werden abgelehnt (503).")
    env = os.environ.get
    return Gateway(
        public_url,
        fcm,
        int(env("PUSH_GATEWAY_RATE", "600")),
        rate_token=int(env("PUSH_GATEWAY_RATE_TOKEN", "30")),
        rate_ip=int(env("PUSH_GATEWAY_RATE_IP", "1200")),
        allow_unbound=env("PUSH_GATEWAY_ALLOW_UNBOUND", "1") != "0",
        trust_proxy=env("PUSH_GATEWAY_TRUST_PROXY", "0") == "1",
    )


def __getattr__(name):
    # gunicorn pushgateway.app:application: erst beim Zugriff erzeugen (Tests ohne Umgebung)
    if name == "application":
        return create()
    raise AttributeError(name)
