"""Postausgang: jede versendete E-Mail wird hier festgehalten.

Ohne hinterlegten Mailserver (Testserver) ist das zugleich das Test-Postfach:
Mails gehen nirgendwohin, sondern lassen sich in der Oberfläche ansehen.
"""

from django.db import models

from core.encfields import EncryptedTextField

# Text einer Mail nach Ablauf der Aufbewahrung (bleibt lesbar, damit die Löschung
# danach filtern kann)
EMPTIED = "(Inhalt nach Ablauf der Aufbewahrungsfrist entfernt)"


class OutgoingMail(models.Model):
    class Status(models.TextChoices):
        STORED = "stored", "nur gespeichert (kein Mailserver)"
        SENT = "sent", "versendet"
        FAILED = "failed", "Versand fehlgeschlagen"

    # Leer bei Mails ohne Organisationsbezug (z. B. „Passwort vergessen“)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="outgoing_mails",
    )
    to = models.TextField("Empfänger")
    reply_to = models.CharField("Antwort an", max_length=300, blank=True)
    subject = models.CharField("Betreff", max_length=300)
    # Verschlüsselt mit dem Schlüssel des Vereins (ohne Verein: der Plattform)
    body = EncryptedTextField("Text", plain_values=(EMPTIED,))
    # [{"name": ..., "path": ..., "size": ..., "content_type": ...}]
    attachments = models.JSONField("Anhänge", default=list, blank=True)
    kind = models.CharField("Art", max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.STORED)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "E-Mail"
        verbose_name_plural = "Postausgang"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.subject} → {self.to}"

    def encryption_org_id(self) -> int:
        if self.organization_id is not None:
            return self.organization_id
        from organizations.models import Organization

        return Organization.platform().pk
