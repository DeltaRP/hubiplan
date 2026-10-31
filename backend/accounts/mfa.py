"""2FA-Geheimnisse (TOTP-Schlüssel, Saat der Wiederherstellungscodes) verschlüsselt speichern.

allauth legt diese Geheimnisse in ``mfa_authenticator.data`` ab und ruft dafür
``encrypt``/``decrypt`` des Adapters auf. Verschlüsselt wird mit Fernet und einem
eigenen Schlüssel aus der Server-``.env`` (``MFA_ENCRYPTION_KEY``). Er liegt nicht in
der Datenbank und nicht im Backup: Wer nur einen Datenbank-Dump hat, kann damit keine
2FA-Codes erzeugen.

Mehrere Schlüssel (``MFA_ENCRYPTION_KEYS=neu,alt``) erlauben einen Wechsel: verschlüsselt
wird mit dem ersten, entschlüsselt mit jedem.
"""

from __future__ import annotations

from functools import lru_cache

from allauth.mfa.adapter import DefaultMFAAdapter
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIX = "enc1:"


@lru_cache(maxsize=4)
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured("MFA_ENCRYPTION_KEY muss gesetzt sein.")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except ValueError as exc:
        raise ImproperlyConfigured(
            "MFA_ENCRYPTION_KEY ist kein gültiger Schlüssel (32 Byte, URL-sicheres Base64)."
        ) from exc


def fernet() -> MultiFernet:
    return _fernet(tuple(settings.MFA_ENCRYPTION_KEYS))


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(text: str) -> str:
    if is_encrypted(text):
        return text
    return PREFIX + fernet().encrypt(text.encode()).decode()


def decrypt(value: str) -> str:
    if not is_encrypted(value):
        # Die Migration hat alle Einträge verschlüsselt; Klartext gilt als untergeschoben
        raise ImproperlyConfigured("2FA-Geheimnis ist nicht verschlüsselt gespeichert.")
    try:
        return fernet().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "2FA-Geheimnis lässt sich nicht entschlüsseln: falscher MFA_ENCRYPTION_KEY?"
        ) from exc


def rotate(value: str) -> str:
    """Mit dem ersten (neuen) Schlüssel neu verschlüsseln."""
    if not is_encrypted(value):
        return encrypt(value)
    return PREFIX + fernet().rotate(value[len(PREFIX) :].encode()).decode()


# Felder in Authenticator.data, die Geheimnisse enthalten
def transform_data(kind: str, data: dict, func) -> dict:
    data = dict(data or {})
    if kind == "totp" and data.get("secret"):
        data["secret"] = func(data["secret"])
    if kind == "recovery_codes":
        if data.get("seed"):
            data["seed"] = func(data["seed"])
        if isinstance(data.get("migrated_codes"), list):
            data["migrated_codes"] = [func(code) for code in data["migrated_codes"]]
    return data


class MFAAdapter(DefaultMFAAdapter):
    def encrypt(self, text: str) -> str:
        return encrypt(text)

    def decrypt(self, encrypted_text: str) -> str:
        return decrypt(encrypted_text)
