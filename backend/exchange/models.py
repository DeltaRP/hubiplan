"""Import von Altdaten und Export von Mitgliederlisten (Meilenstein 5).

Hochgeladene und erzeugte Dateien liegen im privaten Speicher (nicht unter
/media) und werden nur über die API mit Berechtigungsprüfung ausgeliefert.
"""

from __future__ import annotations

from django.conf import settings
from django.core.signals import setting_changed
from django.db import models
from django.dispatch import receiver
from django.utils.functional import LazyObject, empty

from core.privatefiles import PrivateFileField


class PrivateStorage(LazyObject):
    def _setup(self):
        from core.privatefiles import EncryptedStorage

        # Verschlüsselt mit dem Schlüssel des Vereins (core/crypto.py)
        self._wrapped = EncryptedStorage(location=settings.PRIVATE_ROOT, base_url=None)


_private = PrivateStorage()


@receiver(setting_changed)
def _reset_private(*, setting, **kwargs):
    # Tests setzen PRIVATE_ROOT je Test um; sonst bliebe der erste Pfad hängen
    # und parallele Testläufe teilten sich ein Verzeichnis.
    if setting == "PRIVATE_ROOT":
        _private._wrapped = empty


def private_storage():
    """Privater Speicher. Als Funktion übergeben, damit Migrationen keinen
    rechnerabhängigen Pfad enthalten (Django ruft sie beim Anlegen des Felds auf)."""
    return _private


# Aufbewahrung (Gesamtaudit 30.10.a, B-S03): erzeugte Listen 7 Tage, hochgeladene
# Importdateien samt Vorschau und Rückgängig-Journal 30 Tage nach Abschluss
EXPORT_KEEP_DAYS = 7
IMPORT_KEEP_DAYS = 30


def import_path(instance, filename: str) -> str:
    return f"imports/{instance.organization_id}/{filename}"


def export_path(instance, filename: str) -> str:
    return f"exports/{instance.organization_id}/{filename}"


class ExportTemplate(models.Model):
    """Gespeicherte Spaltenauswahl, z. B. „Geburtstagsliste“."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="export_templates"
    )
    name = models.CharField("Name", max_length=100)
    kind = models.CharField(max_length=20, default="members")
    columns = models.JSONField("Spalten", default=list)
    filters = models.JSONField("Filter", default=dict, blank=True)
    file_format = models.CharField(max_length=5, default="xlsx")
    orientation = models.CharField(max_length=10, default="portrait")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Exportvorlage"
        verbose_name_plural = "Exportvorlagen"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="exportvorlage_je_org")
        ]

    def __str__(self) -> str:
        return self.name


class ExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "wartet"
        RUNNING = "running", "läuft"
        DONE = "done", "fertig"
        FAILED = "failed", "fehlgeschlagen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="export_jobs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    kind = models.CharField(max_length=20, default="members")  # members | jubilees
    file_format = models.CharField(max_length=5)  # xlsx | pdf
    columns = models.JSONField(default=list)
    filters = models.JSONField(default=dict, blank=True)
    orientation = models.CharField(max_length=10, default="portrait")
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    file = PrivateFileField(storage=private_storage, upload_to=export_path, blank=True)
    file_name = models.CharField(max_length=200, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Datei nach Ablauf der Aufbewahrung gelöscht; der Protokolleintrag bleibt
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Export"
        verbose_name_plural = "Exporte"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Export {self.file_name or self.pk}"


class ImportTemplate(models.Model):
    """Gespeicherte Spaltenzuordnung für wiederkehrende Importe."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="import_templates"
    )
    name = models.CharField("Name", max_length=100)
    mapping = models.JSONField(default=dict)
    value_mapping = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Importvorlage"
        verbose_name_plural = "Importvorlagen"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="importvorlage_je_org")
        ]

    def __str__(self) -> str:
        return self.name


class ImportJob(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "hochgeladen"
        VALIDATING = "validating", "wird geprüft"
        VALIDATED = "validated", "geprüft"
        IMPORTING = "importing", "wird importiert"
        IMPORTED = "imported", "importiert"
        UNDONE = "undone", "rückgängig gemacht"
        FAILED = "failed", "fehlgeschlagen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="import_jobs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    file = PrivateFileField(storage=private_storage, upload_to=import_path)
    file_name = models.CharField(max_length=200)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADED)
    headers = models.JSONField(default=list)
    sample = models.JSONField(default=list)
    row_count = models.PositiveIntegerField(default=0)
    mapping = models.JSONField(default=dict, blank=True)  # Spaltennummer -> Ziel
    value_mapping = models.JSONField(default=dict, blank=True)  # Ziel -> {Dateiwert: Wert}
    options = models.JSONField(default=dict, blank=True)
    preview = models.JSONField(default=list, blank=True)  # Ergebnis der Prüfung je Person
    counts = models.JSONField(default=dict, blank=True)
    created = models.JSONField(default=dict, blank=True)  # angelegte Objekte (für „Rückgängig“)
    error_file = PrivateFileField(storage=private_storage, upload_to=import_path, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)
    # Datei, Vorschau und Journal nach Ablauf der Aufbewahrung gelöscht
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Import"
        verbose_name_plural = "Importe"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Import {self.file_name}"
