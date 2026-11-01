"""Schlüssel, mit dem HUBIplan die Anmeldebestätigungen (ID-Token) unterschreibt.

RSA 2048 mit RS256, weil das jede OpenID-Connect-Bibliothek kann (auch die Nextcloud-App
„user_oidc“). Die Datei liegt im privaten Speicher (in den Backups enthalten) und wird
beim ersten Gebrauch angelegt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.conf import settings

KEY_FILE_MODE = 0o640

_cache: dict[str, tuple[int, SigningKey]] = {}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int(value: int) -> str:
    return b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@dataclass(frozen=True)
class SigningKey:
    key: rsa.RSAPrivateKey
    kid: str

    def sign(self, data: bytes) -> bytes:
        return self.key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    def jwk(self) -> dict:
        numbers = self.key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": _int(numbers.n),
            "e": _int(numbers.e),
        }


def key_path() -> Path:
    configured = getattr(settings, "OIDC_KEY_FILE", "")
    if configured:
        return Path(configured)
    return Path(settings.PRIVATE_ROOT) / "oidc" / "signing.pem"


def _kid(key: rsa.RSAPrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return b64url(hashlib.sha256(der).digest()[:12])


def _create(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, KEY_FILE_MODE)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    try:
        # link() schlägt fehl, wenn ein anderer Prozess schneller war: dann gilt dessen Datei
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def signing_key() -> SigningKey:
    path = key_path()
    if not path.exists():
        _create(path)
    mtime = path.stat().st_mtime_ns
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise RuntimeError(f"{path}: kein RSA-Schlüssel")
    result = SigningKey(key, _kid(key))
    _cache[str(path)] = (mtime, result)
    return result


def reset_cache() -> None:
    _cache.clear()


def jwt(claims: dict) -> str:
    """Unterschriebenes JWT (RS256)."""
    key = signing_key()
    header = {"alg": "RS256", "typ": "JWT", "kid": key.kid}
    head = b64url(json.dumps(header, separators=(",", ":")).encode())
    body = b64url(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode())
    signing_input = f"{head}.{body}".encode()
    return f"{head}.{body}.{b64url(key.sign(signing_input))}"
