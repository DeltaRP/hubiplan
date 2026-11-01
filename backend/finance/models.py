"""Kasse: Konten, Kategorien, Buchungen und Belege (Einnahmen-/Ausgabenrechnung).

Beträge sind immer positiv. Ob Geld hinein- oder hinausgeht, sagt die Art der
Buchung. Umbuchungen zwischen eigenen Konten zählen weder als Einnahme noch als
Ausgabe.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage


class TaxArea(models.TextChoices):
    IDEAL = "ideal", "ideeller Bereich"
    ASSETS = "assets", "Vermögensverwaltung"
    PURPOSE = "purpose", "Zweckbetrieb"
    BUSINESS = "business", "wirtschaftlicher Geschäftsbetrieb"


class Account(models.Model):
    class Kind(models.TextChoices):
        BANK = "bank", "Bankkonto"
        CASH = "cash", "Barkasse"
        SAVINGS = "savings", "Sparkonto"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField("Name", max_length=100)
    kind = models.CharField("Art", max_length=10, choices=Kind.choices, default=Kind.BANK)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    bank_name = models.CharField("Bank", max_length=100, blank=True)
    opening_balance = models.DecimalField(
        "Anfangsbestand", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    opening_date = models.DateField("Stichtag Anfangsbestand")
    is_active = models.BooleanField("aktiv", default=True)
    position = models.PositiveIntegerField("Reihenfolge", default=0)
    # DATEV-Export: Finanzkonto (z. B. 1200 Bank, 1000 Kasse)
    datev_account = models.CharField("DATEV-Konto", max_length=9, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Konto"
        verbose_name_plural = "Konten"
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="konto_name_eindeutig")
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        self.iban = self.iban.replace(" ", "").upper()
        self.bic = self.bic.replace(" ", "").upper()
        if self.iban and not iban_valid(self.iban):
            raise ValidationError({"iban": "Die IBAN ist ungültig."})


def iban_valid(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if len(iban) < 15 or len(iban) > 34 or not iban[:2].isalpha() or not iban.isalnum():
        return False
    moved = iban[4:] + iban[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


class Category(models.Model):
    class Kind(models.TextChoices):
        INCOME = "income", "Einnahmen"
        EXPENSE = "expense", "Ausgaben"
        BOTH = "both", "Einnahmen und Ausgaben"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField("Name", max_length=100)
    kind = models.CharField("Art", max_length=10, choices=Kind.choices, default=Kind.BOTH)
    tax_area = models.CharField(
        "steuerlicher Bereich", max_length=10, choices=TaxArea.choices, blank=True
    )
    is_active = models.BooleanField("aktiv", default=True)
    # Einnahmen dieser Kategorie lassen sich als Zuwendung (Spende) übernehmen
    donations = models.BooleanField("Spenden (Zuwendungsbestätigung möglich)", default=False)
    # DATEV-Export: Sachkonto (Gegenkonto der Buchungen dieser Kategorie)
    datev_account = models.CharField("DATEV-Konto", max_length=9, blank=True)

    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="kategorie_name_eindeutig"
            )
        ]

    def __str__(self) -> str:
        return self.name

    def allows(self, booking_kind: str) -> bool:
        return self.kind == self.Kind.BOTH or self.kind == booking_kind


class Booking(models.Model):
    class Kind(models.TextChoices):
        INCOME = "income", "Einnahme"
        EXPENSE = "expense", "Ausgabe"
        TRANSFER = "transfer", "Umbuchung"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Geschäftsjahr (Kalenderjahr seines Beginns), siehe Organization.fiscal_year_of
    year = models.PositiveSmallIntegerField("Geschäftsjahr")
    number = models.PositiveIntegerField("Buchungsnummer")
    date = models.DateField("Datum")
    kind = models.CharField("Art", max_length=10, choices=Kind.choices)
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="bookings", verbose_name="Konto"
    )
    to_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
        null=True,
        blank=True,
        verbose_name="Zielkonto",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="bookings",
        null=True,
        blank=True,
        verbose_name="Kategorie",
    )
    text = models.CharField("Buchungstext", max_length=200)
    reference = models.CharField("Belegnummer/Referenz", max_length=100, blank=True)
    # Wer das Geld bekommt (Ausgabe) oder zahlt (Einnahme): Geschäft, Dienstleister,
    # Person. Freitext; frühere Namen werden beim Erfassen vorgeschlagen.
    counterparty = models.CharField("Empfänger/Zahler", max_length=200, blank=True)
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Mitglied",
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Abteilung",
    )
    # Veranstaltung, zu der die Einnahme oder Ausgabe gehört (nur für die Auswertung)
    project = models.ForeignKey(
        "Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
        verbose_name="Veranstaltung",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Beim Jahresabschluss festgehalten (Gesamtaudit 31.10.b, Frage 9): spätere Änderungen
    # an der Kategorie verschieben abgeschlossene Jahre nicht mehr.
    frozen = models.BooleanField(default=False)
    frozen_category_name = models.CharField(max_length=100, blank=True, default="")
    frozen_tax_area = models.CharField(max_length=10, blank=True, default="")
    # Storno (GoBD): Gegenbuchung verweist auf die stornierte Buchung; diese bleibt unverändert
    cancels = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancellation",
        verbose_name="storniert Buchung",
    )
    cancel_reason = models.CharField("Grund des Stornos", max_length=300, blank=True)

    class Meta:
        verbose_name = "Buchung"
        verbose_name_plural = "Buchungen"
        ordering = ["-date", "-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year", "number"], name="buchungsnummer_eindeutig"
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="betrag_positiv"),
        ]
        indexes = [
            models.Index(fields=["organization", "date"]),
            models.Index(fields=["organization", "counterparty"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_number} {self.text}"

    @property
    def category_label(self) -> str | None:
        """Kategorie wie beim Abschluss (abgeschlossenes Jahr) bzw. wie heute."""
        if self.frozen:
            return self.frozen_category_name or None
        return self.category.name if self.category_id else None

    @property
    def tax_area_value(self) -> str:
        if self.frozen:
            return self.frozen_tax_area
        return self.category.tax_area if self.category_id else ""

    @property
    def display_number(self) -> str:
        return f"{self.organization.fiscal_label(self.year)}-{self.number:04d}"

    def clean(self):
        errors: dict[str, str] = {}
        self.counterparty = " ".join((self.counterparty or "").split())
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Der Betrag muss größer als 0 sein."
        if self.kind == self.Kind.TRANSFER:
            if not self.to_account_id:
                errors["to_account"] = "Bitte das Zielkonto wählen."
            elif self.to_account_id == self.account_id:
                errors["to_account"] = "Zielkonto und Konto müssen verschieden sein."
            self.category = None
            self.project = None
            self.counterparty = ""
        else:
            self.to_account = None
            if not self.category_id:
                errors["category"] = "Bitte eine Kategorie wählen."
            elif not self.category.allows(self.kind):
                errors["category"] = "Die Kategorie passt nicht zu dieser Art der Buchung."
        if self.date and self.account_id and self.date < self.account.opening_date:
            errors["date"] = (
                f"Das Datum liegt vor dem Stichtag des Anfangsbestands von "
                f"„{self.account.name}“ ({self.account.opening_date:%d.%m.%Y})."
            )
        if (
            self.date
            and self.to_account_id
            and self.to_account_id != self.account_id
            and self.date < self.to_account.opening_date
        ):
            errors["date"] = "Das Datum liegt vor dem Stichtag des Zielkontos."
        if (
            self.project_id
            and self.organization_id
            and self.project.organization_id != self.organization_id
        ):
            errors["project"] = "Unbekannte Veranstaltung."
        if errors:
            raise ValidationError(errors)

    def effect_on(self, account_id: int) -> Decimal:
        """Wie die Buchung den Bestand eines Kontos verändert."""
        if self.kind == self.Kind.INCOME:
            return self.amount if self.account_id == account_id else Decimal("0")
        if self.kind == self.Kind.EXPENSE:
            return -self.amount if self.account_id == account_id else Decimal("0")
        result = Decimal("0")
        if self.account_id == account_id:
            result -= self.amount
        if self.to_account_id == account_id:
            result += self.amount
        return result


def receipt_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"receipts/{instance.organization_id}/{stamp}-{filename}"


class Receipt(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="receipts", verbose_name="Buchung"
    )
    file = PrivateFileField("Datei", storage=private_storage, upload_to=receipt_path)
    name = models.CharField("Dateiname", max_length=200)
    content_type = models.CharField("Dateityp", max_length=100)
    size = models.PositiveIntegerField("Größe", default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Ausgeblendet statt gelöscht (Aufbewahrungspflicht): Datei bleibt, steht im Export
    hidden_at = models.DateTimeField("ausgeblendet am", null=True, blank=True)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    hidden_reason = models.CharField("Grund", max_length=300, blank=True)
    # E-Rechnung (XRechnung, ZUGFeRD): ausgelesene Angaben; maßgeblich bleibt die Datei
    einvoice = models.JSONField("E-Rechnung", default=dict, blank=True)

    class Meta:
        verbose_name = "Beleg"
        verbose_name_plural = "Belege"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.name


class YearClosing(models.Model):
    """Jahresabschluss: danach ist das Geschäftsjahr für Buchungen gesperrt."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    year = models.PositiveSmallIntegerField("Geschäftsjahr")
    closed_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Stand beim Abschluss (Bestände und Summen), zum Nachweis
    snapshot = models.JSONField(default=dict, blank=True)
    # Ende der Aufbewahrungsfrist (Finanzamt-Prüfung C6, finance/retention.py)
    documents_purged_at = models.DateTimeField("Belege gelöscht am", null=True, blank=True)
    records_purged_at = models.DateTimeField("Bücher anonymisiert am", null=True, blank=True)
    purged_by_name = models.CharField("bereinigt von", max_length=200, blank=True, db_default="")

    class Meta:
        verbose_name = "Jahresabschluss"
        verbose_name_plural = "Jahresabschlüsse"
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "year"], name="abschluss_eindeutig")
        ]

    def __str__(self) -> str:
        return f"Abschluss {self.year}"


