"""Verschlüsselte Datenbankfelder mit dem Schlüssel des Vereins (core/crypto.py).

Der Wert wird beim Speichern verschlüsselt (``pre_save``), am Objekt bleibt der
Klartext. Beim Laden wird entschlüsselt. In der Datenbank steht
``enc1:<Base64(Schlüsselnummer · Nonce · AES-GCM-Chiffrat)>``. Leere Werte bleiben leer.

Die Datenbank kann in diesen Feldern weder suchen noch sortieren. Deshalb sind nur
``isnull`` und der Vergleich mit dem leeren Wert erlaubt; jede andere Abfrage bricht
mit einem Fehler ab, statt still nichts zu finden. Werte ohne ``enc1:`` (von vor der
Umstellung) werden unverändert gelesen, bis ``daten_verschluesseln`` lief.

Wem ein Wert gehört, steht in ``encryption_org_id()`` des Modells, sonst in
``organization_id``, sonst in ``scope_id`` (Verbandsbereich, z. B. Kontaktdaten).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.exceptions import FieldError
from django.db import models

from . import crypto

logger = logging.getLogger(__name__)

PREFIX = "enc1:"
ALLOWED_LOOKUPS = {"isnull", "exact", "in"}


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def _aad(field) -> bytes:
    return f"{field.model._meta.label_lower}.{field.attname}".encode()


def encrypt_text(text: str, org_id: int, field) -> str:
    key_id, key = crypto.key_for_org(org_id)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, text.encode(), _aad(field))
    return PREFIX + base64.b64encode(struct.pack(">Q", key_id) + nonce + ct).decode()


def decrypt_text(value: str, field) -> str:
    try:
        raw = base64.b64decode(value[len(PREFIX) :])
        key_id = struct.unpack(">Q", raw[:8])[0]
    except (ValueError, struct.error) as exc:
        raise crypto.DecryptionError("Verschlüsselter Wert ist beschädigt.") from exc
    key = crypto.key_by_id(key_id)
    try:
        return AESGCM(key).decrypt(raw[8:20], raw[20:], _aad(field)).decode()
    except InvalidTag as exc:
        raise crypto.DecryptionError("Verschlüsselter Wert ist verändert.") from exc


def owner_org_id(instance) -> int | None:
    getter = getattr(instance, "encryption_org_id", None)
    if callable(getter):
        return getter()
    for attname in ("organization_id", "scope_id"):
        value = getattr(instance, attname, None)
        if value is not None:
            return value
    return None


def _owner_or_fail(instance, field) -> int:
    org_id = owner_org_id(instance)
    if org_id is None:
        raise FieldError(
            f"{field.model._meta.label}.{field.name}: Verein für die Verschlüsselung fehlt."
        )
    return org_id


class EncryptedMixin:
    """Gemeinsamer Teil für Text- und JSON-Felder."""

    empty_values_db = ("", None)

    def _plain_to_text(self, value) -> str:
        return value

    def _text_to_plain(self, text: str):
        return text

    def _broken(self):
        return ""

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if value in self.empty_values_db or is_encrypted(value):
            return value
        text = self._plain_to_text(value)
        return encrypt_text(text, _owner_or_fail(model_instance, self), self)

    def decrypt_db_value(self, value):
        if not is_encrypted(value):
            return value
        try:
            return self._text_to_plain(decrypt_text(value, self))
        except crypto.DecryptionError:
            # Schlüssel gelöscht (Verein entfernt) oder Wert verändert
            logger.warning("Wert in %s nicht lesbar", self.model._meta.label)
            return self._broken()

    def get_lookup(self, lookup_name):
        if lookup_name not in ALLOWED_LOOKUPS:
            raise FieldError(
                f"{self.model._meta.label}.{self.name} ist verschlüsselt: "
                f"Abfrage „{lookup_name}“ geht nicht in der Datenbank."
            )
        return super().get_lookup(lookup_name)

    def get_transform(self, lookup_name):
        raise FieldError(
            f"{self.model._meta.label}.{self.name} ist verschlüsselt: keine Teilabfragen."
        )


class EncryptedCharField(EncryptedMixin, models.CharField):
    """CharField, verschlüsselt gespeichert. ``max_length`` gilt für den Klartext
    (Prüfung in Formularen und der API); die Spalte ist ``text``."""

    def db_type(self, connection):
        return "text"

    def cast_db_type(self, connection):
        return "text"

    def from_db_value(self, value, expression, connection):
        return self.decrypt_db_value(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in ("", None) or is_encrypted(value):
            return value
        raise FieldError(
            f"{self.model._meta.label}.{self.name} ist verschlüsselt: nur über save() "
            "schreiben, nicht über update(), bulk_update() oder eine Abfrage."
        )


class EncryptedEmailField(EncryptedCharField, models.EmailField):
    pass


class EncryptedJSONField(EncryptedMixin, models.JSONField):
    """JSONField, verschlüsselt gespeichert als ``{"enc1": "<Chiffrat>"}`` (die Spalte
    bleibt jsonb; daher keine Migration). Für Migrationen ein gewöhnliches JSONField."""

    KEY = "enc1"

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        return name, "django.db.models.JSONField", args, kwargs

    def _plain_to_text(self, value) -> str:
        return json.dumps(value, cls=self.encoder, ensure_ascii=False)

    def _text_to_plain(self, text: str):
        return json.loads(text, cls=self.decoder)

    def _broken(self):
        return None

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if value is None or self._wrapped(value):
            return value
        text = self._plain_to_text(value)
        return {self.KEY: encrypt_text(text, _owner_or_fail(model_instance, self), self)}

    def _wrapped(self, value) -> bool:
        return (
            isinstance(value, dict) and set(value) == {self.KEY} and is_encrypted(value[self.KEY])
        )

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if self._wrapped(value):
            return self.decrypt_db_value(value[self.KEY])
        return value

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is not None and not self._wrapped(value) and not prepared:
            raise FieldError(
                f"{self.model._meta.label}.{self.name} ist verschlüsselt: nur über save() "
                "schreiben, nicht über update(), bulk_update() oder eine Abfrage."
            )
        return super().get_db_prep_value(value, connection, prepared)
