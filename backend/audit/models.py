from django.conf import settings
from django.db import models

from core.encfields import EncryptedJSONField


class AuditEntry(models.Model):
    """Wer hat wann was geändert."""

    class Action(models.TextChoices):
        CREATE = "create", "angelegt"
        UPDATE = "update", "geändert"
        DELETE = "delete", "gelöscht"
        VIEW = "view", "angesehen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="audit_entries"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    user_email = models.EmailField(blank=True)  # bleibt lesbar, falls das Konto gelöscht wird
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=10, choices=Action.choices)
    object_type = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50)
    object_repr = models.CharField(max_length=200)
    # Verschlüsselt mit dem Schlüssel des Vereins; die Prüfsumme gilt für den Klartext
    changes = EncryptedJSONField(default=dict, blank=True)
    # Betroffene Person (für den Reiter „Verlauf“ in der Mitgliedsakte)
    person_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    # Änderungspaket der Anfrage (für „Rückgängig“ aus dem Protokoll)
    change_set = models.UUIDField(null=True, blank=True, db_index=True)
    # Woher die Änderung kam, z. B. „App (Pixel 8)“; leer = Browser oder System
    via = models.CharField(max_length=100, blank=True, default="")
    # Verkettung (Finanzamt-Prüfung C3): laufende Nummer je Organisation, Prüfsumme des
    # Vorgängers und eigene Prüfsumme über alle Angaben; leer = noch nicht versiegelt
    seq = models.BigIntegerField(null=True, blank=True)
    prev_hash = models.CharField(max_length=64, blank=True, default="", db_default="")
    hash = models.CharField(max_length=64, blank=True, default="", db_default="")
    changes_hash = models.CharField(max_length=64, blank=True, default="", db_default="")
    # Inhalt aus Datenschutzgründen geleert (Löschfrist); die Kette bleibt prüfbar
    cleared = models.BooleanField(default=False, db_default=False)

    class Meta:
        verbose_name = "Protokolleintrag"
        verbose_name_plural = "Änderungsprotokoll"
        ordering = ["-timestamp", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "seq"], name="audit_seq_eindeutig")
        ]

    def __str__(self) -> str:
        return f"{self.timestamp:%d.%m.%Y %H:%M} {self.user_email} {self.action} {self.object_repr}"


class AuditCheck(models.Model):
    """Ergebnis der letzten Prüfung der Protokollkette einer Organisation."""

    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, related_name="audit_check"
    )
    checked_at = models.DateTimeField()
    ok = models.BooleanField()
    entries = models.PositiveIntegerField(default=0)
    cleared = models.PositiveIntegerField(default=0)
    head_seq = models.BigIntegerField(null=True, blank=True)
    head_hash = models.CharField(max_length=64, blank=True, default="")
    problems = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Prüfung des Änderungsprotokolls"

    def __str__(self) -> str:
        return f"Prüfung {self.checked_at:%d.%m.%Y %H:%M}: {'ok' if self.ok else 'verändert'}"