class ReopenedClosing(models.Model):
    """Aufgehobener Jahresabschluss: alter Stand mit Grund, zum Nachweis (GoBD, B4)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    year = models.PositiveSmallIntegerField("Geschäftsjahr")
    closed_at = models.DateTimeField("abgeschlossen am")
    closed_by_name = models.CharField("abgeschlossen von", max_length=200, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    reopened_at = models.DateTimeField("aufgehoben am", auto_now_add=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reopened_by_name = models.CharField("aufgehoben von", max_length=200, blank=True)
    reason = models.CharField("Grund", max_length=500)

    class Meta:
        verbose_name = "aufgehobener Jahresabschluss"
        verbose_name_plural = "aufgehobene Jahresabschlüsse"
        ordering = ["-year", "-reopened_at"]
        indexes = [models.Index(fields=["organization", "year"])]

    def __str__(self) -> str:
        return f"Abschluss {self.year}, aufgehoben"


class ProjectSeries(models.Model):
    """Reihe wiederkehrender Veranstaltungen (z. B. das jährliche Schützenfest),
    um die Jahre miteinander zu vergleichen."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField("Name", max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Veranstaltungsreihe"
        verbose_name_plural = "Veranstaltungsreihen"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="reihe_name_eindeutig")
        ]

    def __str__(self) -> str:
        return self.name


