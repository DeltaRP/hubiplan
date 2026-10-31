"""Digitaler Mitgliedsausweis: QR-Code mit zufälligem Schlüssel je Mitgliedschaft.

Der QR-Code enthält nur einen Link mit einem zufälligen, nicht erratbaren
Schlüssel, keine Mitgliedsnummer. Wer ihn scannt, sieht eine öffentliche Seite
mit Name, Foto (nur mit Einwilligung), aktuellem Status, Verein und Abteilung.

Anders als bei Upload- und Anmeldelinks wird der Schlüssel im Klartext
gespeichert: Der Ausweis muss jederzeit neu gedruckt und im Mitgliederbereich
angezeigt werden können, und er öffnet nur diese eine, bewusst öffentliche
Seite. Neu erzeugen ersetzt den Schlüssel (alte Ausdrucke werden ungültig),
Sperren macht ihn ungültig, bis der Ausweis wieder freigegeben wird.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models


def new_token() -> str:
    return secrets.token_urlsafe(24)


class MemberCard(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name="Verein",
        on_delete=models.CASCADE,
        related_name="+",
    )
    membership = models.OneToOneField(
        "members.Membership", on_delete=models.CASCADE, related_name="card"
    )
    token = models.CharField(max_length=64, unique=True, default=new_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Zeitpunkt des aktuellen Schlüssels (beim Neu-Erzeugen aktualisiert)
    issued_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField("gesperrt am", null=True, blank=True)

    class Meta:
        verbose_name = "Mitgliedsausweis"
        verbose_name_plural = "Mitgliedsausweise"

    def __str__(self) -> str:
        return f"Mitgliedsausweis {self.membership_id}"

    @property
    def url(self) -> str:
        return f"{settings.FRONTEND_URL}/ausweis/{self.token}"
