"""Rundschreiben: Mails und Serienbriefe an ausgewählte Mitglieder.

Ein Rundschreiben gehört der Organisation, die es verschickt (Verein oder
Dachverband). Rundschreiben einer Abteilung gehören dem Verein und tragen die
Abteilung. Die Empfänger werden beim Versand festgehalten (``CircularRecipient``):
Wer eine E-Mail-Adresse hat, bekommt eine Mail, alle anderen einen Brief
(Serienbrief-PDF zum Drucken).

Zwei Arten:

- ``info``   Information: Mitglieder können sich davon abmelden.
- ``notice`` Vereinsmitteilung (z. B. Einladung zur Versammlung): geht immer raus.
- ``short``  Kurzmitteilung (bis 500 Zeichen, ohne Anhang, nie als Brief), gedacht
  für die App („Antreten heute 18 Uhr am Zelt“).

Wer die HUBIplan-App mit Push hat, bekommt das Rundschreiben per App
(``via_app``), sonst per Mail (mit ``also_mail`` zusätzlich per Mail); ohne Mail
einen Brief bzw. bei Kurzmitteilungen nur im Mitgliederbereich.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5
MAX_BODY = 20000
MAX_SHORT_BODY = 500
# Kurzmitteilungen je Einheit (Verein bzw. Abteilung) und Tag
MAX_SHORT_PER_DAY = 10


class Circular(models.Model):
    class Kind(models.TextChoices):
        INFO = "info", "Information"
        NOTICE = "notice", "Vereinsmitteilung"
        SHORT = "short", "Kurzmitteilung"

    class Audience(models.TextChoices):
        MEMBERS = "members", "Mitglieder"
        BOARDS = "boards", "Vorstände der Vereine"
        DEPARTMENTS = "departments", "Rolleninhaber der Abteilungen"
        # Inhaber von Rollen des Vereins selbst (Vorstand, Kassierer, Schriftführer …)
        ROLES = "roles", "Rolleninhaber des Vereins"

    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        SENDING = "sending", "wird versendet"
        # Fachfrage 14 (Audit 31.10.): „abgearbeitet“ – ob jede Mail ankam, zeigen die Zahlen
        SENT = "sent", "abgearbeitet"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Leer: Rundschreiben der Organisation, sonst einer Abteilung (des Vereins)
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="Abteilung",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField("Art", max_length=10, choices=Kind.choices, default=Kind.INFO)
    audience = models.CharField(
        "Empfängerkreis", max_length=12, choices=Audience.choices, default=Audience.MEMBERS
    )
    subject = models.CharField("Betreff", max_length=200, blank=True)
    # Text mit einfacher Auszeichnung: **fett**, *kursiv*, Listen mit „- “, [Text](https://…)
    body = models.TextField("Text", blank=True, max_length=MAX_BODY)
    reply_to = models.EmailField("Antwort an", blank=True)
    # Mitglieder mit der App (und Push) bekommen es per App statt per Mail
    via_app = models.BooleanField("per App, wo möglich", default=True)
    # Mit ``via_app``: App-Nutzer bekommen zusätzlich die Mail
    also_mail = models.BooleanField("zusätzlich per E-Mail", default=False)
    # Auswahl der Empfänger (siehe circulars.recipients)
    filters = models.JSONField("Empfängerauswahl", default=dict, blank=True)
    # An einen Verteiler: Empfängerkreis und Auswahl kommen aus dessen Muster
    mailing_list = models.ForeignKey(
        "MailingList",
        verbose_name="Verteiler",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField("versendet am", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rundschreiben"
        verbose_name_plural = "Rundschreiben"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["organization", "department", "status"])]

    def __str__(self) -> str:
        return self.subject or "Rundschreiben ohne Betreff"

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT


def attachment_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"circulars/{instance.organization_id}/{instance.circular_id}/{stamp}-{filename}"


class CircularAttachment(models.Model):
    """PDF-Anhang eines Rundschreibens."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    circular = models.ForeignKey(Circular, on_delete=models.CASCADE, related_name="attachments")
    file = PrivateFileField("Datei", storage=private_storage, upload_to=attachment_path)
    name = models.CharField("Dateiname", max_length=200)
    size = models.PositiveIntegerField("Größe", default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anhang eines Rundschreibens"
        verbose_name_plural = "Anhänge von Rundschreiben"
        ordering = ["uploaded_at", "pk"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.organization_id = self.circular.organization_id
        super().save(*args, **kwargs)


class CircularRecipient(models.Model):
    """Empfänger eines versendeten Rundschreibens (Versandprotokoll)."""

    class Channel(models.TextChoices):
        MAIL = "mail", "E-Mail"
        LETTER = "letter", "Brief"
        APP = "app", "App"
        # Kurzmitteilung an Mitglieder ohne App und Mail
        PORTAL = "portal", "nur Mitgliederbereich"

    class Status(models.TextChoices):
        PENDING = "pending", "wartet"
        # Beansprucht, Ergebnis steht noch aus. Bleibt es länger so (Absturz mitten
        # im Versand), zeigt HUBIplan „Versand unklar“ (Audit 29.10. B-V04)
        SENDING = "sending", "wird versendet"
        SENT = "sent", "versendet"
        FAILED = "failed", "fehlgeschlagen"
        LETTER = "letter", "Brief zum Drucken"
        PORTAL = "portal", "im Mitgliederbereich"

    # Absender (wie das Rundschreiben)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    circular = models.ForeignKey(Circular, on_delete=models.CASCADE, related_name="recipients")
    # Verein des Empfängers: Mitglieder sehen ihre Rundschreiben im Mitgliederbereich
    club = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="circulars",
    )
    # Vorstand eines Vereins (Rundschreiben des Dachverbands an die Vorstände)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    first_name = models.CharField("Vorname", max_length=100, blank=True)
    last_name = models.CharField("Name", max_length=100, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    address = models.TextField("Anschrift", blank=True)
    # Werte der Platzhalter beim Versand
    values = models.JSONField(default=dict, blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Empfänger eines Rundschreibens"
        verbose_name_plural = "Empfänger von Rundschreiben"
        ordering = ["last_name", "first_name", "pk"]
        indexes = [models.Index(fields=["club", "membership"])]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs):
        self.organization_id = self.circular.organization_id
        super().save(*args, **kwargs)


class CircularTemplate(models.Model):
    """Vorlage: Betreff, Text und Art zum Wiederverwenden."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="Abteilung",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    name = models.CharField("Name", max_length=100)
    kind = models.CharField(
        "Art", max_length=10, choices=Circular.Kind.choices, default=Circular.Kind.INFO
    )
    subject = models.CharField("Betreff", max_length=200, blank=True)
    body = models.TextField("Text", blank=True, max_length=MAX_BODY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vorlage für Rundschreiben"
        verbose_name_plural = "Vorlagen für Rundschreiben"
        ordering = ["name", "pk"]

    def __str__(self) -> str:
        return self.name


# --- Mailverteiler: Rundschreiben aus dem eigenen Mailprogramm ---

LOCAL_PART_MAX = 64


class MailingList(models.Model):
    """Verteiler-Adresse: Mails an ``<adresse>@<Verteiler-Domain>`` werden zum Rundschreiben.

    Empfänger, Art und Empfängerkreis stehen in einem Muster-Rundschreiben
    (``pattern``, bleibt immer Entwurf). So gelten dieselben Filter und dieselbe
    Vorschau wie beim Rundschreiben in der Oberfläche.
    """

    class Mode(models.TextChoices):
        CONFIRM = "confirm", "Absender bestätigt per Link"
        DRAFT = "draft", "als Entwurf in HUBIplan ablegen"
        DIRECT = "direct", "direkt versenden (ohne Bestätigung)"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="Abteilung",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    name = models.CharField("Name", max_length=100)
    # Teil vor dem @, auf der ganzen Instanz eindeutig
    local_part = models.CharField("Adresse", max_length=LOCAL_PART_MAX, unique=True)
    # Weitere Adressen desselben Verteilers (z. B. „schriftfuehrer“ neben „schriftfuehrung“)
    aliases = models.JSONField("weitere Adressen", default=list, blank=True)
    mode = models.CharField("Versand", max_length=10, choices=Mode.choices, default=Mode.CONFIRM)
    is_active = models.BooleanField("aktiv", default=True)
    # Leer: alle mit dem Recht „Rundschreiben versenden“ für die Einheit; sonst nur diese
    # (und auch sie nur, solange sie das Recht haben)
    senders = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name="Absender", blank=True, related_name="+"
    )
    # Jeder darf schreiben, auch ohne Konto (Ralf 2026-10-31: ohne Freigabe direkt an alle)
    open_senders = models.BooleanField("jeder darf schreiben", default=False)
    pattern = models.OneToOneField(Circular, on_delete=models.CASCADE, related_name="list_pattern")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Verteiler"
        verbose_name_plural = "Verteiler"
        ordering = ["name", "pk"]

    def __str__(self) -> str:
        return self.name


class InboundMail(models.Model):
    """Eingegangene Mail an eine Verteiler-Adresse (Protokoll)."""

    class Status(models.TextChoices):
        REJECTED = "rejected", "abgewiesen"
        WAITING = "waiting", "wartet auf Bestätigung"
        DRAFT = "draft", "als Entwurf abgelegt"
        SENT = "sent", "versendet"
        FAILED = "failed", "Fehler"

    # Leer, solange keinem Verteiler zugeordnet (nur im Betriebsprotokoll)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    mailing_list = models.ForeignKey(
        MailingList, on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound"
    )
    message_id = models.CharField(max_length=300, blank=True, db_index=True)
    sender = models.CharField("Absender", max_length=300, blank=True)
    recipient = models.CharField("an", max_length=300, blank=True)
    subject = models.CharField("Betreff", max_length=300, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    circular = models.ForeignKey(
        Circular, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices)
    reason = models.CharField("Grund", max_length=300, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Eingang eines Verteilers"
        verbose_name_plural = "Eingänge der Verteiler"
        ordering = ["-received_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.subject} ({self.sender})"