class Project(models.Model):
    """Veranstaltung: bündelt Einnahmen und Ausgaben für eine eigene Auswertung.

    Die Buchungen bleiben normale Buchungen im Kassenbuch. Termine im Kalender
    können auf die Veranstaltung verweisen (``events.Event.project``), müssen es
    aber nicht.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "geplant"
        RUNNING = "running", "laufend"
        DONE = "done", "abgeschlossen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Leer: Veranstaltung der Organisation selbst, sonst einer Abteilung
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Abteilung",
    )
    series = models.ForeignKey(
        ProjectSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
        verbose_name="Reihe",
    )
    name = models.CharField("Name", max_length=200)
    starts_on = models.DateField("Beginn")
    ends_on = models.DateField("Ende", null=True, blank=True)
    description = models.TextField("Beschreibung", blank=True, max_length=5000)
    status = models.CharField(
        "Status", max_length=10, choices=Status.choices, default=Status.PLANNED
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Veranstaltung"
        verbose_name_plural = "Veranstaltungen"
        ordering = ["-starts_on", "name"]
        indexes = [models.Index(fields=["organization", "starts_on"])]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        errors: dict[str, str] = {}
        if self.ends_on and self.starts_on and self.ends_on < self.starts_on:
            errors["ends_on"] = "Das Ende liegt vor dem Beginn."
        if self.organization_id:
            if self.series_id and self.series.organization_id != self.organization_id:
                errors["series"] = "Unbekannte Reihe."
            if self.department_id and self.department.organization_id != self.organization_id:
                from organizations.terms import fill

                errors["department"] = fill("Unbekannt{adj} {sg}.", self.organization)
        if errors:
            raise ValidationError(errors)


class CashReceipt(models.Model):
    """Quittung mit zwei Unterschriften (Kassierer und Gegenseite), siehe
    konzepte/digitale-quittung.md.

    Entwurf → abgeschlossen (Buchung im Kassenbuch, Belegnummer = Buchungsnummer, PDF als
    Beleg an der Buchung) → ggf. storniert (Gegenbuchung, neues PDF). Abgeschlossene
    Quittungen werden nie geändert oder gelöscht.
    """

    class Direction(models.TextChoices):
        IN = "in", "Verein erhält Geld"
        OUT = "out", "Verein zahlt Geld aus"

    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        FINAL = "final", "abgeschlossen"
        CANCELLED = "cancelled", "storniert"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    direction = models.CharField("Richtung", max_length=3, choices=Direction.choices)
    status = models.CharField("Status", max_length=10, choices=Status.choices, default=Status.DRAFT)
    counterparty_name = models.CharField("Name der Gegenseite", max_length=200)
    counterparty_address = models.TextField("Anschrift", max_length=500, blank=True)
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Mitglied",
    )
    email = models.EmailField("E-Mail der Gegenseite", blank=True)
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    purpose = models.CharField("Zweck", max_length=200)
    # Umsatzsteuer nur bei Bedarf (Ralf 30.10.: Standard nein)
    vat_rate = models.DecimalField(
        "USt-Satz in %", max_digits=4, decimal_places=1, null=True, blank=True
    )
    account = models.ForeignKey(
        Account, on_delete=models.RESTRICT, related_name="+", verbose_name="Kasse"
    )
    category = models.ForeignKey(
        Category, on_delete=models.RESTRICT, related_name="+", verbose_name="Kategorie"
    )
    project = models.ForeignKey(
        "Project",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Veranstaltung",
    )
    # Barzahlung zu einer Rechnung (Schritt Q5): der Abschluss bucht die Zahlung
    invoice = models.ForeignKey(
        "billing.Invoice",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="cash_receipts",
        verbose_name="Rechnung",
    )
    # Unterschriften: nur die Form (Linienzüge), keine Zeit- oder Druckwerte
    treasurer_signature = models.JSONField("Unterschrift Kassierer", null=True, blank=True)
    treasurer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    treasurer_name = models.CharField(max_length=200, blank=True)
    treasurer_signed_at = models.DateTimeField(null=True, blank=True)
    counterparty_signature = models.JSONField("Unterschrift Gegenseite", null=True, blank=True)
    counterparty_signed_at = models.DateTimeField(null=True, blank=True)
    counterparty_confirmed = models.CharField("bestätigter Text", max_length=500, blank=True)
    # Zahler unterschreibt nicht (nur wenn der Verein Geld erhält), mit Begründung
    no_signature_reason = models.CharField(max_length=300, blank=True)
    source = models.CharField("erfasst über", max_length=60, blank=True)

    booking = models.OneToOneField(
        Booking,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="cash_receipt",
        verbose_name="Buchung",
    )
    payment = models.OneToOneField(
        "billing.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_receipt",
    )
    # Belegnummer beim Abschluss festgehalten (ändert sich auch beim Neunummerieren nicht)
    number = models.CharField("Belegnummer", max_length=30, blank=True)
    receipt_date = models.DateField("Datum", null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    document = models.ForeignKey(
        Receipt, on_delete=models.RESTRICT, null=True, blank=True, related_name="+"
    )
    pdf_sha256 = models.CharField(max_length=64, blank=True)

    cancel_booking = models.OneToOneField(
        Booking,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="cash_receipt_cancel",
    )
    cancel_reason = models.CharField("Grund des Stornos", max_length=300, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancel_document = models.ForeignKey(
        Receipt, on_delete=models.RESTRICT, null=True, blank=True, related_name="+"
    )
    cancel_sha256 = models.CharField(max_length=64, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Quittung"
        verbose_name_plural = "Quittungen"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="quittung_betrag_positiv"
            ),
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self) -> str:
        return f"Quittung {self.number or '(Entwurf)'}"

    @property
    def receives(self) -> bool:
        """Verein erhält das Geld (sonst zahlt er es aus)."""
        return self.direction == self.Direction.IN


# --- Zuwendungsbestätigungen (Spendenbescheinigungen) nach amtlichem Muster ---


class DonationSettings(models.Model):
    """Angaben zur Steuerbegünstigung, die auf jeder Zuwendungsbestätigung stehen."""

    class Notice(models.TextChoices):
        EXEMPTION = "exemption", "Freistellungsbescheid bzw. Anlage zum Körperschaftsteuerbescheid"
        STATUTE = "statute", "Feststellung der Satzungsmäßigkeit nach § 60a AO"

    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Steuerbegünstigt mit eigenem Bescheid: entscheidet, nicht der Registereintrag
    # (auch nicht eingetragene Vereine können gemeinnützig sein, § 1 Abs. 1 Nr. 5 KStG)
    enabled = models.BooleanField("steuerbegünstigt mit eigenem Bescheid", default=False)
    purposes = models.TextField(
        "begünstigte Zwecke",
        max_length=1000,
        blank=True,
        help_text="z. B. Förderung des traditionellen Brauchtums (§ 52 Abs. 2 Satz 1 Nr. 23 AO)",
    )
    notice = models.CharField(
        "Art des Bescheids", max_length=10, choices=Notice.choices, default=Notice.EXEMPTION
    )
    tax_office = models.CharField("Finanzamt", max_length=200, blank=True)
    tax_number = models.CharField("Steuernummer", max_length=50, blank=True)
    notice_date = models.DateField("Datum des Bescheids", null=True, blank=True)
    assessment_period = models.CharField(
        "letzter Veranlagungszeitraum", max_length=50, blank=True, help_text="z. B. 2022 bis 2024"
    )
    fees_allowed = models.BooleanField("Mitgliedsbeiträge bestätigen", default=False)
    place = models.CharField("Ort der Ausstellung", max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Einstellungen Zuwendungsbestätigungen"
        verbose_name_plural = "Einstellungen Zuwendungsbestätigungen"

    def __str__(self) -> str:
        return f"Zuwendungsbestätigungen {self.organization_id}"


def donation_statement_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"donations/{instance.organization_id}/{stamp}-{filename}"


class DonationStatement(models.Model):
    """Ausgestellte Zuwendungsbestätigung; das PDF ist das Doppel (§ 50 Abs. 7 EStDV)."""

    class Kind(models.TextChoices):
        SINGLE = "single", "Einzelbestätigung"
        COLLECTIVE = "collective", "Sammelbestätigung"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    year = models.PositiveSmallIntegerField("Jahr")
    seq = models.PositiveIntegerField("laufende Nummer")
    kind = models.CharField("Art", max_length=10, choices=Kind.choices)
    goods = models.BooleanField("Sachzuwendung", default=False)
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    donor_name = models.CharField("Zuwendender", max_length=200)
    donor_address = models.TextField("Anschrift", max_length=500, blank=True)
    total = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    period_from = models.DateField("von")
    period_to = models.DateField("bis")
    # Die bestätigten Zuwendungen, wie sie beim Ausstellen galten
    items = models.JSONField(default=list, blank=True)
    issued_on = models.DateField("ausgestellt am")
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    signer_name = models.CharField("unterschrieben von", max_length=200, blank=True)
    file = PrivateFileField(
        "Doppel", storage=private_storage, upload_to=donation_statement_path, blank=True
    )
    pdf_sha256 = models.CharField(max_length=64, blank=True)
    cancelled_at = models.DateTimeField("storniert am", null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.CharField("Grund des Stornos", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zuwendungsbestätigung"
        verbose_name_plural = "Zuwendungsbestätigungen"
        ordering = ["-year", "-seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year", "seq"], name="zuwendungsbestaetigung_nummer"
            )
        ]

    def __str__(self) -> str:
        return f"Zuwendungsbestätigung {self.number}"

    @property
    def number(self) -> str:
        return f"ZB-{self.year}-{self.seq:04d}"


class Donation(models.Model):
    """Eine Zuwendung (Geld, Mitgliedsbeitrag oder Sache), bestätigt oder noch offen."""

    class Kind(models.TextChoices):
        MONEY = "money", "Geldzuwendung"
        FEE = "fee", "Mitgliedsbeitrag"
        GOODS = "goods", "Sachzuwendung"

    class Origin(models.TextChoices):
        BUSINESS = "business", "aus dem Betriebsvermögen"
        PRIVATE = "private", "aus dem Privatvermögen"
        UNKNOWN = "unknown", "keine Angaben zur Herkunft"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    date = models.DateField("Tag der Zuwendung")
    kind = models.CharField("Art", max_length=10, choices=Kind.choices, default=Kind.MONEY)
    amount = models.DecimalField("Betrag bzw. Wert", max_digits=12, decimal_places=2)
    waiver = models.BooleanField("Verzicht auf Erstattung von Aufwendungen", default=False)
    membership = models.ForeignKey(
        "members.Membership",
        verbose_name="Mitglied",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    donor_name = models.CharField("Zuwendender", max_length=200)
    donor_address = models.TextField("Anschrift", max_length=500, blank=True)
    goods_description = models.TextField(
        "Bezeichnung der Sache (Alter, Zustand, Kaufpreis)", max_length=1000, blank=True
    )
    goods_origin = models.CharField(
        "Herkunft der Sache", max_length=10, choices=Origin.choices, blank=True
    )
    goods_documents = models.BooleanField("Unterlagen zur Wertermittlung liegen vor", default=False)
    booking = models.OneToOneField(
        Booking,
        verbose_name="Buchung",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donation",
    )
    note = models.CharField("Notiz", max_length=300, blank=True)
    statement = models.ForeignKey(
        DonationStatement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Zuwendung"
        verbose_name_plural = "Zuwendungen"
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["organization", "date"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.amount} € von {self.donor_name}"


# --- Kontoauszüge (CAMT.053) ---


def bank_statement_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"kontoauszuege/{instance.organization_id}/{stamp}-{filename}"


class BankStatement(models.Model):
    """Ein eingelesener Kontoauszug (eine Datei kann mehrere enthalten)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="statements")
    file_name = models.CharField("Datei", max_length=200)
    reference = models.CharField("Auszug", max_length=100, blank=True)
    date_from = models.DateField("von", null=True, blank=True)
    date_to = models.DateField("bis", null=True, blank=True)
    opening_balance = models.DecimalField(
        "Anfangssaldo", max_digits=12, decimal_places=2, null=True, blank=True
    )
    closing_balance = models.DecimalField(
        "Endsaldo", max_digits=12, decimal_places=2, null=True, blank=True
    )
    line_count = models.PositiveIntegerField("Umsätze", default=0)
    duplicate_count = models.PositiveIntegerField("schon eingelesen", default=0)
    # Die eingelesene Datei unverändert (GoBD: elektronische Kontoauszüge im Original)
    source = PrivateFileField(
        "Originaldatei", storage=private_storage, upload_to=bank_statement_path, blank=True
    )
    source_sha256 = models.CharField(max_length=64, blank=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kontoauszug"
        verbose_name_plural = "Kontoauszüge"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Kontoauszug {self.reference or self.pk} ({self.account_id})"


class BankLine(models.Model):
    """Ein Umsatz aus dem Kontoauszug; wird zugeordnet, gebucht oder übergangen."""

    class Status(models.TextChoices):
        OPEN = "open", "offen"
        DONE = "done", "erledigt"
        IGNORED = "ignored", "übergangen"

    class Suggestion(models.TextChoices):
        NONE = "", "kein Vorschlag"
        INVOICE = "invoice", "Zahlung zu Rechnung"
        DEBIT_RUN = "debit_run", "Lastschriftlauf"
        BOOKED = "booked", "schon im Kassenbuch"
        RETURN = "return", "Rücklastschrift"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    date = models.DateField("Buchungstag")
    value_date = models.DateField("Wertstellung", null=True, blank=True)
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    credit = models.BooleanField("Gutschrift")
    name = models.CharField("Gegenseite", max_length=200, blank=True)
    iban = models.CharField("IBAN der Gegenseite", max_length=34, blank=True)
    purpose = models.CharField("Verwendungszweck", max_length=500, blank=True)
    end_to_end = models.CharField("End-to-End-Referenz", max_length=35, blank=True)
    bank_ref = models.CharField("Bankreferenz", max_length=100, blank=True)
    return_code = models.CharField("Rückgabegrund", max_length=10, blank=True)
    batch_count = models.PositiveIntegerField("Einzelposten", default=1)
    # Einzelposten einer Sammelbuchung, so wie sie im Auszug stehen (Audit 31.10. FIN31-02)
    details = models.JSONField("Einzelposten der Sammelbuchung", default=list, blank=True)
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    suggestion = models.CharField(
        max_length=10, choices=Suggestion.choices, blank=True, default=Suggestion.NONE
    )
    # Vorschlag beruht auf einer Referenz (Rechnungsnummer, Name, Mandat) und darf mit
    # „Alle Vorschläge übernehmen“ gebucht werden; sonst nur einzeln nach Prüfung (FIN31-03)
    suggestion_sure = models.BooleanField("Vorschlag sicher", default=False)
    suggested_invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggested_run = models.ForeignKey(
        "billing.DebitRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggested_booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggested_membership = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name="bank_lines"
    )
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Kontoumsatz"
        verbose_name_plural = "Kontoumsätze"
        ordering = ["date", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "account", "fingerprint"], name="kontoumsatz_einmal"
            )
        ]

    def __str__(self) -> str:
        sign = "+" if self.credit else "-"
        return f"{self.date} {sign}{self.amount} {self.name}"


