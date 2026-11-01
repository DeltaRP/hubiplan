"""Verschlüsseln und Unterschreiben von Verbund-Paketen.

Jedes Paket ist zusätzlich zu HTTPS Ende-zu-Ende verschlüsselt: Schlüssel aus
X25519 (Einmalschlüssel der Absenderin + Schlüssel der Empfängerin), HKDF-SHA256,
ChaCha20-Poly1305. Die Instanz-IDs beider Seiten sind als Zusatzdaten
eingebunden: Ein Paket für Instanz B lässt sich nicht an Instanz C umleiten.

Unterschrieben wird die ganze Anfrage (Methode, Pfad, Zeit, Einmalwert,
Prüfsumme des Inhalts) mit Ed25519. Der Empfänger prüft die Unterschrift mit
dem gespeicherten (beim Koppeln geprüften) Schlüssel der Absenderin.
"""

from __future__ import annotations

import hashlib
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.utils.translation import gettext

from .identity import Identity, b64, unb64, verify

INFO = b"hubiplan-peering-v1"
ENVELOPE = "hubiplan-sealed-v1"


class CryptoError(ValueError):
    pass


def _key(shared: bytes, epk: bytes, rpk: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=epk + rpk, info=INFO).derive(shared)


def _aad(sender: str, recipient: str) -> bytes:
    return f"{ENVELOPE}|{sender}|{recipient}".encode()


def seal(payload: dict, *, sender: str, recipient: str, recipient_enc_key: str) -> dict:
    """Verschlüsselt ``payload`` für die Empfänger-Instanz."""
    rpk = unb64(recipient_enc_key)
    eph = X25519PrivateKey.generate()
    epk = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    shared = eph.exchange(X25519PublicKey.from_public_bytes(rpk))
    nonce = os.urandom(12)
    plain = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ct = ChaCha20Poly1305(_key(shared, epk, rpk)).encrypt(nonce, plain, _aad(sender, recipient))
    return {
        "format": ENVELOPE,
        "from": sender,
        "to": recipient,
        "epk": b64(epk),
        "nonce": b64(nonce),
        "ct": b64(ct),
    }


def open_sealed(envelope: dict, ident: Identity) -> dict:
    """Entschlüsselt ein Paket an diese Instanz."""
    if not isinstance(envelope, dict) or envelope.get("format") != ENVELOPE:
        raise CryptoError(gettext("kein verschlüsseltes Paket"))
    if envelope.get("to") != ident.instance_id:
        raise CryptoError(gettext("Paket ist nicht für diese Instanz"))
    # Nach einem geplanten Schlüsselwechsel: auch der alte Schlüssel (Übergangszeit)
    for enc_key in ident.decryption_keys:
        try:
            epk = unb64(envelope["epk"])
            rpk = enc_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            shared = enc_key.exchange(X25519PublicKey.from_public_bytes(epk))
            plain = ChaCha20Poly1305(_key(shared, epk, rpk)).decrypt(
                unb64(envelope["nonce"]),
                unb64(envelope["ct"]),
                _aad(str(envelope.get("from", "")), ident.instance_id),
            )
            return json.loads(plain)
        except InvalidTag:
            continue
        except (KeyError, ValueError, TypeError) as exc:
            raise CryptoError(gettext("Paket lässt sich nicht entschlüsseln")) from exc
    raise CryptoError(gettext("Paket lässt sich nicht entschlüsseln"))


def signing_input(method: str, path: str, date: str, nonce: str, body: bytes) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return "\n".join([method.upper(), path, date, nonce, digest]).encode()


def sign_request(ident: Identity, method: str, path: str, date: str, nonce: str, body: bytes):
    return ident.sign(signing_input(method, path, date, nonce, body))


def sign_request_previous(ident: Identity, method, path, date, nonce, body) -> str:
    """Zweite Unterschrift mit dem alten Schlüssel während der Übergangszeit."""
    return ident.sign_previous(signing_input(method, path, date, nonce, body))


def verify_request(public_key, method, path, date, nonce, body, signature) -> bool:
    return verify(public_key, signing_input(method, path, date, nonce, body), signature)


def verify_request_any(public_keys, method, path, date, nonce, body, signatures) -> bool:
    """Gültig, wenn eine der Unterschriften zu einem der angenommenen Schlüssel passt."""
    data = signing_input(method, path, date, nonce, body)
    return any(verify(k, data, s) for k in public_keys if k for s in signatures if s)
