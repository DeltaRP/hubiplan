"""Dokumentenablage von Dachverbänden, Vereinen und Abteilungen.

- ``Folder``: Ordner einer Organisation oder einer Abteilung, mit Sichtbarkeit.
- ``Document``: Dokument im Ordner (Titel, Datum, Bemerkung); gelöschte
  Dokumente bleiben 30 Tage im Papierkorb (``deleted_at``).
- ``DocumentVersion``: hochgeladene Datei; jede neue Fassung bleibt erhalten,
  aktuell ist die jüngste.

Die Satzung liegt weiter in der App ``statutes`` und erscheint in der Ablage als
fester Ordner. Dateien gelöschter Fassungen entfernt erst die tägliche
Aufräumaufgabe (``documents.services.purge``), damit Rückgängig sie wiederherstellen kann.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def document_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"documents/{instance.organization_id}/{stamp}-{filename}"


class Folder(models.Model):
    class Visibility(models.TextChoices):
        BOARD = "board", "nur Vorstand"
        CLUBS = "clubs", "Vereine des Dachverbands"
        MEMBERS = "members", "alle Mitglieder"
        PUBLIC = "public", "öffentlich per Link"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Leer: Ablage der Organisation selbst, sonst die einer Abteilung
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Abteilung",
    )
    name = models.CharField("Name", max_length=100)
    visibility = models.CharField(
        "Sichtbar für", max_length=10, choices=Visibility.choices, default=Visibility.BOARD
    )
    # Nach oben freigegeben: Abteilungsordner für den Vereinsvorstand, Vereinsordner
    # für den Vorstand des Dachverbands (nur lesen). Sonst sieht die höhere Ebene nichts.
    shared_up = models.BooleanField("nach oben freigegeben", default=False)
    # Bleibt beim Ändern der Sichtbarkeit gleich, damit Links stabil sind
    public_key = models.CharField(max_length=40, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Dokumentenordner"
        verbose_name_plural = "Dokumentenordner"
        ordering = ["name", "pk"]
        indexes = [models.Index(fields=["organization", "department"])]

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(18)


class Document(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Abteilung",
    )
    folder = models.ForeignKey(
        Folder, on_delete=models.CASCADE, related_name="documents", verbose_name="Ordner"
    )
    title = models.CharField("Titel", max_length=200)
    date = models.DateField("Datum", null=True, blank=True)
    note = models.CharField("Bemerkung", max_length=500, blank=True)
    deleted_at = models.DateTimeField("gelöscht am", null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Dokument"
        verbose_name_plural = "Dokumente"
        ordering = ["-date", "title", "pk"]
        indexes = [models.Index(fields=["organization", "department"])]

    def __str__(self) -> str:
        return self.title


class DocumentVersion(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Abteilung",
    )
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="versions", verbose_name="Dokument"
    )
    file = PrivateFileField("Datei", storage=private_storage, upload_to=document_path)
    name = models.CharField("Dateiname", max_length=200)
    size = models.PositiveIntegerField("Größe", default=0)
    content_type = models.CharField("Dateiart", max_length=100)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField("hochgeladen am", default=timezone.now)

    class Meta:
        verbose_name = "Dokumentfassung"
        verbose_name_plural = "Dokumentfassungen"
        ordering = ["-uploaded_at", "-pk"]

    def __str__(self) -> str:
        return self.name
