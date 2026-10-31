"""Identität dieser Instanz im Verbund: Instanz-ID und zwei Schlüsselpaare.

- Ed25519 zum Unterschreiben (Absender und Unverändertheit jedes Pakets)
- X25519 zum Verschlüsseln (nur die Empfänger-Instanz kann ein Paket lesen,
  auch ein vorgeschalteter Webserver mit eigenem TLS nicht)

Der private Schlüssel liegt als Datei im privaten Speicher (nicht in der
Datenbank). Er wird beim ersten Gebrauch erzeugt. Backend und Worker teilen sich
die Datei; das Anlegen ist gegen gleichzeitige Starts abgesichert.

Der Schlüssel landet mit dem privaten Speicher in der (verschlüsselten)
Sicherung. Nach einer Rücksicherung bleibt die Instanz dieselbe.

Schlüsselwechsel (Härtung H6): ``rotate()`` erzeugt neue Schlüssel. Beim geplanten
Wechsel bleiben die alten 30 Tage als ``previous`` erhalten: Anfragen tragen dann
zwei Unterschriften, und Pakete an den alten Verschlüsselungsschlüssel lassen sich
noch öffnen. Danach wird der alte private Schlüssel gelöscht, damit mitgeschnittene
Pakete aus der Zeit davor nicht mehr lesbar werden. Beim Notfallwechsel gilt der
alte Schlüssel sofort nicht mehr.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from django.conf import settings
from django.utils import timezone

FORMAT = "hubiplan-instance"
# So lange gelten die alten Schlüssel nach einem geplanten Wechsel weiter
TRANSITION = datetime.timedelta(days=30)
# Automatischer Wechsel nach so langer Zeit
MAX_AGE = datetime.timedelta(days=365)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def fingerprint(public_key: str, enc_public_key: str) -> str:
    """Kurzer, vorlesbarer Fingerabdruck der öffentlichen Schlüssel einer Instanz."""
    digest = hashlib.sha256(unb64(public_key) + unb64(enc_public_key)).hexdigest()[:24].upper()
    return " ".join(digest[i : i + 4] for i in range(0, len(digest), 4))


def _pub(key) -> str:
    return b64(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def _raw(key) -> str:
    return b64(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )


@dataclass(frozen=True)
class Identity:
    instance_id: str
    private_key: Ed25519PrivateKey
    enc_key: X25519PrivateKey
    created: str
    # Zeitpunkt des letzten Wechsels (sonst created)
    rotated_at: str = ""
    # Alte Schlüssel während der Übergangszeit nach einem geplanten Wechsel
    previous_key: Ed25519PrivateKey | None = field(default=None, compare=False)
    previous_enc: X25519PrivateKey | None = field(default=None, compare=False)
    previous_until: str = ""
    # Notfallwechsel: alter Schlüssel nur noch für die Ankündigung, nie für Pakete
    previous_revoked: bool = False

    @property
    def has_previous(self) -> bool:
        return (
            self.previous_key is not None
            and not self.previous_revoked
            and _future(self.previous_until)
        )

    @property
    def previous_public_key(self) -> str:
        return _pub(self.previous_key) if self.has_previous else ""

    @property
    def decryption_keys(self) -> list[X25519PrivateKey]:
        # Auch nach einem Notfall: Partner haben Pakete vielleicht noch für den alten
        # Schlüssel versiegelt (Warteschlange, höchstens 14 Tage). Öffnen schadet nicht,
        # die Unterschrift der Absenderin wird davon unabhängig geprüft.
        keys = [self.enc_key]
        if self.previous_enc is not None and _future(self.previous_until):
            keys.append(self.previous_enc)
        return keys

    def sign_previous(self, data: bytes) -> str:
        """Zweite Unterschrift mit dem alten Schlüssel (leer ohne Übergangszeit)."""
        if not self.has_previous:
            return ""
        return b64(self.previous_key.sign(data))

    def sign_announcement(self, data: bytes) -> str:
        """Unterschrift des alten Schlüssels für die Ankündigung des Wechsels (auch im Notfall):
        Nur wer den alten Schlüssel hat, kann einen Wechsel ankündigen."""
        if self.previous_key is None or not _future(self.previous_until):
            return ""
        return b64(self.previous_key.sign(data))

    @property
    def last_change(self) -> datetime.datetime | None:
        from django.utils.dateparse import parse_datetime

        return parse_datetime(self.rotated_at or self.created or "")

    @property
    def public_key(self) -> str:
        return _pub(self.private_key)

    @property
    def enc_public_key(self) -> str:
        return _pub(self.enc_key)

    @property
    def fingerprint(self) -> str:
        """Fingerabdruck über beide öffentlichen Schlüssel."""
        return fingerprint(self.public_key, self.enc_public_key)

    def sign(self, data: bytes) -> str:
        return b64(self.private_key.sign(data))


def verify(public_key: str, data: bytes, signature: str) -> bool:
    if not public_key or not signature:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(unb64(public_key)).verify(unb64(signature), data)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def key_path() -> Path:
    configured = getattr(settings, "PEERING_KEY_FILE", "")
    return (
        Path(configured)
        if configured
        else Path(settings.PRIVATE_ROOT) / "peering" / "instance.json"
    )


# Pfad → (Änderungszeit der Datei, Identität): ein Wechsel in einem anderen Prozess
# (Worker, zweites Backend) wird beim nächsten Gebrauch bemerkt
_cache: dict[str, tuple[int, Identity]] = {}


def _future(until: str) -> bool:
    from django.utils.dateparse import parse_datetime

    when = parse_datetime(until or "")
    return when is not None and when > timezone.now()


def _load(path: Path) -> Identity:
    data = json.loads(path.read_text())
    if data.get("format") != FORMAT:
        raise RuntimeError(f"{path}: unbekanntes Format")
    key = Ed25519PrivateKey.from_private_bytes(unb64(data["private_key"]))
    enc = X25519PrivateKey.from_private_bytes(unb64(data["enc_key"]))
    prev = data.get("previous") or {}
    prev_key = prev_enc = None
    if prev and _future(prev.get("until", "")):
        prev_key = Ed25519PrivateKey.from_private_bytes(unb64(prev["private_key"]))
        prev_enc = X25519PrivateKey.from_private_bytes(unb64(prev["enc_key"]))
    return Identity(
        data["instance_id"],
        key,
        enc,
        data.get("created", ""),
        rotated_at=data.get("rotated_at", ""),
        previous_key=prev_key,
        previous_enc=prev_enc,
        previous_until=prev.get("until", "") if prev_key else "",
        previous_revoked=bool(prev.get("emergency")),
    )


def _write(path: Path, data: dict) -> None:
    """Datei ersetzen (erst vollständig schreiben, dann umbenennen)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(path: Path):
    lock = path.with_name(f".{path.name}.lock")
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _create(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    enc_raw = X25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    data = {
        "format": FORMAT,
        "instance_id": str(uuid.uuid4()),
        "private_key": b64(raw),
        "enc_key": b64(enc_raw),
        "created": timezone.now().isoformat(),
    }
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    try:
        # link() schlägt fehl, wenn ein anderer Prozess schneller war: dann gilt dessen Datei
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def identity() -> Identity:
    path = key_path()
    if not path.exists():
        _create(path)
    mtime = path.stat().st_mtime_ns
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        ident = cached[1]
        # Übergangszeit abgelaufen: alte Schlüssel nicht mehr benutzen
        if ident.previous_key is None or _future(ident.previous_until):
            return ident
    ident = _load(path)
    _cache[str(path)] = (mtime, ident)
    return ident


def reset_cache() -> None:
    _cache.clear()


def rotate(*, emergency: bool = False) -> Identity:
    """Neue Schlüssel erzeugen. Geplant: alte gelten 30 Tage weiter. Notfall: Pakete gelten nur
    noch mit dem neuen Schlüssel, und die Partner müssen den neuen Fingerabdruck bestätigen."""
    path = key_path()
    identity()  # legt die Datei an, falls es sie noch nicht gibt
    with _locked(path):
        data = json.loads(path.read_text())
        now = timezone.now()
        # Den alten Schlüssel braucht es auch im Notfall noch: nur er beweist den Partnern,
        # dass die Ankündigung von hier kommt. Pakete unterschreibt und öffnet er dann nicht mehr.
        data["previous"] = {
            "private_key": data["private_key"],
            "enc_key": data["enc_key"],
            "until": (now + TRANSITION).isoformat(),
            "emergency": emergency,
        }
        data["private_key"] = _raw(Ed25519PrivateKey.generate())
        data["enc_key"] = _raw(X25519PrivateKey.generate())
        data["rotated_at"] = now.isoformat()
        _write(path, data)
    reset_cache()
    return identity()


def drop_expired() -> bool:
    """Alte private Schlüssel nach der Übergangszeit aus der Datei löschen."""
    path = key_path()
    if not path.exists():
        return False
    with _locked(path):
        data = json.loads(path.read_text())
        prev = data.get("previous")
        if not prev or _future(prev.get("until", "")):
            return False
        data.pop("previous")
        _write(path, data)
    reset_cache()
    return True


def key_statement(instance_id: str, public_key: str, enc_public_key: str, at: str) -> bytes:
    """Inhalt, den beim Wechsel alter und neuer Schlüssel unterschreiben."""
    return f"hubiplan-keys-v1|{instance_id}|{public_key}|{enc_public_key}|{at}".encode()


def base_url() -> str:
    """Öffentliche Adresse dieser Instanz (ohne Schrägstrich am Ende)."""
    return (getattr(settings, "PEERING_BASE_URL", "") or settings.FRONTEND_URL).rstrip("/")
