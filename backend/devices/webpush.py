"""Web-Push an die HUBIplan-App (RFC 8030, verschlüsselt nach RFC 8291, VAPID nach RFC 8292).

Die App meldet einen Push-Endpunkt (UnifiedPush-Verteiler wie ntfy oder später
das Push-Gateway der Play-Variante) und zwei Schlüssel (``p256dh``, ``auth``).
HUBIplan verschlüsselt jede Nachricht mit diesen Schlüsseln. Der Push-Dienst
sieht nur Gerät, Zeit und Größe, keinen Inhalt.

Der VAPID-Schlüssel der Instanz liegt als Datei im privaten Speicher (wie der
Schlüssel des Verbunds) und wird beim ersten Gebrauch erzeugt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import struct
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.utils.translation import gettext

# Nur für die App (Eigentümer) und die Gruppe lesbar: Der Backup-Container gehört zur
# Gruppe der App (group_add in docker-compose.server.yml) und muss die Datei mitsichern.
# Mit 0600 brach die Dateiliste des Backups ab (Testserver 31.10.2026).
KEY_FILE_MODE = 0o640

FORMAT = "hubiplan-vapid"
RECORD_SIZE = 4096
# Größte Nutzlast (Klartext); darüber geht nur „Neues von HUBIplan“ hinaus
MAX_PAYLOAD = 3000
# Über das Push-Gateway (FCM, 4 KB je Nachricht, base64): kleiner
MAX_PAYLOAD_FCM = 2600
TIMEOUT = 10
TTL = 24 * 60 * 60


class PushError(Exception):
    """Push nicht zustellbar (Netz, Dienst, ungültiger Endpunkt)."""


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- Schlüssel prüfen ---


def valid_p256dh(value: str) -> bool:
    try:
        raw = unb64(value)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except (ValueError, TypeError):
        return False
    return len(raw) == 65


def valid_auth(value: str) -> bool:
    try:
        return len(unb64(value)) == 16
    except (ValueError, TypeError):
        return False


def check_endpoint(url: str) -> None:
    """Nur https und keine internen Adressen (Schutz vor Missbrauch des Servers)."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise PushError(gettext("Push-Endpunkt muss eine https-Adresse sein."))
    if getattr(settings, "PUSH_ALLOW_INTERNAL", False):
        return
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise PushError(
            gettext("{hostname} ist nicht auflösbar.").format(hostname=parts.hostname)
        ) from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise PushError(
                gettext("{hostname} zeigt auf eine interne Adresse.").format(
                    hostname=parts.hostname
                )
            )


# --- VAPID-Schlüssel der Instanz ---


def key_path() -> Path:
    configured = getattr(settings, "PUSH_VAPID_KEY_FILE", "")
    return Path(configured) if configured else Path(settings.PRIVATE_ROOT) / "push" / "vapid.json"


_cache: dict[str, ec.EllipticCurvePrivateKey] = {}


def _create(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    data = {"format": FORMAT, "private_key": b64(raw)}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, KEY_FILE_MODE)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    try:
        # Schneller war ein anderer Prozess: dann gilt dessen Datei
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def vapid_key() -> ec.EllipticCurvePrivateKey:
    path = key_path()
    cached = _cache.get(str(path))
    if cached is not None:
        return cached
    if not path.exists():
        _create(path)
    data = json.loads(path.read_text())
    if data.get("format") != FORMAT:
        raise RuntimeError(f"{path}: unbekanntes Format")
    value = int.from_bytes(unb64(data["private_key"]), "big")
    key = ec.derive_private_key(value, ec.SECP256R1())
    _cache[str(path)] = key
    return key


def reset_cache() -> None:
    _cache.clear()


def public_bytes(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> bytes:
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    return pub.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def vapid_public_key() -> str:
    """Öffentlicher VAPID-Schlüssel (für die Anmeldung beim UnifiedPush-Verteiler)."""
    return b64(public_bytes(vapid_key()))


def vapid_subject() -> str:
    configured = getattr(settings, "PUSH_VAPID_SUBJECT", "")
    if configured:
        return configured
    url = settings.FRONTEND_URL.rstrip("/")
    return url if url.startswith("https://") else "mailto:noreply@localhost"


def vapid_header(endpoint: str, now: float | None = None) -> str:
    parts = urllib.parse.urlsplit(endpoint)
    audience = f"{parts.scheme}://{parts.netloc}"
    now = int(now if now is not None else time.time())
    header = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = {"aud": audience, "exp": now + 12 * 60 * 60, "sub": vapid_subject()}
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    der = vapid_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{body}.{signature}, k={vapid_public_key()}"


# --- Verschlüsseln (RFC 8291, aes128gcm nach RFC 8188) ---


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    sender_key: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
    pad_to: int = 0,
) -> bytes:
    """Nutzlast für das Gerät verschlüsseln. ``sender_key``/``salt`` nur für Tests.

    ``pad_to``: Klartext mit Füllbytes auf diese Länge bringen (RFC 8291 erlaubt das), damit
    der Push-Dienst an der Größe nicht ablesen kann, was für eine Nachricht es ist."""
    if len(payload) > RECORD_SIZE - 17:
        raise PushError(gettext("Nachricht zu groß."))
    ua_public = unb64(p256dh)
    auth_secret = unb64(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = public_bytes(sender_key)
    shared = sender_key.exchange(ec.ECDH(), ua_key)
    # IKM aus gemeinsamem Geheimnis und auth (RFC 8291, Abschnitt 3.4)
    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    padding = b"\x00" * max(0, min(pad_to, RECORD_SIZE - 16) - len(payload) - 1)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02" + padding, None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


# --- Senden ---


@dataclass(frozen=True)
class Result:
    ok: bool
    status: int
    # Endpunkt gibt es nicht mehr (404/410): beim Gerät entfernen
    gone: bool = False


# Feste Größen für den Klartext samt Trennbyte (Härtung H5, P2): kurz oder größte erlaubte
PAD_SMALL = 1024


def padded_size(length: int, max_payload: int) -> int:
    return PAD_SMALL if length + 1 <= PAD_SMALL else max_payload + 1


def _post(url: str, headers: dict, body: bytes) -> int:
    """Eigentlicher HTTP-Aufruf (in Tests ersetzt): feste, geprüfte Adresse (kein DNS-Rebinding)."""
    from core import safehttp

    check_endpoint(url)
    try:
        resp = safehttp.request(
            "POST",
            url,
            headers=headers,
            body=body,
            timeout=TIMEOUT,
            max_body=64 * 1024,
            allow_internal=getattr(settings, "PUSH_ALLOW_INTERNAL", False),
        )
    except safehttp.SafeHTTPError as exc:
        raise PushError(str(exc)) from exc
    return resp.status


def send(
    endpoint: str,
    p256dh: str,
    auth: str,
    data: dict,
    *,
    urgent: bool = True,
    max_payload: int = MAX_PAYLOAD,
) -> Result:
    """Eine Nachricht (JSON) verschlüsselt an einen Endpunkt schicken."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payload) > max_payload:
        # Zu groß: nur Wecksignal, die App holt den Inhalt selbst
        payload = json.dumps({"v": 1, "t": "sync"}).encode()
    body = encrypt(payload, p256dh, auth, pad_to=padded_size(len(payload), max_payload))
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Encoding": "aes128gcm",
        "TTL": str(TTL),
        "Urgency": "high" if urgent else "normal",
        "Authorization": vapid_header(endpoint),
    }
    status = _post(endpoint, headers, body)
    return Result(ok=200 <= status < 300, status=status, gone=status in (404, 410))
