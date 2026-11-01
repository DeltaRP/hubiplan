"""Anmeldung an der Nextcloud (und ähnlichen Diensten) mit dem HUBIplan-Konto.

HUBIplan ist dafür Anbieter nach OpenID Connect (siehe ``provider``). Jede Einheit trägt
ihre Nextcloud als ``Client`` ein und legt fest, wer sich anmelden darf und welche
Gruppen mitgehen. Codes und Zugriffsschlüssel liegen nur kurz im Cache, nie in der
Datenbank.
"""

from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlsplit

from django.conf import settings
from django.db import models


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_client_id() -> str:
    return "hp-" + secrets.token_urlsafe(18)


def new_salt() -> str:
    return secrets.token_urlsafe(32)


class Client(models.Model):
    class Audience(models.TextChoices):
        BOARD = "board", "Vorstand und Rollen"
        MEMBERS = "members", "zusätzlich Mitglieder mit Zugang"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="oidc_clients"
    )
    name = models.CharField("Name", max_length=100, default="Nextcloud")
    # Adresse der Nextcloud, z. B. https://cloud.example.org (ohne /index.php)
    base_url = models.URLField("Adresse der Nextcloud", max_length=300)
    client_id = models.CharField("Client-ID", max_length=64, unique=True, default=new_client_id)
    # Nur die Prüfsumme; das Geheimnis sieht man einmal beim Anlegen bzw. Erneuern
    secret_hash = models.CharField(max_length=64)
    # Macht die Kennung (sub) je Dienst verschieden: Zwei Dienste können ihre Nutzer
    # nicht über die Kennung zusammenführen.
    subject_salt = models.CharField(max_length=64, default=new_salt)
    audience = models.CharField(
        "Wer darf sich anmelden", max_length=10, choices=Audience.choices, default=Audience.BOARD
    )
    require_mfa = models.BooleanField("nur mit Zwei-Faktor-Anmeldung", default=False)
    groups_board = models.BooleanField("Gruppe „Vorstand“", default=True)
    groups_roles = models.BooleanField("je Rolle eine Gruppe", default=True)
    groups_units = models.BooleanField("je Untereinheit eine Gruppe", default=True)
    groups_members = models.BooleanField("Gruppe „Mitglieder“", default=True)
    is_active = models.BooleanField("eingeschaltet", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField("zuletzt benutzt", null=True, blank=True)

    # Im Änderungsprotokoll nie Geheimnis oder Salz
    audit_fields = frozenset(
        {
            "name",
            "base_url",
            "client_id",
            "audience",
            "require_mfa",
            "groups_board",
            "groups_roles",
            "groups_units",
            "groups_members",
            "is_active",
        }
    )

    class Meta:
        verbose_name = "Nextcloud-Anmeldung"
        verbose_name_plural = "Nextcloud-Anmeldungen"
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.host})"

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).netloc

    def set_secret(self) -> str:
        secret = secrets.token_urlsafe(32)
        self.secret_hash = hash_secret(secret)
        return secret

    def check_secret(self, secret: str) -> bool:
        return bool(self.secret_hash) and secrets.compare_digest(
            self.secret_hash, hash_secret(secret or "")
        )

    @property
    def redirect_uris(self) -> list[str]:
        """Rückleitungen der Nextcloud-App „user_oidc“ (mit und ohne index.php)."""
        base = self.base_url.rstrip("/")
        return [f"{base}/apps/user_oidc/code", f"{base}/index.php/apps/user_oidc/code"]
