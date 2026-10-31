"""Zugänge für Mitglieder und Abteilungen (Meilenstein 7).

- ``PortalAccess`` verknüpft ein Benutzerkonto mit einer Mitgliedschaft. Darüber
  sieht das Mitglied seine Daten im Mitgliederbereich, und Inhaber von
  Abteilungsrollen bekommen die Rechte ihrer Rolle.
- ``LoginLink`` ist ein persönlicher, einmal nutzbarer Anmeldelink.
- ``ChangeRequest`` ist eine Änderungsmeldung des Mitglieds, die der Vorstand
  bestätigt oder ablehnt.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PortalAccess(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name="Verein",
        on_delete=models.CASCADE,
        related_name="+",
    )
    membership = models.OneToOneField(
        "members.Membership", on_delete=models.CASCADE, related_name="portal_access"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portal_accesses"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zugang"
        verbose_name_plural = "Zugänge"

    def __str__(self) -> str:
        return f"Zugang {self.user} → Mitgliedschaft {self.membership_id}"


class LoginLink(models.Model):
    """Persönlicher Anmeldelink ohne Passwort: einmal nutzbar, zeitlich begrenzt."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_links"
    )
    # Verein bzw. Abteilung, die den Link erzeugt hat (leer = selbst angefordert)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Anmeldelink"
        verbose_name_plural = "Anmeldelinks"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Anmeldelink {self.pk}"

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)

    @property
    def is_open(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class ChangeRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "offen"
        ACCEPTED = "accepted", "übernommen"
        REJECTED = "rejected", "abgelehnt"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="change_requests"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="gemeldet von",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    # Nur die geänderten Felder: {"email": "neu@…", "street": …}
    data = models.JSONField("Änderungen", default=dict)
    # Werte zum Zeitpunkt der Meldung (zum Vergleich)
    previous = models.JSONField("bisherige Werte", default=dict)
    message = models.CharField("Nachricht", max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    response = models.CharField("Antwort", max_length=500, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Änderungsmeldung"
        verbose_name_plural = "Änderungsmeldungen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Änderungsmeldung {self.pk} ({self.get_status_display()})"
