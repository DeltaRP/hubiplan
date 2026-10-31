"""Schlüsselpaare der App im Android-Keystore (Härtung H7, G3).

- **Geräteschlüsselpaar** (P-256, nicht exportierbar): Beim Verbinden meldet die App den
  öffentlichen Teil. Damit unterschreibt sie die Erneuerung des Geräteschlüssels ``hpd_…``.
  Wer nur ``hpd_…`` abgreift, kann ihn nicht erneuern; nach ``RENEW_MAX_DAYS`` wirkt er nicht
  mehr.
- **Vorstands-Schlüsselpaar** (P-256, nur kurz nach dem Entsperren nutzbar): Beim Freischalten
  der Verwaltung meldet die App den öffentlichen Teil. Jede Anfrage an die Verwaltung trägt
  Zeit und Unterschrift über Methode, Pfad, Zeit und Prüfsumme des Inhalts.

Öffentliche Schlüssel: unkomprimierter Punkt (65 Byte), base64url. Unterschriften: DER, base64url.
"""

from __future__ import annotations

import hashlib
import io

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from .webpush import unb64

# Erneuern ab 7 Tagen, ohne Erneuerung gilt ein Schlüssel höchstens 14 Tage
RENEW_DAYS = 7
RENEW_MAX_DAYS = 14
# Alter Schlüssel gilt nach der ersten Nutzung des neuen noch so lange (laufende Anfragen)
GRACE_SECONDS = 5 * 60
# Aufgabe zum Erneuern gilt so lange
CHALLENGE_SECONDS = 5 * 60
# Ausgemusterte Schlüssel, deren Nutzung als Kopie erkannt wird
RETIRED_KEEP = 10

# Vorstandsanfragen
TIME_HEADER = "X-Hubiplan-Time"
SIGNATURE_HEADER = "X-Hubiplan-Signature"
# Ab App 0.19: zufällige Kennung je Anfrage, mit unterschrieben (Format 2)
NONCE_HEADER = "X-Hubiplan-Nonce"
IDEMPOTENCY_HEADER = "Idempotency-Key"
# Ordnung der Kurve P-256 (für die eindeutige Form einer Unterschrift)
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
MAX_SKEW = 5 * 60
# Größter Inhalt, der für die Unterschrift gelesen wird (Fotos und Belege bis 10 MB)
MAX_SIGNED_BODY = 16 * 1024 * 1024


def public_key(value: str) -> ec.EllipticCurvePublicKey | None:
    try:
        raw = unb64(value)
        if len(raw) != 65:
            return None
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except (ValueError, TypeError):
        return None


def valid_public_key(value: str) -> bool:
    return public_key(value) is not None


def verify(public: str, message: bytes, signature: str) -> bool:
    key = public_key(public)
    if key is None:
        return False
    try:
        key.verify(unb64(signature), message, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def renew_message(device_id: int, challenge: str) -> bytes:
    return f"hubiplan-renew\n{device_id}\n{challenge}".encode()


def admin_message(
    method: str, path: str, timestamp: str, body: bytes, nonce: str = "", idempotency: str = ""
) -> bytes:
    """Was die App für jede Vorstandsanfrage unterschreibt.

    ``path``: Pfad samt Abfrage wie gesendet (percent-kodiert), z. B. ``/api/…/?q=M%C3%BCller``.
    Mit ``nonce`` (Format 2, ab App 0.19) zusätzlich die Zufallskennung der Anfrage und der
    ``Idempotency-Key``; ohne bleibt es beim Format 1 älterer Apps.
    """
    digest = hashlib.sha256(body).hexdigest()
    if nonce:
        return (
            f"hubiplan-admin-2\n{method.upper()}\n{path}\n{timestamp}\n{nonce}\n"
            f"{idempotency}\n{digest}"
        ).encode()
    return f"hubiplan-admin\n{method.upper()}\n{path}\n{timestamp}\n{digest}".encode()


def replay_id(message: bytes, signature: str) -> str:
    """Eindeutige Kennung einer unterschriebenen Anfrage, unabhängig von der Schreibweise.

    Dieselbe Unterschrift lässt sich verschieden kodieren (base64 mit/ohne Füllzeichen) und
    bei ECDSA zusätzlich als (r, n−s) schreiben. Gezählt wird deshalb die Nachricht samt
    r und dem kleineren der beiden s-Werte (Gesamtaudit 30.10., BSEC-02).
    """
    r, s = decode_dss_signature(unb64(signature))
    s = min(s, P256_ORDER - s)
    return hashlib.sha256(message + b"\n" + f"{r:x}:{s:x}".encode()).hexdigest()


class BodyTooLarge(Exception):
    pass


def request_body(request) -> bytes:
    """Inhalt der Anfrage lesen und für die spätere Verarbeitung (auch multipart) aufheben.

    Django begrenzt ``request.body`` auf ``DATA_UPLOAD_MAX_MEMORY_SIZE``; Uploads der
    Verwaltung dürfen größer sein, deshalb hier eine eigene Grenze.
    """
    raw = getattr(request, "_request", request)
    if hasattr(raw, "_body"):
        return raw._body
    length = int(raw.META.get("CONTENT_LENGTH") or 0)
    if length > MAX_SIGNED_BODY:
        raise BodyTooLarge()
    body = raw.read()
    raw._body = body
    raw._stream = io.BytesIO(body)
    return body
