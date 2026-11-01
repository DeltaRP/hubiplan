"""Meldungen: Personen, Mannschaften und Angaben an einen Veranstalter melden.

Eine Ausschreibung (``Call``) sagt, was bis wann an wen gemeldet wird. Ihr Formular
besteht aus Bausteinen (``CallBlock``): Mannschaften, Personenliste, Zahl, Auswahl,
Text. Die Meldung (``Entry``) der Einheit füllt die Bausteine; beim Abgeben wird der
Stand als Fassung (``EntryVersion``) festgehalten und über einen Meldeweg (Brief,
E-Mail, Tabelle, sonstiger Weg) hinausgegeben. Konzept: konzepte/meldungen.md,
Doku docs/meldungen.md.

Schritt 1: Die meldende Einheit erfasst die Ausschreibung selbst (Veranstalter außerhalb
von HUBIplan). Mannschaften und Personen behalten ihre Kennung über alle Fassungen; ein
Ersatz tauscht nur die Person. Darauf verweisen die Starter eines fremden Wettbewerbs.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from core.encfields import EncryptedJSONField


class Call(models.Model):
    """Ausschreibung: was, bis wann, an wen und wie gemeldet wird."""

    class FeePer(models.TextChoices):
        TEAM = "mannschaft", gettext_lazy("je Mannschaft")
        PERSON = "person", gettext_lazy("je Person")
        FLAT = "pauschal", "pauschal"

    class Changes(models.TextChoices):
        NONE = "keine", gettext_lazy("nach Meldeschluss keine Änderungen")
        SUBSTITUTE = "ersatz", gettext_lazy("nach Meldeschluss nur Ersatz von Personen")
        FREE = "frei", gettext_lazy("Änderungen bis zum Anlass")

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    title = models.CharField("Titel", max_length=200)
    organizer = models.CharField("Veranstalter", max_length=200)
    # Anschrift für den Brief, eine Zeile je Zeile (ohne den Namen des Veranstalters)
    organizer_address = models.TextField("Anschrift", max_length=500, blank=True)
    organizer_email = models.EmailField("E-Mail des Veranstalters", blank=True)
    salutation = models.CharField(
        "Anrede", max_length=200, default="Sehr geehrte Damen und Herren,", blank=True
    )
    description = models.TextField("Beschreibung", max_length=5000, blank=True)
    date = models.DateField("Datum des Anlasses", null=True, blank=True)
    location = models.CharField("Ort", max_length=200, blank=True)
    deadline = models.DateField("Meldeschluss", null=True, blank=True)
    # Stichtag für Alter und Mitgliedschaft (leer: Datum des Anlasses, sonst heute)
    reference_date = models.DateField("Stichtag", null=True, blank=True)
    # Angaben je Person außer dem Namen, z. B. ["birth_date", "member_number"]
    person_fields = models.JSONField("Angaben je Person", default=list, blank=True)
    # {"active": bool, "min_age": int, "max_age": int, "member_types": [id],
    #  "units": [id], "one_team": bool, "guests": bool}
    conditions = models.JSONField("Bedingungen", default=dict, blank=True)
    fee_amount = models.DecimalField(
        "Meldegebühr", max_digits=9, decimal_places=2, null=True, blank=True
    )
    fee_per = models.CharField(
        "Gebühr", max_length=12, choices=FeePer.choices, default=FeePer.TEAM, blank=True
    )
    changes_after_deadline = models.CharField(
        "Änderungen nach Meldeschluss",
        max_length=10,
        choices=Changes.choices,
        default=Changes.SUBSTITUTE,
    )
    # Beim Abgeben einen fremden Wettbewerb mit den Mannschaften anlegen (Modul Wettbewerbe)
    create_competition = models.BooleanField("fremden Wettbewerb anlegen", default=False)
    event = models.ForeignKey(
        "events.Event",
        verbose_name="Termin",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Schritt 3: Ausschreibung an die eigenen Untereinheiten (Veranstalter in HUBIplan)
    internal = models.BooleanField("an eigene Untereinheiten", default=False)
    # Angeschriebene Untereinheiten (Kennungen); leer: alle direkten Untereinheiten
    units = models.JSONField("Untereinheiten", default=list, blank=True)
    # Bedingungen sperren das Abgeben, statt nur zu warnen
    strict = models.BooleanField("Bedingungen sperren", default=False)
    # Eigener Wettbewerb, in den bestätigte Meldungen als Starter laufen
    competition = models.ForeignKey(
        "competitions.Competition",
        verbose_name="Wettbewerb",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    copied_from = models.ForeignKey(
        "self",
        verbose_name="kopiert aus",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ausschreibung"
        verbose_name_plural = "Ausschreibungen"
        ordering = ["-date", "-pk"]

    def __str__(self) -> str:
        return self.title


class CallBlock(models.Model):
    """Baustein des Formulars einer Ausschreibung."""

    class Kind(models.TextChoices):
        TEAMS = "mannschaften", gettext_lazy("Mannschaften")
        PERSONS = "personen", gettext_lazy("Personenliste")
        NUMBER = "zahl", gettext_lazy("Zahl")
        CHOICE = "auswahl", gettext_lazy("Auswahl")
        TEXT = "text", gettext_lazy("Text")

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="blocks")
    kind = models.CharField("Art", max_length=12, choices=Kind.choices)
    label = models.CharField("Bezeichnung", max_length=200)
    help_text = models.CharField("Hinweis", max_length=300, blank=True)
    required = models.BooleanField("Pflicht", default=False)
    # Mannschaften: min_teams, max_teams, min_size, max_size, substitutes, positions
    # Personenliste: min, max, positions · Zahl: min, max · Auswahl: options, multiple
    # Text: multiline
    settings = models.JSONField("Einstellungen", default=dict, blank=True)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)

    class Meta:
        verbose_name = "Baustein der Ausschreibung"
        verbose_name_plural = "Bausteine der Ausschreibung"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.label


class Entry(models.Model):
    """Meldung einer Einheit zu einer Ausschreibung."""

    class Status(models.TextChoices):
        DRAFT = "entwurf", gettext_lazy("Entwurf")
        SUBMITTED = "abgegeben", "abgegeben"
        CONFIRMED = "bestaetigt", gettext_lazy("bestätigt")
        RETURNED = "rueckfrage", gettext_lazy("Rückfrage")
        WITHDRAWN = "zurueckgezogen", gettext_lazy("zurückgezogen")

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="entries")
    # Meldende Untereinheit bei Ausschreibungen von oben (Daten liegen beim Veranstalter)
    department = models.ForeignKey(
        "organizations.Organization",
        verbose_name="Untereinheit",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    question = models.CharField("Rückfrage des Veranstalters", max_length=500, blank=True)
    # Starter und Mannschaften, die diese Meldung im Wettbewerb angelegt hat
    synced = models.JSONField("übertragen", default=dict, blank=True, editable=False)
    status = models.CharField(
        "Zustand", max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    # Seit der letzten Fassung geändert (Änderungsmeldung fällig)
    changed = models.BooleanField("geändert seit der letzten Fassung", default=False)
    note = models.TextField("Notiz", max_length=2000, blank=True)
    confirmed_note = models.CharField("Bestätigung", max_length=300, blank=True)
    competition = models.ForeignKey(
        "competitions.Competition",
        verbose_name="Wettbewerb",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Meldung"
        verbose_name_plural = "Meldungen"
        constraints = [
            models.UniqueConstraint(
                fields=["call", "organization"],
                condition=models.Q(department__isnull=True),
                name="meldung_je_einheit",
            ),
            models.UniqueConstraint(
                fields=["call", "department"],
                condition=models.Q(department__isnull=False),
                name="meldung_je_untereinheit",
            ),
        ]

    def __str__(self) -> str:
        return f"Meldung {self.call}"


class EntryTeam(models.Model):
    """Gemeldete Mannschaft. Die Kennung bleibt über alle Fassungen gleich."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="teams")
    block = models.ForeignKey(CallBlock, on_delete=models.CASCADE, related_name="+")
    name = models.CharField("Mannschaft", max_length=100)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    # Gegenstück im fremden Wettbewerb
    team = models.ForeignKey(
        "competitions.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "gemeldete Mannschaft"
        verbose_name_plural = "gemeldete Mannschaften"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.name


class EntryPerson(models.Model):
    """Gemeldete Person (Mitglied oder Gast), einzeln oder in einer Mannschaft.

    Der Platz behält seine Kennung; bei einem Ersatz wechselt nur die Person."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="persons")
    block = models.ForeignKey(CallBlock, on_delete=models.CASCADE, related_name="+")
    team = models.ForeignKey(
        EntryTeam, on_delete=models.CASCADE, null=True, blank=True, related_name="persons"
    )
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Mitglied",
    )
    # Name als Text: für Gäste die Eingabe, für Mitglieder eine Kopie
    name = models.CharField("Name", max_length=200)
    club = models.CharField("Verein", max_length=200, blank=True)
    position = models.CharField("Aufgabe", max_length=100, blank=True)
    substitute = models.BooleanField("Ersatz", default=False)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    starter = models.ForeignKey(
        "competitions.Starter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "gemeldete Person"
        verbose_name_plural = "gemeldete Personen"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_guest(self) -> bool:
        return self.membership_id is None


class EntryAnswer(models.Model):
    """Antwort auf einen Baustein Zahl, Auswahl oder Text."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="answers")
    block = models.ForeignKey(CallBlock, on_delete=models.CASCADE, related_name="+")
    value = models.JSONField("Wert", null=True, blank=True)

    class Meta:
        verbose_name = "Angabe der Meldung"
        verbose_name_plural = "Angaben der Meldung"
        constraints = [
            models.UniqueConstraint(fields=["entry", "block"], name="meldung_angabe_einmal")
        ]

    def __str__(self) -> str:
        return f"{self.block_id}: {self.value}"


class EntryVersion(models.Model):
    """Festgehaltene Fassung einer abgegebenen Meldung (Meldung, Änderung, Rückzug)."""

    class Kind(models.TextChoices):
        ENTRY = "meldung", gettext_lazy("Meldung")
        CHANGE = "aenderung", gettext_lazy("Änderungsmeldung")
        WITHDRAWAL = "rueckzug", gettext_lazy("Rückzug")

    class Channel(models.TextChoices):
        LETTER = "brief", gettext_lazy("Brief")
        EMAIL = "email", gettext_lazy("E-Mail")
        TABLE = "tabelle", gettext_lazy("Tabelle")
        OTHER = "sonstiges", gettext_lazy("sonstiger Weg")
        HUBIPLAN = "hubiplan", gettext_lazy("in HUBIplan")

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveSmallIntegerField("Fassung")
    kind = models.CharField("Art", max_length=10, choices=Kind.choices, default=Kind.ENTRY)
    channel = models.CharField("Meldeweg", max_length=10, choices=Channel.choices)
    # E-Mail-Adresse oder Vermerk (z. B. „persönlich übergeben“)
    sent_to = models.CharField("an", max_length=300, blank=True)
    # Änderungen gegenüber der vorigen Fassung, als Text („Für A schießt nun B“)
    changes = models.JSONField("Änderungen", default=list, blank=True)
    reason = models.CharField("Grund", max_length=300, blank=True)
    # Stand der Meldung samt Angaben je Person, verschlüsselt (Brief und Tabelle daraus)
    data = EncryptedJSONField("Stand", default=dict, blank=True)
    # Absender für den Brief (Name, Funktion)
    signed_by = models.CharField("Unterzeichner", max_length=200, blank=True)
    signed_function = models.CharField("Funktion", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Nach der Aufbewahrungsfrist gekürzt (nur noch Name und Mannschaft)
    shortened_at = models.DateTimeField("gekürzt am", null=True, blank=True)

    class Meta:
        verbose_name = "Fassung der Meldung"
        verbose_name_plural = "Fassungen der Meldung"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["entry", "number"], name="meldung_fassung_einmal")
        ]

    def __str__(self) -> str:
        return f"Fassung {self.number}"
