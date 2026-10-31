"""Zurückgehaltene Nachrichten aus dem Kontaktformular der Webseite.

Unauffällige Nachrichten gehen sofort per Mail an die Empfänger und werden hier
nicht gespeichert. Nur Nachrichten, die die Inhaltsprüfung auffällig findet,
warten hier auf Freigabe; nach 7 Tagen werden sie gelöscht.
"""

from __future__ import annotations

from django.db import models

HELD_DAYS = 7


class HeldMessage(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    website = models.ForeignKey(
        "website.Website", on_delete=models.CASCADE, related_name="held_messages"
    )
    recipient = models.CharField("Empfänger (Kennung)", max_length=40)
    recipient_name = models.CharField("Empfänger", max_length=200)
    sender_name = models.CharField("Name", max_length=100)
    sender_email = models.EmailField("E-Mail")
    subject = models.CharField("Betreff", max_length=150)
    body = models.TextField("Nachricht", max_length=5000)
    reason = models.CharField("Grund", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "zurückgehaltene Nachricht"
        verbose_name_plural = "zurückgehaltene Nachrichten"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Nachricht von {self.sender_name}"
