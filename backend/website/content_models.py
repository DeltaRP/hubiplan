"""Inhalte der Webseite, die HUBIplan nicht aus der Vereinsverwaltung kennt:
Begrüßung, Textseiten (z. B. Geschichte), Kurztexte der Untereinheiten, Bilder.

Texte haben einen Entwurf und eine veröffentlichte Fassung. Sichtbar ist nur
die veröffentlichte (im Wartungsmodus auch die nur in der Vorschau). Jede
Veröffentlichung bleibt als Fassung erhalten und lässt sich zurückholen.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage

from .models import Website

# Bilderkarussell: Sekunden bis zum nächsten Bild
GALLERY_INTERVAL = 7
MIN_INTERVAL = 3
MAX_INTERVAL = 30

MAX_TITLE = 120
MAX_BODY = 50_000
SLUG_RE = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
# Adressen, die die Webseite selbst belegt
RESERVED_SLUGS = frozenset(
    {
        "vorstand",
        "termine",
        "zuege",
        "einheiten",
        "majestaeten",
        "chronik",
        "aemter",
        "kontakt",
        "impressum",
        "datenschutz",
        "vorschau",
        "bilder",
        "api",
        "static",
        "kalender",
    }
)


class WebsiteText(models.Model):
    class Kind(models.TextChoices):
        GREETING = "greeting", "Begrüßung (Startseite)"
        PAGE = "page", "Textseite"
        UNIT = "unit", "Text einer Untereinheit"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="texts")
    kind = models.CharField("Art", max_length=10, choices=Kind.choices)
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    slug = models.CharField("Adresse", max_length=60, blank=True)
    menu_position = models.PositiveSmallIntegerField("Reihenfolge im Menü", default=0)
    show_in_menu = models.BooleanField("im Menü zeigen", default=True)
    # Entwurf
    title = models.CharField("Titel", max_length=MAX_TITLE, blank=True)
    body = models.TextField("Text", max_length=MAX_BODY, blank=True)
    image = models.ForeignKey(
        "website.WebsiteImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Bild",
    )
    # Bilderkarussell der Begrüßung: IDs der Bilder in ihrer Reihenfolge
    gallery = models.JSONField("Bilderkarussell", default=list, blank=True)
    # Sekunden bis zum nächsten Bild, je Karussell einstellbar (Ralf 01.11.)
    gallery_interval = models.PositiveSmallIntegerField(
        "Wechsel nach (Sekunden)",
        default=GALLERY_INTERVAL,
        validators=[MinValueValidator(MIN_INTERVAL), MaxValueValidator(MAX_INTERVAL)],
    )
    # Beginnt mit einem zufälligen Bild statt mit dem ersten der Liste
    gallery_random = models.BooleanField("zufälliges Startbild", default=False)
    # Veröffentlicht
    published_title = models.CharField(max_length=MAX_TITLE, blank=True)
    published_body = models.TextField(blank=True)
    published_image = models.ForeignKey(
        "website.WebsiteImage", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    published_gallery = models.JSONField(default=list, blank=True)
    published_gallery_interval = models.PositiveSmallIntegerField(default=GALLERY_INTERVAL)
    published_gallery_random = models.BooleanField(default=False)
    published_at = models.DateTimeField("veröffentlicht am", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Text der Webseite"
        verbose_name_plural = "Texte der Webseite"
        ordering = ["kind", "menu_position", "title", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["website", "slug"],
                condition=models.Q(kind="page"),
                name="webseite_textseite_adresse",
            ),
            models.UniqueConstraint(
                fields=["website"],
                condition=models.Q(kind="greeting"),
                name="webseite_eine_begruessung",
            ),
            models.UniqueConstraint(
                fields=["website", "department"],
                condition=models.Q(kind="unit"),
                name="webseite_ein_text_je_einheit",
            ),
        ]

    def __str__(self) -> str:
        return self.title or self.get_kind_display()

    def save(self, *args, **kwargs):
        if self.kind == self.Kind.PAGE:
            from core.reorder import append_if_new

            append_if_new(
                self,
                "menu_position",
                WebsiteText.objects.filter(website_id=self.website_id, kind=self.Kind.PAGE),
            )
        super().save(*args, **kwargs)

    @property
    def is_published(self) -> bool:
        return self.published_at is not None

    @property
    def has_changes(self) -> bool:
        """Entwurf weicht von der veröffentlichten Fassung ab."""
        return (
            not self.is_published
            or self.title != self.published_title
            or self.body != self.published_body
            or self.image_id != self.published_image_id
            or (self.gallery or []) != (self.published_gallery or [])
            or self.gallery_interval != self.published_gallery_interval
            or self.gallery_random != self.published_gallery_random
        )

    def clean(self):
        import re

        if self.kind == self.Kind.PAGE:
            if not self.title.strip():
                raise ValidationError({"title": "Bitte einen Titel angeben."})
            if not re.match(SLUG_RE, self.slug or ""):
                raise ValidationError(
                    {"slug": "Nur Kleinbuchstaben, Ziffern und Bindestriche, z. B. „geschichte“."}
                )
            if self.slug in RESERVED_SLUGS:
                raise ValidationError({"slug": "Diese Adresse ist für die Webseite reserviert."})


class WebsiteRevision(models.Model):
    """Veröffentlichte Fassung eines Textes (Verlauf)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    text = models.ForeignKey(WebsiteText, on_delete=models.CASCADE, related_name="revisions")
    title = models.CharField(max_length=MAX_TITLE, blank=True)
    body = models.TextField(blank=True)
    image = models.ForeignKey(
        "website.WebsiteImage", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    gallery = models.JSONField(default=list, blank=True)
    gallery_interval = models.PositiveSmallIntegerField(default=GALLERY_INTERVAL)
    gallery_random = models.BooleanField(default=False)
    published_at = models.DateTimeField(default=timezone.now)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Fassung eines Textes der Webseite"
        verbose_name_plural = "Fassungen der Texte der Webseite"
        ordering = ["-published_at", "-pk"]

    def __str__(self) -> str:
        return f"Fassung vom {timezone.localtime(self.published_at):%d.%m.%Y %H:%M}"


def image_path(instance, filename: str) -> str:
    return f"website/{instance.organization_id}/{instance.key}-{filename}"


class WebsiteImage(models.Model):
    """Bild für die Webseite, beim Hochladen verkleinert und ohne Metadaten."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="images")
    # Öffentliche Kennung im Text (Markdown ``![Alt](bild:<key>)``) und in Adressen
    key = models.CharField(max_length=24, unique=True)
    file = PrivateFileField("Bild", storage=private_storage, upload_to=image_path)
    small = PrivateFileField("Bild klein", storage=private_storage, upload_to=image_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    caption = models.CharField("Bildunterschrift", max_length=300, blank=True)
    alt_text = models.CharField("Alternativtext", max_length=300, blank=True)
    # Bewusst ohne Beschreibung (reiner Schmuck): dann alt="" auf der Webseite,
    # sonst ersetzt die Bildunterschrift einen fehlenden Alternativtext
    decorative = models.BooleanField("nur Schmuck", default=False)
    # Original (höchstens 4000 px, ohne Metadaten) und gewählter Ausschnitt: Damit lässt
    # sich der Ausschnitt später neu wählen, ohne dass etwas verloren geht (Ralf 01.11.).
    # Ältere Bilder haben kein Original; dann gilt ``file`` als Original.
    original = PrivateFileField(
        "Original", storage=private_storage, upload_to=image_path, blank=True
    )
    # {"x", "y", "width", "height"} in Prozent des (gedrehten) Originals, "rotation",
    # "aspect" (Schlüssel des Formats); leer = ganzes Bild
    crop = models.JSONField("Ausschnitt", default=dict, blank=True)
    # Optional: gehört zu einer Untereinheit (nur Filter für die Auswahl, keine Sperre)
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="gehört zu",
    )
    # Steigt mit jedem neuen Ausschnitt oder Ersetzen: neue Adresse für Zwischenspeicher
    version = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Bild der Webseite"
        verbose_name_plural = "Bilder der Webseite"
        ordering = ["-uploaded_at", "-pk"]

    def __str__(self) -> str:
        return self.caption or self.alt_text or f"Bild {self.key}"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(12)

    @property
    def public_key(self) -> str:
        """Kennung in öffentlichen Adressen, mit Fassung (``<key>-v3``), damit nach
        neuem Ausschnitt kein Zwischenspeicher das alte Bild zeigt."""
        return f"{self.key}-v{self.version}" if self.version else self.key
