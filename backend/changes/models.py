"""Änderungspakete für Rückgängig, Wiederherstellen und Papierkorb.

Jede Anfrage, die Daten ändert, ergibt höchstens ein Änderungspaket
(``ChangeSet``). Darin steht je geändertem Datensatz ein ``ChangeRecord`` mit den
Rohwerten vorher und nachher, auch für alles, was beim Löschen mit wegfällt.
Rückgängig spielt die Einträge in umgekehrter Reihenfolge zurück. Pakete werden
nach ``RETENTION_DAYS`` Tagen gelöscht (Datenschutz).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.encfields import EncryptedJSONField

RETENTION_DAYS = 30


class ChangeSet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    # Grund, warum das Paket nicht rückgängig gemacht werden kann (leer = möglich)
    blocked_reason = models.CharField(max_length=200, blank=True)
    # Dieses Paket macht ein anderes rückgängig (Rückgängig bzw. Wiederherstellen)
    reverts = models.UUIDField(null=True, blank=True, db_index=True)
    # Das Paket wurde durch dieses Paket rückgängig gemacht
    reverted_by = models.UUIDField(null=True, blank=True)
    has_create = models.BooleanField(default=False)
    has_delete = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Änderungspaket"
        verbose_name_plural = "Änderungspakete"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.pk}"


class ChangeRecord(models.Model):
    class Operation(models.TextChoices):
        CREATE = "create", "angelegt"
        UPDATE = "update", "geändert"
        DELETE = "delete", "gelöscht"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Ohne Datenbank-Fremdschlüssel: die Einträge entstehen vor dem Paket.
    change_set = models.ForeignKey(
        ChangeSet, on_delete=models.CASCADE, related_name="records", db_constraint=False
    )
    seq = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    model = models.CharField(max_length=100)  # app_label.model_name
    object_id = models.CharField(max_length=50)
    operation = models.CharField(max_length=10, choices=Operation.choices)
    # Verschlüsselt mit dem Schlüssel des Vereins
    before = EncryptedJSONField(null=True, blank=True)
    after = EncryptedJSONField(null=True, blank=True)
    # Betroffene Person (zum Löschen nach Ablauf der Löschfrist)
    person_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Änderung"
        verbose_name_plural = "Änderungen"
        ordering = ["change_set", "seq"]
        indexes = [models.Index(fields=["model", "object_id"])]

    def __str__(self) -> str:
        return f"{self.operation} {self.model} {self.object_id}"


class RequestKey(models.Model):
    """Schlüssel einer schon ausgeführten Anfrage (gegen doppeltes Absenden).

    Der Browser schickt bei Zahlungen und Aufnahmen einen Schlüssel je Formular mit.
    Kommt dieselbe Anfrage erneut (Doppelklick, Wiederholung nach Netzfehler), liefert
    der Server das Ergebnis der ersten aus, statt noch einmal zu buchen.
    """

    key = models.UUIDField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=50)
    # Prüfsumme der Angaben: derselbe Schlüssel mit anderen Angaben ist ein Konflikt
    fingerprint = models.CharField(max_length=64, blank=True, default="")
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Anfrageschlüssel"
        verbose_name_plural = "Anfrageschlüssel"

    def __str__(self) -> str:
        return f"{self.scope} {self.key}"
