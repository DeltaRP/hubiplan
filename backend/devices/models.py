"""Geräte der HUBIplan-App (Android) und Codes zum Verbinden.

Ein Gerät meldet sich einmal an (QR-Code aus „Mein Konto“, Anmeldelink oder
Passwort mit 2FA) und bekommt einen eigenen, widerrufbaren Schlüssel. In der
Datenbank steht nur dessen Prüfsumme, wie bei Anmeldelinks.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy

# Ein Gerät, das so lange nicht mehr da war, muss sich neu verbinden
IDLE_DAYS = 180
# Fachfrage 3 (31.10.b): Geräte ohne Schlüsselpaar (Apps vor 0.15) gelten höchstens so lange,
# dann verbindet die App sich neu und meldet dabei ein Schlüsselpaar an
UNBOUND_DAYS = 60
# QR-Code zum Verbinden
PAIRING_MINUTES = 10
TOKEN_PREFIX = "hpd_"  # noqa: S105  (Kennung, kein Passwort)
# Vorstandszugang der App (Schritt A8): eigener Schlüssel nur für /api/app/v1/admin/u/
ADMIN_PREFIX = "hpa_"
ADMIN_DAYS = 30
ADMIN_IDLE_DAYS = 14


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Device(models.Model):
    class Platform(models.TextChoices):
        ANDROID = "android", gettext_lazy("Android")
        IOS = "ios", "iOS"
        OTHER = "other", "anderes"

    class Push(models.TextChoices):
        NONE = "none", gettext_lazy("kein Push (Abruf)")
        UNIFIEDPUSH = "unifiedpush", gettext_lazy("UnifiedPush")
        FCM = "fcm", gettext_lazy("Google (FCM)")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    name = models.CharField("Gerätename", max_length=100)
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.ANDROID)
    app_version = models.CharField("App-Version", max_length=30, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    # Push (Schritt A4): Web-Push-Endpunkt und Schlüssel des Geräts
    push_kind = models.CharField(max_length=12, choices=Push.choices, default=Push.NONE)
    push_endpoint = models.URLField(max_length=1000, blank=True)
    push_p256dh = models.CharField(max_length=200, blank=True)
    push_auth = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Vorstandszugang: nur mit Passwort und 2FA freigeschaltet, läuft von selbst ab
    admin_token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    admin_until = models.DateTimeField("Verwaltung freigeschaltet bis", null=True, blank=True)
    admin_used_at = models.DateTimeField(null=True, blank=True)
    # Härtung H7: öffentliche Schlüssel aus dem Keystore des Geräts (leer: ältere App)
    device_key = models.CharField("Geräteschlüsselpaar (öffentlich)", max_length=120, blank=True)
    admin_key = models.CharField("Vorstands-Schlüsselpaar (öffentlich)", max_length=120, blank=True)
    # Erneuerung des Geräteschlüssels: wann ausgestellt, Vorgänger (gilt bis kurz nach der
    # ersten Nutzung des neuen) und ausgemusterte Prüfsummen (Nutzung = Kopie)
    token_issued_at = models.DateTimeField(null=True, blank=True)
    previous_token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    previous_until = models.DateTimeField(null=True, blank=True)
    retired_hashes = models.JSONField(default=list, blank=True)
    revoked_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Gerät"
        verbose_name_plural = "Geräte"
        ordering = ["-last_seen_at", "pk"]
        # Suche nach ausgemusterten Schlüsseln (Kopie erkennen) ohne Durchsuchen aller Zeilen
        indexes = [GinIndex(fields=["retired_hashes"], name="device_retired_hashes_gin")]

    def __str__(self) -> str:
        return f"Gerät {self.name}"

    @staticmethod
    def new_token() -> str:
        return TOKEN_PREFIX + secrets.token_urlsafe(32)

    @staticmethod
    def new_admin_token() -> str:
        return ADMIN_PREFIX + secrets.token_urlsafe(32)

    @property
    def admin_active(self) -> bool:
        now = timezone.now()
        return bool(
            self.admin_token_hash
            and self.admin_until
            and self.admin_until > now
            and (self.admin_used_at or now) > now - datetime.timedelta(days=ADMIN_IDLE_DAYS)
        )

    def lock_admin(self) -> None:
        self.admin_token_hash = ""
        self.admin_until = None
        self.admin_used_at = None
        self.admin_key = ""
        self.save(update_fields=["admin_token_hash", "admin_until", "admin_used_at", "admin_key"])

    @property
    def issued_at(self) -> datetime.datetime:
        return self.token_issued_at or self.created_at

    @property
    def renew_due(self) -> bool:
        """Geräteschlüssel erneuern (nur mit Geräteschlüsselpaar möglich)."""
        from .devicekey import RENEW_DAYS

        return bool(self.device_key) and self.issued_at < timezone.now() - datetime.timedelta(
            days=RENEW_DAYS
        )

    @property
    def renew_required(self) -> bool:
        """Zu lange nicht erneuert: der Schlüssel taugt nur noch zum Erneuern."""
        from .devicekey import RENEW_MAX_DAYS

        return bool(self.device_key) and self.issued_at < timezone.now() - datetime.timedelta(
            days=RENEW_MAX_DAYS
        )

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        if not self.device_key and self.issued_at < now - datetime.timedelta(days=UNBOUND_DAYS):
            return False
        return self.revoked_at is None and self.last_seen_at > now - datetime.timedelta(
            days=IDLE_DAYS
        )


class PairingCode(models.Model):
    """Einmalcode im QR-Code: verbindet die App mit dem Konto, das ihn erzeugt hat."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pairing_codes"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    # Gerät, das sich damit verbunden hat (Anzeige im Browser: „Verbunden: …“)
    device = models.ForeignKey(
        "Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Code zum Verbinden der App"
        verbose_name_plural = "Codes zum Verbinden der App"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Verbindungscode {self.pk}"

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(24)

    @property
    def is_open(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()
