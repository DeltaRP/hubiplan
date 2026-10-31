"""Vollständiger Export einer Organisation als JSON (oder ZIP mit Dateien) und
Import auf der nächsthöheren Ebene.

Ein ``TransferJob`` gehört der Organisation, in der er angestoßen wurde: beim
Export der exportierenden, beim Import der übergeordneten (Plattform, Dachverband
oder Verein). Die Dateien liegen im privaten Speicher und werden nach
``KEEP_DAYS`` Tagen gelöscht.
"""

from __future__ import annotations

import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone

from exchange.models import private_storage

KEEP_DAYS = 7


def transfer_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"datatransfer/{instance.organization_id}/{stamp}-{filename}"


def default_expiry():
    return timezone.now() + datetime.timedelta(days=KEEP_DAYS)


class TransferJob(models.Model):
    class Direction(models.TextChoices):
        EXPORT = "export", "Export"
        IMPORT = "import", "Import"

    class Kind(models.TextChoices):
        ORGANIZATION = "organization", "Organisation"
        DEPARTMENT = "department", "Abteilung"

    class Status(models.TextChoices):
        PENDING = "pending", "wartet"
        RUNNING = "running", "läuft"
        CHECKED = "checked", "geprüft"
        DONE = "done", "fertig"
        FAILED = "failed", "fehlgeschlagen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ORGANIZATION)
    # Export einer Abteilung bzw. beim Import die neu angelegte Abteilung
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Export der Plattform: die exportierte Organisation (sonst leer = ``organization``)
    subject = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    with_files = models.BooleanField("mit Dateien", default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    file = models.FileField(storage=private_storage, upload_to=transfer_path, blank=True)
    file_name = models.CharField(max_length=200, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    # Export: Anzahlen. Import: Vorschau mit Anzahlen, Warnungen, Fehlern, Dubletten.
    summary = models.JSONField(default=dict, blank=True)
    preview = models.JSONField(default=dict, blank=True)
    # Import: Entscheidungen zu Dubletten und Optionen (Name, Einladungen)
    decisions = models.JSONField(default=dict, blank=True)
    options = models.JSONField(default=dict, blank=True)
    # Import: neu angelegte Organisation
    result_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(default=default_expiry)

    class Meta:
        verbose_name = "Datenübernahme"
        verbose_name_plural = "Datenübernahmen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.file_name or self.pk}"