def cash_count_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"zaehlungen/{instance.organization_id}/{stamp}.pdf"


# Stückelung in Cent: Scheine und Münzen (Euro)
DENOMINATIONS = [50000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 2, 1]


class CashCount(models.Model):
    """Zählprotokoll einer Barkasse oder Kassenbericht eines Festes (Finanzamt-Prüfung B2).

    Wird einmal erstellt und danach nicht mehr geändert; die zugehörigen Buchungen
    (Kassendifferenz bzw. Tageseinnahmen) tragen das PDF als Beleg."""

    class Kind(models.TextChoices):
        COUNT = "count", "Zählprotokoll"
        EVENT = "event", "Kassenbericht"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    kind = models.CharField("Art", max_length=10, choices=Kind.choices)
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="cash_counts", verbose_name="Barkasse"
    )
    date = models.DateField("Datum")
    title = models.CharField("Bezeichnung", max_length=200, blank=True)
    project = models.ForeignKey(
        "Project", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # Anzahl je Stückelung, Schlüssel in Cent als Text
    denominations = models.JSONField("Stückelung", default=dict, blank=True)
    counted = models.DecimalField("gezählt", max_digits=12, decimal_places=2)
    # Zählprotokoll: Bestand laut Kassenbuch am Ende des Tages vor der Differenzbuchung
    expected = models.DecimalField("Soll laut Kassenbuch", max_digits=12, decimal_places=2)
    # Kassenbericht: Wechselgeld zu Beginn, bar bezahlte Ausgaben, Entnahmen während des Festes
    opening = models.DecimalField("Anfangsbestand", max_digits=12, decimal_places=2, default=0)
    expenses = models.DecimalField(
        "Ausgaben aus der Kasse", max_digits=12, decimal_places=2, default=0
    )
    withdrawals = models.DecimalField("Entnahmen", max_digits=12, decimal_places=2, default=0)
    # Kassenbericht: Aufteilung der Einnahmen [{category, name, amount}]
    lines = models.JSONField("Aufteilung", default=list, blank=True)
    note = models.CharField("Bemerkung/Grund", max_length=500, blank=True)
    counted_by = models.CharField("gezählt von", max_length=200)
    witness = models.CharField("zweite Person", max_length=200, blank=True)
    booking_ids = models.JSONField("Buchungen", default=list, blank=True)
    pdf = PrivateFileField("PDF", storage=private_storage, upload_to=cash_count_path, blank=True)
    pdf_sha256 = models.CharField("Prüfsumme", max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kassenzählung"
        verbose_name_plural = "Kassenzählungen"
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["organization", "date"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.date:%d.%m.%Y}"

    @property
    def difference(self) -> Decimal:
        return self.counted - self.expected

    @property
    def takings(self) -> Decimal:
        """Kassenbericht: Tageseinnahme = Endbestand − Anfangsbestand + Ausgaben + Entnahmen."""
        return self.counted - self.opening + self.expenses + self.withdrawals


class Reserve(models.Model):
    """Rücklage nach § 62 AO (Finanzamt-Prüfung C4, zuschaltbar).

    Eine Rücklage ist kein Konto: Das Geld bleibt auf den Konten, die Rücklage bindet
    einen Teil davon für einen Zweck. Bewegungen sind Zuführungen und Auflösungen."""

    class Kind(models.TextChoices):
        PURPOSE = "purpose", "Projektrücklage (§ 62 Abs. 1 Nr. 1 AO)"
        REPLACEMENT = "replacement", "Wiederbeschaffungsrücklage (§ 62 Abs. 1 Nr. 2 AO)"
        FREE = "free", "freie Rücklage (§ 62 Abs. 1 Nr. 3 AO)"
        OTHER = "other", "sonstige Rücklage"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField("Bezeichnung", max_length=100)
    kind = models.CharField("Art", max_length=12, choices=Kind.choices)
    purpose = models.TextField("Zweck bzw. Vorhaben", max_length=1000, blank=True)
    is_active = models.BooleanField("aktiv", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Rücklage"
        verbose_name_plural = "Rücklagen"
        ordering = ["-is_active", "name"]

    def __str__(self) -> str:
        return self.name


class ReserveMovement(models.Model):
    """Zuführung zu oder Auflösung einer Rücklage."""

    class Direction(models.TextChoices):
        ADD = "add", "Zuführung"
        RELEASE = "release", "Auflösung"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    reserve = models.ForeignKey(Reserve, on_delete=models.PROTECT, related_name="movements")
    direction = models.CharField("Art", max_length=10, choices=Direction.choices)
    date = models.DateField("Datum")
    year = models.PositiveSmallIntegerField("Geschäftsjahr")
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    note = models.CharField("Begründung", max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Rücklagenbewegung"
        verbose_name_plural = "Rücklagenbewegungen"
        ordering = ["date", "pk"]
        indexes = [models.Index(fields=["organization", "year"])]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.reserve} {self.amount} €"

    @property
    def signed(self) -> Decimal:
        return self.amount if self.direction == self.Direction.ADD else -self.amount
