"""Private Dateien verschlüsselt ablegen (Schlüssel je Verein, siehe core/crypto.py).

- :class:`EncryptedStorage` verschlüsselt beim Schreiben mit dem Schlüssel des Vereins,
  dem die Datei gehört, und entschlüsselt beim Lesen. Dateien von vor der Umstellung
  (ohne Kennung im Kopf) liest er unverändert, bis ``dateien_verschluesseln`` lief.
- :class:`PrivateFileField` merkt sich beim Speichern, zu welchem Verein die Datei
  gehört (``organization`` des Datensatzes, sonst ``encryption_org_id()``).

``.path`` zeigt auf die verschlüsselte Datei. Wer den Inhalt braucht, liest über
``open()`` oder :func:`local_copy`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models.fields.files import FieldFile
from django.utils.translation import gettext

from . import crypto


class _EncryptedContent(File):
    """Liefert beim Speichern die verschlüsselten Blöcke (kein temporary_file_path:
    sonst würde Django die Klartextdatei einfach verschieben)."""

    def __init__(self, content, key_id: int, key: bytes):
        super().__init__(None, name=getattr(content, "name", None))
        self._content = content
        self._key_id = key_id
        self._key = key

    def chunks(self, chunk_size=None):
        source = self._content
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except (OSError, ValueError):
                pass
        if hasattr(source, "open") and getattr(source, "closed", False):
            source.open("rb")
        yield from crypto.encrypt_chunks(source, self._key_id, self._key)

    def __bool__(self) -> bool:
        return True


class _StoredFile(File):
    """Datei aus dem privaten Speicher, im Klartext gelesen. ``open()`` nach dem
    Schließen öffnet sie wieder über den Speicher (nie die verschlüsselte Datei direkt)."""

    def __init__(self, storage, name):
        self._storage = storage
        super().__init__(storage._open_plain(name), name)

    def open(self, mode=None, *args, **kwargs):
        if mode and any(c in mode for c in "wa+"):
            raise ValueError(gettext("Private Dateien nur über save() schreiben."))
        if not self.closed:
            self.seek(0)
        else:
            self.file = self._storage._open_plain(self.name)
        return self


class EncryptedStorage(FileSystemStorage):
    def _save(self, name, content):
        key_id, key = crypto.current_key()
        return super()._save(name, _EncryptedContent(content, key_id, key))

    def _open(self, name, mode="rb"):
        if "w" in mode or "a" in mode or "+" in mode:
            raise ValueError(gettext("Private Dateien nur über save() schreiben."))
        return _StoredFile(self, name)

    def _open_plain(self, name):
        raw = open(self.path(name), "rb")
        try:
            return crypto.open_plain(raw)
        except Exception:
            raw.close()
            raise

    def size(self, name):
        path = self.path(name)
        total = os.path.getsize(path)
        with open(path, "rb") as raw:
            head = raw.read(len(crypto.MAGIC))
        return crypto.plain_size(total) if crypto.is_encrypted_header(head) else total

    def is_encrypted(self, name) -> bool:
        with open(self.path(name), "rb") as raw:
            return crypto.is_encrypted_header(raw.read(len(crypto.MAGIC)))


def org_id_of(instance) -> int | None:
    """Verein, dem die Dateien eines Datensatzes gehören."""
    getter = getattr(instance, "encryption_org_id", None)
    if callable(getter):
        return getter()
    org_id = getattr(instance, "organization_id", None)
    if org_id is not None:
        return org_id
    # Noch nicht gesetzt (z. B. erst in save() vom übergeordneten Datensatz übernommen):
    # beim übergeordneten Datensatz nachsehen
    for field in instance._meta.concrete_fields:
        if not field.is_relation or field.related_model is None:
            continue
        related_id = getattr(instance, field.attname, None)
        if related_id is None or not any(
            f.attname == "organization_id" for f in field.related_model._meta.concrete_fields
        ):
            continue
        from .tenancy import rls_bypass

        with rls_bypass():
            org_id = (
                field.related_model._base_manager.filter(pk=related_id)
                .values_list("organization_id", flat=True)
                .first()
            )
        if org_id is not None:
            return org_id
    return None


class PrivateFieldFile(FieldFile):
    def save(self, name, content, save=True):
        with crypto.owner(org_id_of(self.instance)):
            super().save(name, content, save)


class PrivateFileField(models.FileField):
    """FileField für den privaten Speicher. Für Migrationen ein gewöhnliches
    FileField (deconstruct), damit die Umstellung keine Migration braucht."""

    attr_class = PrivateFieldFile

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        return name, "django.db.models.FileField", args, kwargs


@contextmanager
def local_copy(fieldfile, suffix: str = "") -> Iterator[str]:
    """Pfad einer entschlüsselten Kopie im temporären Verzeichnis (für Bibliotheken,
    die einen Dateinamen brauchen). Wird danach gelöscht."""
    handle, path = tempfile.mkstemp(suffix=suffix, prefix="hubiplan-")
    try:
        with os.fdopen(handle, "wb") as target, fieldfile.open("rb") as source:
            shutil.copyfileobj(source, target, 1024 * 1024)
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def read_private(relative_name: str) -> bytes:
    """Inhalt einer Datei im privaten Speicher (entschlüsselt, falls nötig)."""
    from exchange.models import private_storage

    with private_storage().open(relative_name, "rb") as handle:
        return handle.read()
