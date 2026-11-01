"""Satzungen, Beitragsordnungen und Gründungsurkunden der Einheiten.

Jede Einheit kann eine Satzung und optional eine Beitragsordnung und eine
Gründungsurkunde hinterlegen (Ralf 2026-10-31). Alle sind gleich gebaut und
unterscheiden sich nur in ``kind``. Jede hochgeladene Fassung bleibt erhalten;
aktuell ist die mit dem jüngsten Datum. Die Dokumente haben in der App keine
Funktion, können aber über einen öffentlichen Link (z. B. für Webseiten)
abgerufen werden, wenn das eingeschaltet ist.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage

MAX_STATUTE_BYTES = 20 * 1024 * 1024


class Kind(models.TextChoices):
    STATUTE = "statute", "Satzung"
    FEE_RULES = "fee_rules", "Beitragsordnung"
    FOUNDING_DEED = "founding_deed", "Gründungsurkunde"


def kind_label(kind: str) -> str:
    return Kind(kind).label if kind in Kind.values else Kind.STATUTE.label


def statute_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"statutes/{instance.organization_id}/{stamp}-{filename}"


class StatuteVersion(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Leer: Satzung der Organisation selbst, sonst die einer Abteilung
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Abteilung",
    )
    kind = models.CharField("Art", max_length=20, choices=Kind.choices, default=Kind.STATUTE)
    file = PrivateFileField("Datei", storage=private_storage, upload_to=statute_path)
    name = models.CharField("Dateiname", max_length=200)
    size = models.PositiveIntegerField("Größe", default=0)
    valid_from = models.DateField("gültig ab / beschlossen am")
    note = models.CharField("Bemerkung", max_length=500, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField("hochgeladen am", auto_now_add=True)

    class Meta:
        verbose_name = "Satzungsfassung"
        verbose_name_plural = "Satzungsfassungen"
        ordering = ["-valid_from", "-uploaded_at", "-pk"]
        indexes = [models.Index(fields=["organization", "department", "kind"])]

    def __str__(self) -> str:
        return f"{kind_label(self.kind)} vom {self.valid_from:%d.%m.%Y}"


class StatutePublication(models.Model):
    """Öffentlicher Abruf von Satzung, Beitragsordnung oder Gründungsurkunde einer Einheit."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField("Art", max_length=20, choices=Kind.choices, default=Kind.STATUTE)
    is_public = models.BooleanField("öffentlich abrufbar", default=False)
    # Bleibt beim Aus- und Einschalten gleich, damit Links auf Webseiten stabil sind
    public_key = models.CharField(max_length=40, unique=True)

    class Meta:
        verbose_name = "Veröffentlichung der Satzung"
        verbose_name_plural = "Veröffentlichungen der Satzung"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind"],
                condition=models.Q(department__isnull=True),
                name="satzung_veroeffentlichung_org_art",
            ),
            models.UniqueConstraint(
                fields=["department", "kind"],
                condition=models.Q(department__isnull=False),
                name="satzung_veroeffentlichung_abteilung_art",
            ),
        ]

    def __str__(self) -> str:
        return f"{kind_label(self.kind)} öffentlich: {self.is_public}"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(18)
