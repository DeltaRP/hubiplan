"""Mitgliederfotos und persönliche Upload-Links.

Fotos liegen im privaten Speicher und werden nur über die API mit Rechteprüfung
ausgeliefert. Upload-Links speichern nur den Hash ihres Tokens; das Token selbst
enthält keinen Personenbezug.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage


def photo_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"photos/{instance.organization_id}/{instance.membership_id}-{stamp}-{filename}"


class MemberPhoto(models.Model):
    class Status(models.TextChoices):
        APPROVED = "approved", "freigegeben"
        PENDING = "pending", "wartet auf Freigabe"

    class Source(models.TextChoices):
        BOARD = "board", "Vorstand"
        MEMBER = "member", "Mitglied (Upload-Link)"
        APP = "app", "Mitglied (App)"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="photos"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPROVED)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.BOARD)
    image = PrivateFileField(storage=private_storage, upload_to=photo_path)
    thumbnail = PrivateFileField(storage=private_storage, upload_to=photo_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mitgliederfoto"
        verbose_name_plural = "Mitgliederfotos"
        constraints = [
            # Höchstens ein freigegebenes und ein wartendes Foto je Mitgliedschaft
            models.UniqueConstraint(fields=["membership", "status"], name="foto_je_status")
        ]

    def __str__(self) -> str:
        return f"Foto {self.membership_id} ({self.get_status_display()})"

    def delete_files(self) -> None:
        """Dateien nach dem Commit löschen (bei Rollback bleiben sie)."""
        from core.files import delete_on_commit

        delete_on_commit(self.image, self.thumbnail)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PhotoUploadLink(models.Model):
    """Persönlicher, zeitlich begrenzter und einmal nutzbarer Upload-Link."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="photo_links"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    sent_to = models.EmailField(blank=True)

    class Meta:
        verbose_name = "Foto-Upload-Link"
        verbose_name_plural = "Foto-Upload-Links"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Upload-Link {self.pk}"

    @classmethod
    def new_token(cls) -> str:
        return secrets.token_urlsafe(32)

    @property
    def state(self) -> str:
        if self.revoked_at:
            return "revoked"
        if self.used_at:
            return "used"
        if self.expires_at <= timezone.now():
            return "expired"
        return "open"
