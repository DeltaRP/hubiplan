"""Terminkalender (Meilenstein 12).

Dachverband, Verein und Abteilung führen je einen eigenen Kalender. Ein Termin
gehört immer einer Organisation (Dachverband oder Verein); Abteilungstermine
tragen zusätzlich die Abteilung. So greift die Mandantentrennung wie überall.

Sichtbarkeit je Termin:

- ``public``  nach außen öffentlich: zusätzlich im öffentlichen Link (Webseite)
- ``members`` alle Mitglieder der Ebene (Dachverband: alle Vereine im Verband)
- ``board``   nur Vorstandsrollen der Ebene

Serientermine werden als Regel gespeichert; die einzelnen Termine rechnet
``events.recurrence`` erst beim Anzeigen aus. Abweichungen einzelner Termine
(verschoben oder abgesagt) stehen in ``EventException``.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from exchange.models import private_storage
from organizations.terms import fill

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS = 10
MAX_GUESTS = 10

color_validator = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Farbe bitte als #RRGGBB angeben.")


class EventCategory(models.Model):
    """Kategorie eines Kalenders, z. B. Versammlung, Fest, Umzug."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField("Name", max_length=80)
    color = models.CharField("Farbe", max_length=7, default="#2f6f4f", validators=[color_validator])
    is_active = models.BooleanField("aktiv", default=True)

    class Meta:
        verbose_name = "Terminkategorie"
        verbose_name_plural = "Terminkategorien"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="terminkategorie_name_je_org"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Event(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "nach außen öffentlich"
        MEMBERS = "members", "Mitglieder"
        BOARD = "board", "nur Vorstand"

    class Repeat(models.TextChoices):
        NONE = "none", "einmalig"
        WEEKLY = "weekly", "wöchentlich"
        MONTHLY = "monthly", "monatlich"
        YEARLY = "yearly", "jährlich"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Leer: Termin der Organisation selbst, sonst Termin einer Abteilung
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="Abteilung",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    title = models.CharField("Titel", max_length=200)
    description = models.TextField("Beschreibung", blank=True, max_length=5000)
    location = models.CharField("Ort", max_length=200, blank=True)
    address = models.CharField("Anschrift", max_length=300, blank=True)
    category = models.ForeignKey(
        EventCategory,
        verbose_name="Kategorie",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    all_day = models.BooleanField("ganztägig", default=False)
    # Ganztägig: Beginn = erster Tag 0:00, Ende = letzter Tag 0:00 (deutsche Zeit)
    starts_at = models.DateTimeField("Beginn")
    ends_at = models.DateTimeField("Ende")
    visibility = models.CharField(
        "Sichtbarkeit", max_length=10, choices=Visibility.choices, default=Visibility.MEMBERS
    )
    repeat = models.CharField("Wiederholung", max_length=10, choices=Repeat.choices, default="none")
    repeat_interval = models.PositiveSmallIntegerField(
        "alle … (Abstand)", default=1, validators=[MinValueValidator(1), MaxValueValidator(52)]
    )
    repeat_until = models.DateField("wiederholen bis", null=True, blank=True)
    # Weitergabe nach oben/unten; leer = wie bei der Einheit voreingestellt
    share_up = models.BooleanField("nach oben freigeben", null=True, blank=True)
    share_down = models.BooleanField("nach unten freigeben", null=True, blank=True)
    is_cancelled = models.BooleanField("abgesagt", default=False)
    cancel_note = models.CharField("Hinweis zur Absage", max_length=300, blank=True)
    # Verbund: Kennung des Termins auf seiner Heimat-Instanz (nur bei übermittelten
    # Terminen einer fernen Einheit; die ändert hier niemand)
    remote_uid = models.CharField(max_length=80, blank=True, db_index=True, editable=False)
    # Zeit oder Ort nach dem Anlegen geändert: im Kalender markiert
    changed_at = models.DateTimeField("Zeit oder Ort geändert am", null=True, blank=True)
    # Zu- und Absagen (Meilenstein 13): nur einmalige Termine eines Vereins oder Zugs
    rsvp_enabled = models.BooleanField("Zu- und Absagen", default=False)
    rsvp_deadline = models.DateTimeField("Anmeldeschluss", null=True, blank=True)
    rsvp_capacity = models.PositiveIntegerField(
        "Höchstzahl Teilnehmer",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100000)],
    )
    rsvp_guests = models.BooleanField("Begleitpersonen erlaubt", default=False)
    # Erinnerung per E-Mail: so viele Tage vor Beginn
    remind_days = models.PositiveSmallIntegerField(
        "Erinnerung Tage vorher",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
    )
    reminded_at = models.DateTimeField("Erinnerung verschickt am", null=True, blank=True)
    # Veranstaltung (Finanzen), zu der der Termin gehört; nur aus den Finanzen gesetzt
    project = models.ForeignKey(
        "finance.Project",
        verbose_name="Veranstaltung",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Termin"
        verbose_name_plural = "Termine"
        ordering = ["starts_at", "pk"]
        indexes = [
            models.Index(fields=["organization", "department", "starts_at"]),
            models.Index(fields=["organization", "visibility"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_series(self) -> bool:
        return self.repeat != self.Repeat.NONE

    def clean(self) -> None:
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            errors["ends_at"] = "Das Ende liegt vor dem Beginn."
        if (
            self.is_series
            and self.repeat_until
            and self.starts_at
            and self.repeat_until < timezone.localdate(self.starts_at)
        ):
            errors["repeat_until"] = "Das Ende der Serie liegt vor dem ersten Termin."
        if self.category_id and self.organization_id:
            if self.category.organization_id != self.organization_id:
                errors["category"] = "Unbekannte Kategorie."
        if (
            self.department_id
            and self.organization_id
            and self.department.organization_id != self.organization_id
        ):
            errors["department"] = fill("Unbekannt{adj} {sg}.", self.organization)
        if self.rsvp_enabled:
            if self.is_series:
                errors["rsvp_enabled"] = "Zu- und Absagen gibt es nur bei einmaligen Terminen."
            elif self.visibility == self.Visibility.BOARD:
                errors["rsvp_enabled"] = (
                    "Bei Terminen „nur Vorstand“ gibt es keine Zu- und Absagen."
                )
            elif self.organization_id and self.organization.type != "club":
                errors["rsvp_enabled"] = (
                    "Zu- und Absagen gibt es nicht bei Terminen der übergeordneten Einheit."
                )
            if self.rsvp_deadline and self.ends_at and self.rsvp_deadline > self.ends_at:
                errors["rsvp_deadline"] = "Der Anmeldeschluss liegt nach dem Termin."
        if self.remind_days and self.is_series:
            errors["remind_days"] = "Erinnerungen gibt es nur bei einmaligen Terminen."
        if errors:
            raise ValidationError(errors)


class EventException(models.Model):
    """Abweichung eines einzelnen Termins einer Serie: verschoben oder abgesagt."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="exceptions")
    # Beginn laut Serienregel – daran wird der einzelne Termin erkannt
    original_start = models.DateTimeField("ursprünglicher Beginn")
    is_cancelled = models.BooleanField("abgesagt", default=False)
    starts_at = models.DateTimeField("neuer Beginn", null=True, blank=True)
    ends_at = models.DateTimeField("neues Ende", null=True, blank=True)
    note = models.CharField("Hinweis", max_length=300, blank=True)

    class Meta:
        verbose_name = "Abweichung eines Serientermins"
        verbose_name_plural = "Abweichungen von Serienterminen"
        ordering = ["original_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "original_start"], name="serienabweichung_eindeutig"
            )
        ]

    def __str__(self) -> str:
        return f"{self.event} am {self.original_start:%d.%m.%Y}"

    def save(self, *args, **kwargs):
        self.organization_id = self.event.organization_id
        super().save(*args, **kwargs)


def attachment_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"events/{instance.organization_id}/{instance.event_id}/{stamp}-{filename}"


class EventAttachment(models.Model):
    """Anhang eines Termins, z. B. Einladung als PDF."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField("Datei", storage=private_storage, upload_to=attachment_path)
    name = models.CharField("Dateiname", max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField("Größe", default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anhang eines Termins"
        verbose_name_plural = "Anhänge von Terminen"
        ordering = ["uploaded_at", "pk"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.organization_id = self.event.organization_id
        super().save(*args, **kwargs)


class CalendarPublication(models.Model):
    """Öffentlicher Link auf die nach außen öffentlichen Termine (iCal und JSON)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    is_public = models.BooleanField("öffentlicher Link eingeschaltet", default=False)
    public_key = models.CharField(max_length=40, unique=True)

    class Meta:
        verbose_name = "Öffentlicher Kalender"
        verbose_name_plural = "Öffentliche Kalender"
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(department__isnull=True),
                name="kalender_veroeffentlichung_org",
            ),
            models.UniqueConstraint(
                fields=["department"],
                condition=models.Q(department__isnull=False),
                name="kalender_veroeffentlichung_abteilung",
            ),
        ]

    def __str__(self) -> str:
        return f"Kalender öffentlich: {self.is_public}"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(24)


class EventResponse(models.Model):
    """Zu- oder Absage eines Mitglieds zu einem Termin."""

    class Status(models.TextChoices):
        YES = "yes", "Zusage"
        NO = "no", "Absage"

    class Source(models.TextChoices):
        MEMBER = "member", "Mitglied"
        BOARD = "board", "Vorstand"

    # Verein des Termins (Mandantentrennung)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="responses")
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="event_responses"
    )
    status = models.CharField("Rückmeldung", max_length=5, choices=Status.choices)
    guests = models.PositiveSmallIntegerField(
        "Begleitpersonen", default=0, validators=[MaxValueValidator(MAX_GUESTS)]
    )
    note = models.CharField("Bemerkung", max_length=200, blank=True)
    source = models.CharField("eingetragen von", max_length=10, choices=Source.choices)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rückmeldung zu einem Termin"
        verbose_name_plural = "Rückmeldungen zu Terminen"
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "membership"], name="rueckmeldung_einmal_je_mitglied"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_status_display()} zu {self.event}"

    def save(self, *args, **kwargs):
        self.organization_id = self.event.organization_id
        super().save(*args, **kwargs)

    @property
    def persons(self) -> int:
        return 1 + self.guests if self.status == self.Status.YES else 0


class PersonalCalendar(models.Model):
    """Persönliches Kalender-Abo eines Mitglieds (iCal-Link ohne Anmeldung)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    access = models.OneToOneField(
        "portal.PortalAccess", on_delete=models.CASCADE, related_name="calendar_feed"
    )
    key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Persönliches Kalender-Abo"
        verbose_name_plural = "Persönliche Kalender-Abos"

    def __str__(self) -> str:
        return "Kalender-Abo"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(24)
