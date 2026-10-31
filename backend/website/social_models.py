"""Beiträge aus Instagram und Facebook für die Webseite.

HUBIplan holt die eigenen Beiträge einer Einheit serverseitig über die offizielle
Meta-Schnittstelle ab und speichert Text und Bilder selbst. Besucher der Webseite
haben keinen Kontakt zu Meta. Jede Einheit nutzt ihre eigene Meta-App; App-ID,
App-Geheimnis und Zugang liegen nur hier und verschlüsselt (Konzept
``konzepte/social-media-feed.md``).
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models

from exchange.models import private_storage

MAX_POSTS_DEFAULT = 24


class SocialFeed(models.Model):
    """Ein verbundener Kanal (Instagram-Profikonto oder Facebook-Seite)."""

    class Kind(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        FACEBOOK = "facebook", "Facebook-Seite"

    class Mode(models.TextChoices):
        AUTO = "auto", "automatisch zeigen"
        APPROVAL = "approval", "erst nach Freigabe"

    class Status(models.TextChoices):
        NEW = "new", "nicht verbunden"
        CHOOSE = "choose", "Seite auswählen"
        OK = "ok", "verbunden"
        ERROR = "error", "Störung"
        EXPIRED = "expired", "neu verbinden"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    website = models.ForeignKey(
        "website.Website", on_delete=models.CASCADE, related_name="social_feeds"
    )
    # Kanal einer Untereinheit (erscheint auf ihrer Seite); leer = Kanal der Einheit selbst
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Untereinheit",
    )
    kind = models.CharField("Art", max_length=10, choices=Kind.choices)
    mode = models.CharField("Neue Beiträge", max_length=10, choices=Mode.choices, default=Mode.AUTO)
    max_posts = models.PositiveSmallIntegerField("Beiträge halten", default=MAX_POSTS_DEFAULT)
    show_link = models.BooleanField("Link zum Beitrag zeigen", default=True)
    strip_hashtags = models.BooleanField("Hashtags am Ende weglassen", default=True)
    is_active = models.BooleanField("Abruf aktiv", default=True)
    # Eigene Meta-App der Einheit (Geheimnis und Zugang verschlüsselt)
    app_id = models.CharField("App-ID", max_length=40, blank=True)
    # Instagram über die Facebook-Anmeldung („Unified Login“, für neue Meta-Apps der
    # einzige Weg): das Profikonto hängt an einer Facebook-Seite, Zugang = Seiten-Zugang.
    # Aus: alter Weg „Instagram-Login“ (graph.instagram.com), nur für ältere Apps.
    via_facebook = models.BooleanField("Instagram über Facebook-Anmeldung", default=True)
    # Facebook Login for Business: Konfiguration aus der Meta-App (statt Berechtigungsliste)
    config_id = models.CharField("Konfigurations-ID", max_length=40, blank=True)
    app_secret = models.TextField(blank=True)
    access_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    token_refreshed_at = models.DateTimeField(null=True, blank=True)
    # Bei mehreren Facebook-Seiten: Auswahl (verschlüsselt, mit Seiten-Zugängen)
    pending_pages = models.TextField(blank=True)
    account_id = models.CharField(max_length=40, blank=True)
    account_name = models.CharField("Konto", max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    last_error = models.CharField(max_length=500, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    warned_at = models.DateTimeField(null=True, blank=True)
    # Anmeldung bei Meta: Einmalwert (nur als Hash) mit Ablauf und Person
    oauth_state = models.CharField(max_length=64, blank=True)
    oauth_started_at = models.DateTimeField(null=True, blank=True)
    oauth_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    connected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Social-Media-Kanal der Webseite"
        verbose_name_plural = "Social-Media-Kanäle der Webseite"
        ordering = ["department_id", "kind", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["website", "department", "kind"],
                name="socialfeed_unique_kind",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        name = self.account_name or self.get_kind_display()
        return f"{self.get_kind_display()}: {name}"

    @property
    def is_connected(self) -> bool:
        return bool(self.access_token) and self.status in (self.Status.OK, self.Status.ERROR)


def post_image_path(instance, filename: str) -> str:
    return f"website/{instance.organization_id}/social/{instance.key}-{filename}"


class SocialPost(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Bild"
        ALBUM = "album", "Album"
        VIDEO = "video", "Video"
        TEXT = "text", "nur Text"

    class State(models.TextChoices):
        VISIBLE = "visible", "sichtbar"
        PENDING = "pending", "wartet auf Freigabe"
        HIDDEN = "hidden", "ausgeblendet"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    feed = models.ForeignKey(SocialFeed, on_delete=models.CASCADE, related_name="posts")
    external_id = models.CharField(max_length=80)
    media_type = models.CharField(max_length=10, choices=MediaType.choices)
    text = models.TextField(blank=True)
    permalink = models.URLField(max_length=500, blank=True)
    published_at = models.DateTimeField()
    state = models.CharField(max_length=10, choices=State.choices, default=State.VISIBLE)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Social-Media-Beitrag"
        verbose_name_plural = "Social-Media-Beiträge"
        ordering = ["-published_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["feed", "external_id"], name="socialpost_unique")
        ]

    def __str__(self) -> str:
        return f"Beitrag vom {self.published_at:%d.%m.%Y}"


class SocialPostImage(models.Model):
    """Bild eines Beitrags, neu geschrieben ohne Metadaten (bei Videos das Vorschaubild)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    post = models.ForeignKey(SocialPost, on_delete=models.CASCADE, related_name="images")
    position = models.PositiveSmallIntegerField(default=0)
    key = models.CharField(max_length=24, unique=True)
    external_id = models.CharField(max_length=80, blank=True)
    file = models.FileField(storage=private_storage, upload_to=post_image_path)
    small = models.FileField(storage=private_storage, upload_to=post_image_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    is_video = models.BooleanField(default=False)
    alt_text = models.CharField("Alternativtext", max_length=300, blank=True)

    class Meta:
        ordering = ["post_id", "position", "pk"]

    def __str__(self) -> str:
        return self.alt_text or f"Bild {self.position + 1}"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(12)
