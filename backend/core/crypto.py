"""Verschlüsselung gespeicherter Daten mit einem Schlüssel je Verein (Umschlagverfahren).

Aufbau (Konzept „Serverhack-Schutz“, Abschnitt 3.4, Stufe 1):

- Jeder Verein (oberste Einheit mit eigenem Datenbestand: Plattform, Dachverband,
  Verein) bekommt einen eigenen zufälligen **Datenschlüssel** (AES-256-GCM). Er liegt
  in der Tabelle ``core_datakey``, selbst verschlüsselt („verpackt“).
- Verpackt wird er von einer **Schlüsselquelle** (``DATA_KEY_PROVIDER``). Standard ist
  :class:`EnvKeyProvider` mit dem Hauptschlüssel aus der Server-``.env``
  (``DATA_ENCRYPTION_KEY``). Eine andere Quelle, etwa ein externer Schlüsseldienst,
  braucht nur ``wrap``/``unwrap``; am übrigen Code ändert sich nichts.
- Jede verschlüsselte Datei und jeder verschlüsselte Wert trägt die Nummer seines
  Datenschlüssels. Zum Entschlüsseln muss niemand wissen, zu welchem Verein er gehört.

Entpackte Datenschlüssel bleiben nur im Arbeitsspeicher des Prozesses.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import io
import logging
import os
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection, transaction
from django.utils.module_loading import import_string
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """Daten lassen sich nicht entschlüsseln (falscher Schlüssel oder verändert)."""


# ---------------------------------------------------------------------------
# Schlüsselquelle (austauschbar, Konzept „Externer Schlüsselspeicher“, Abschnitt 6)
# ---------------------------------------------------------------------------


class KeyUnavailable(APIException):
    """Die Schlüsselquelle ist nicht erreichbar (z. B. externer Dienst aus). Die API
    antwortet dann mit 503 und einer verständlichen Meldung; die Oberfläche versucht
    es bei 503 von selbst erneut."""

    status_code = 503
    default_detail = (
        "Die verschlüsselten Daten sind gerade nicht verfügbar. Bitte in einigen Minuten "
        "erneut versuchen."
    )
    default_code = "schluessel_nicht_verfuegbar"


class KeyProvider:
    """Verpackt und entpackt Datenschlüssel.

    Ergebnis von ``wrap``: ``"<prefix>:<version>:<base64>"``. ``context`` ist die
    unveränderliche Kennung des Vereins (``org:<pk>``) und wird mitgeprüft: Ein
    Datenschlüssel, der in der Datenbank einem anderen Verein untergeschoben wird,
    lässt sich nicht entpacken."""

    prefix = "?"

    def wrap(self, key: bytes, context: str) -> str:
        raise NotImplementedError

    def unwrap(self, wrapped: str, context: str) -> bytes:
        raise NotImplementedError

    def ready(self) -> bool:
        return True


def _decode_master(value: str) -> bytes:
    value = value.strip()
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("Der Hauptschlüssel ist kein gültiges Base64.") from exc
    if len(raw) != 32:
        raise ImproperlyConfigured("Der Hauptschlüssel muss 32 Byte lang sein (Base64).")
    return raw


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FileKeyProvider(KeyProvider):
    """Hauptschlüssel aus einer Datei auf dem Server (``DATA_ENCRYPTION_KEY_FILE``,
    eingebunden als Docker-Secret, nicht in der ``.env``). Sonst aus
    ``DATA_ENCRYPTION_KEYS`` (Entwicklung, Tests).

    Mehrere Schlüssel (Zeilen der Datei bzw. ``neu,alt``) erlauben einen Wechsel:
    verpackt wird mit dem ersten, entpackt mit dem passenden (Kennung im Ergebnis).
    Format: ``file:1:<Kennung des Hauptschlüssels>.<Nonce · AES-GCM-Chiffrat>``.
    """

    prefix = "file"
    VERSION = "1"

    def __init__(self, keys: list[str] | None = None):
        values = keys if keys is not None else self._configured()
        if not values:
            raise ImproperlyConfigured(
                "Kein Hauptschlüssel: DATA_ENCRYPTION_KEY_FILE oder DATA_ENCRYPTION_KEY setzen."
            )
        self._keys = [_decode_master(v) for v in values]
        self._by_id = {self.key_id(k): k for k in self._keys}

    @staticmethod
    def _configured() -> list[str]:
        path = getattr(settings, "DATA_ENCRYPTION_KEY_FILE", "")
        if path:
            try:
                with open(path, encoding="ascii") as handle:
                    lines = [line.strip() for line in handle]
            except OSError as exc:
                raise KeyUnavailable(f"Hauptschlüssel nicht lesbar: {exc.strerror}") from exc
            return [line for line in lines if line and not line.startswith("#")]
        return list(settings.DATA_ENCRYPTION_KEYS)

    @staticmethod
    def key_id(key: bytes) -> str:
        return hashlib.sha256(b"hubiplan-hauptschluessel:" + key).hexdigest()[:16]

    def wrap(self, key: bytes, context: str) -> str:
        master = self._keys[0]
        nonce = os.urandom(12)
        ct = AESGCM(master).encrypt(nonce, key, b"datakey:" + context.encode())
        return f"{self.prefix}:{self.VERSION}:{self.key_id(master)}.{_b64(nonce + ct)}"

    def unwrap(self, wrapped: str, context: str) -> bytes:
        try:
            prefix, version, rest = wrapped.split(":", 2)
            kid, data = rest.split(".", 1)
            blob = _unb64(data)
        except ValueError as exc:
            raise DecryptionError("Unbekanntes Format eines verpackten Schlüssels.") from exc
        if prefix != self.prefix or version != self.VERSION or len(blob) < 12 + 16:
            raise DecryptionError("Unbekanntes Format eines verpackten Schlüssels.")
        master = self._by_id.get(kid)
        if master is None:
            raise DecryptionError(
                "Datenschlüssel wurde mit einem anderen Hauptschlüssel verpackt "
                "(Hauptschlüssel falsch oder der alte fehlt)."
            )
        try:
            return AESGCM(master).decrypt(blob[:12], blob[12:], b"datakey:" + context.encode())
        except InvalidTag as exc:
            raise DecryptionError("Datenschlüssel lässt sich nicht entpacken.") from exc

    def is_current(self, wrapped: str) -> bool:
        return wrapped.startswith(f"{self.prefix}:{self.VERSION}:{self.key_id(self._keys[0])}.")


_provider_lock = threading.Lock()
_providers: list[KeyProvider] | None = None


def providers() -> list[KeyProvider]:
    """Schlüsselquellen aus ``DATA_KEY_PROVIDERS``: verpackt wird mit der ersten,
    entpackt mit der, deren Präfix passt (später z. B. ``openbao,file``)."""
    global _providers
    if _providers is None:
        with _provider_lock:
            if _providers is None:
                _providers = [
                    import_string(PROVIDER_CLASSES.get(name, name))()
                    for name in settings.DATA_KEY_PROVIDERS
                ]
    return _providers


PROVIDER_CLASSES = {"file": "core.crypto.FileKeyProvider"}


def wrap_key(key: bytes, context: str) -> str:
    return providers()[0].wrap(key, context)


def unwrap_key(wrapped: str, context: str) -> bytes:
    prefix = wrapped.split(":", 1)[0]
    for p in providers():
        if p.prefix == prefix:
            return p.unwrap(wrapped, context)
    raise KeyUnavailable(f"Keine Schlüsselquelle für „{prefix}“ eingerichtet.")


def ready() -> bool:
    try:
        return all(p.ready() for p in providers())
    except (KeyUnavailable, ImproperlyConfigured):
        return False


def reset() -> None:
    """Zwischenspeicher leeren (Tests, Schlüsselwechsel)."""
    global _providers
    _providers = None
    _keys_by_id.clear()
    _key_ids_by_owner.clear()
    _owner_cache.clear()


# ---------------------------------------------------------------------------
# Datenschlüssel je Verein
# ---------------------------------------------------------------------------

# Schlüssel nach Nummer (Nummern werden nie wieder vergeben); Zuordnung Verein →
# Nummer erst nach dem Commit, siehe _remember
_keys_by_id: dict[int, tuple[bytes, float]] = {}
_key_ids_by_owner: dict[int, int] = {}
# Organisation → Schlüsselinhaber (ändert sich nicht: Untereinheiten bleiben in ihrem Verein)
_owner_cache: dict[int, int] = {}


def _context(owner_id: int) -> str:
    return f"org:{owner_id}"


def key_owner_id(org_id: int) -> int:
    """Inhaber des Schlüssels: die Organisation selbst oder, bei einer Untereinheit,
    der Verein (bzw. Dachverband), zu dem sie gehört."""
    cached = _owner_cache.get(org_id)
    if cached is not None:
        return cached
    from organizations.models import Organization

    from .tenancy import rls_bypass

    node_id = org_id
    with rls_bypass():
        for _ in range(50):
            row = Organization.objects.filter(pk=node_id).values("type", "parent_id").first()
            if row is None or row["type"] != Organization.Type.UNIT or not row["parent_id"]:
                break
            node_id = row["parent_id"]
    _owner_cache[org_id] = node_id
    return node_id


def _remember(key_id: int, owner_id: int, key: bytes) -> None:
    # Zum Entschlüsseln sofort merken: Wer die Nummer kennt, hat Daten damit gelesen
    # oder geschrieben, und eine zurückgerollte Nummer kommt nie wieder vor.
    _keys_by_id[key_id] = (key, time.monotonic())

    def _store():
        _key_ids_by_owner[owner_id] = key_id

    # Zum Verschlüsseln erst nach dem Commit: Rollt die Transaktion zurück, gibt es den
    # Schlüssel nicht, und nichts Neues darf ihn benutzen.
    transaction.on_commit(_store)


def _load(key_id: int) -> bytes:
    from .models import DataKey

    row = DataKey.objects.filter(pk=key_id).values("organization_id", "wrapped").first()
    if row is None:
        raise DecryptionError(f"Datenschlüssel {key_id} fehlt (Verein gelöscht?).")
    key = unwrap_key(row["wrapped"], _context(row["organization_id"]))
    _remember(key_id, row["organization_id"], key)
    return key


def _cached(key_id: int) -> bytes | None:
    entry = _keys_by_id.get(key_id)
    if entry is None:
        return None
    ttl = settings.DATA_KEY_CACHE_SECONDS
    if ttl and time.monotonic() - entry[1] > ttl:
        _keys_by_id.pop(key_id, None)
        return None
    return entry[0]


def key_by_id(key_id: int) -> bytes:
    key = _cached(key_id)
    return key if key is not None else _load(key_id)


def key_for_owner(owner_id: int) -> tuple[int, bytes]:
    """(Nummer, Schlüssel) des Datenschlüssels eines Vereins; legt ihn bei Bedarf an."""
    key_id = _key_ids_by_owner.get(owner_id)
    if key_id is not None:
        key = _cached(key_id)
        if key is not None:
            return key_id, key
    from .models import DataKey

    row = DataKey.objects.filter(organization_id=owner_id).values("pk").first()
    if row is not None:
        return row["pk"], key_by_id(row["pk"])
    key = AESGCM.generate_key(bit_length=256)
    try:
        with transaction.atomic():
            obj = DataKey.objects.create(
                organization_id=owner_id,
                wrapped=wrap_key(key, _context(owner_id)),
            )
    except IntegrityError:
        # Gleichzeitig angelegt: den anderen nehmen
        row = DataKey.objects.filter(organization_id=owner_id).values("pk").get()
        return row["pk"], key_by_id(row["pk"])
    _remember(obj.pk, owner_id, key)
    return obj.pk, key


def key_for_org(org_id: int) -> tuple[int, bytes]:
    return key_for_owner(key_owner_id(org_id))


# ---------------------------------------------------------------------------
# Wem gehört eine Datei? (gesetzt von PrivateFieldFile beim Speichern)
# ---------------------------------------------------------------------------

_current_org: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "hubiplan_crypto_org", default=None
)


@contextmanager
def owner(org_id: int | None) -> Iterator[None]:
    token = _current_org.set(org_id)
    try:
        yield
    finally:
        _current_org.reset(token)


def current_key() -> tuple[int, bytes]:
    org_id = _current_org.get()
    if org_id is None:
        if getattr(settings, "DATA_ENCRYPTION_STRICT", False):
            raise ImproperlyConfigured("Datei ohne Verein gespeichert (crypto.owner fehlt).")
        # Lieber mit dem Schlüssel der Plattform verschlüsseln als im Klartext ablegen
        logger.warning("Private Datei ohne Verein: verschlüsselt mit dem Plattformschlüssel")
        from organizations.models import Organization

        org_id = Organization.platform().pk
    return key_for_org(org_id)


# ---------------------------------------------------------------------------
# Dateien: AES-256-GCM in Blöcken (Streaming, wahlfreier Zugriff beim Lesen)
# ---------------------------------------------------------------------------
#
# Kopf: MAGIC (8) · Schlüsselnummer (8, big endian) · Nonce-Präfix (8) = 24 Byte.
# Danach Blöcke zu höchstens CHUNK Byte Klartext, je mit 16 Byte Prüfsumme.
# Nonce eines Blocks: Präfix · Blocknummer (4). Der Kopf und ein Kennzeichen „letzter
# Block“ sind als zusätzliche Daten mitgeprüft: Abschneiden, Vertauschen oder
# Austauschen von Blöcken fällt beim Lesen auf.

MAGIC = b"HUBENC1\n"
HEADER = 24
CHUNK = 64 * 1024
TAG = 16


def _chunk_nonce(prefix: bytes, index: int) -> bytes:
    return prefix + struct.pack(">I", index)


def _chunk_aad(header: bytes, last: bool) -> bytes:
    return header + (b"\x01" if last else b"\x00")


def is_encrypted_header(head: bytes) -> bool:
    return head[: len(MAGIC)] == MAGIC


def encrypt_chunks(source, key_id: int, key: bytes) -> Iterator[bytes]:
    """Verschlüsselt einen Klartext-Datenstrom (Dateiobjekt mit ``read``) blockweise."""
    prefix = os.urandom(8)
    header = MAGIC + struct.pack(">Q", key_id) + prefix
    aes = AESGCM(key)
    yield header
    index = 0
    current = _read_full(source, CHUNK)
    while True:
        following = _read_full(source, CHUNK) if len(current) == CHUNK else b""
        last = not following
        yield aes.encrypt(_chunk_nonce(prefix, index), current, _chunk_aad(header, last))
        if last:
            return
        index += 1
        current = following


def _read_full(source, size: int) -> bytes:
    parts, missing = [], size
    while missing:
        data = source.read(missing)
        if not data:
            break
        if isinstance(data, str):
            data = data.encode()
        parts.append(data)
        missing -= len(data)
    return b"".join(parts)


def encrypt_bytes(data: bytes, key_id: int, key: bytes) -> bytes:
    return b"".join(encrypt_chunks(io.BytesIO(data), key_id, key))


def plain_size(total: int) -> int:
    body = total - HEADER
    if body < TAG:
        raise DecryptionError("Verschlüsselte Datei ist abgeschnitten.")
    chunks = max(1, -(-body // (CHUNK + TAG)))
    return body - chunks * TAG


class DecryptingReader(io.RawIOBase):
    """Liest eine verschlüsselte Datei als Klartext; unterstützt ``seek``."""

    def __init__(self, raw):
        super().__init__()
        self._raw = raw
        raw.seek(0)
        header = raw.read(HEADER)
        if len(header) != HEADER or not is_encrypted_header(header):
            raise DecryptionError("Keine verschlüsselte Datei.")
        self._header = header
        self._prefix = header[16:24]
        self._aes = AESGCM(key_by_id(struct.unpack(">Q", header[8:16])[0]))
        raw.seek(0, io.SEEK_END)
        total = raw.tell()
        self._size = plain_size(total)
        self._chunks = max(1, -(-(total - HEADER) // (CHUNK + TAG)))
        self._pos = 0
        self._cached: tuple[int, bytes] | None = None

    @property
    def size(self) -> int:
        return self._size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            pos = offset
        elif whence == io.SEEK_CUR:
            pos = self._pos + offset
        elif whence == io.SEEK_END:
            pos = self._size + offset
        else:
            raise ValueError("whence")
        if pos < 0:
            raise ValueError("Negative Position")
        self._pos = pos
        return pos

    def _chunk(self, index: int) -> bytes:
        if self._cached and self._cached[0] == index:
            return self._cached[1]
        self._raw.seek(HEADER + index * (CHUNK + TAG))
        data = self._raw.read(CHUNK + TAG)
        last = index == self._chunks - 1
        try:
            plain = self._aes.decrypt(
                _chunk_nonce(self._prefix, index), data, _chunk_aad(self._header, last)
            )
        except InvalidTag as exc:
            raise DecryptionError("Verschlüsselte Datei ist beschädigt oder verändert.") from exc
        self._cached = (index, plain)
        return plain

    def readinto(self, buffer) -> int:
        if self._pos >= self._size:
            return 0
        index, offset = divmod(self._pos, CHUNK)
        plain = self._chunk(index)[offset:]
        n = min(len(buffer), len(plain))
        buffer[:n] = plain[:n]
        self._pos += n
        return n

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            super().close()


def open_plain(raw):
    """Datei-Objekt im Klartext: entschlüsselt, wenn verschlüsselt; sonst unverändert
    (Dateien von vor der Verschlüsselung, bis ``dateien_verschluesseln`` lief)."""
    head = raw.read(len(MAGIC))
    raw.seek(0)
    if not is_encrypted_header(head):
        return raw
    return io.BufferedReader(DecryptingReader(raw), buffer_size=CHUNK)


def decrypt_bytes(data: bytes) -> bytes:
    if not is_encrypted_header(data):
        return data
    with DecryptingReader(io.BytesIO(data)) as reader:
        return reader.read()


def available() -> bool:
    """Tabelle der Datenschlüssel vorhanden (nach der Migration)?"""
    return "core_datakey" in connection.introspection.table_names()
