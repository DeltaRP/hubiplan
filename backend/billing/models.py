"""Beiträge und Rechnungen.

- ``BillingSettings``: Rhythmus, Zahlungsziel, Konto und Kategorie für Zahlungen.
- ``FeeRate`` und ``AgeRate``: Beitrag je Mitgliedsart, Altersstufen mit eigenem
  Betrag oder Abschlag. Beträge gelten für ein ganzes Beitragsjahr (= Geschäftsjahr).
- ``FeeRun``: ein Beitragslauf für einen Abrechnungszeitraum.
- ``Invoice`` mit ``InvoiceLine``: Rechnung an ein Mitglied oder als
  Sammelrechnung an eine Abteilung.
- ``Payment``: Zahlungseingang, erzeugt eine Einnahme-Buchung in der Kasse.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.encfields import EncryptedCharField
from core.privatefiles import PrivateFileField
from exchange.models import private_storage

ZERO = Decimal("0.00")


class Rhythm(models.TextChoices):
    YEARLY = "yearly", "jährlich"
    HALFYEARLY = "halfyearly", "halbjährlich"
    QUARTERLY = "quarterly", "vierteljährlich"
    MONTHLY = "monthly", "monatlich"


PERIODS_PER_YEAR = {
    Rhythm.YEARLY: 1,
    Rhythm.HALFYEARLY: 2,
    Rhythm.QUARTERLY: 4,
    Rhythm.MONTHLY: 12,
}


class BillingSettings(models.Model):
    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, related_name="billing_settings"
    )
    rhythm = models.CharField(
        "Abrechnungsrhythmus", max_length=12, choices=Rhythm.choices, default=Rhythm.YEARLY
    )
    due_days = models.PositiveSmallIntegerField("Zahlungsziel in Tagen", default=14)
    pro_rata = models.BooleanField(
        "Eintritt im laufenden Zeitraum anteilig berechnen (je angefangenem Monat)",
        default=False,
    )
    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Konto für Überweisungen",
    )
    category = models.ForeignKey(
        "finance.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Kategorie für Beitragszahlungen",
    )
    intro_text = models.TextField(
        "Text vor den Posten",
        blank=True,
        default="wir berechnen Ihnen den Mitgliedsbeitrag wie folgt:",
    )
    footer_text = models.TextField("Text unter der Rechnung", blank=True)
    qr_code = models.BooleanField("QR-Code für die Banking-App aufdrucken", default=True)
    # Umsatzsteuer (Standard: nicht ausgewiesen)
    vat_enabled = models.BooleanField("Umsatzsteuer auf Rechnungen ausweisen", default=False)
    vat_rate = models.DecimalField(
        "Steuersatz in Prozent", max_digits=4, decimal_places=2, default=Decimal("19.00")
    )
    tax_number = models.CharField("Steuernummer oder USt-IdNr.", max_length=50, blank=True)
    # Dachverband: Beitrag der Vereine je gemeldetem Mitglied (Jahresbeträge)
    club_rate_active = models.DecimalField(
        "je gemeldetem aktiven Mitglied", max_digits=10, decimal_places=2, null=True, blank=True
    )
    club_rate_passive = models.DecimalField(
        "je gemeldetem passiven Mitglied", max_digits=10, decimal_places=2, null=True, blank=True
    )
    club_base_amount = models.DecimalField(
        "Grundbetrag je Verein", max_digits=10, decimal_places=2, null=True, blank=True
    )
    # SEPA-Lastschrift; ausgeschaltet verschwinden Lastschriften und Mandate aus der Oberfläche
    sepa_enabled = models.BooleanField("SEPA-Lastschrift nutzen", default=False)
    creditor_id = models.CharField("Gläubiger-Identifikationsnummer", max_length=35, blank=True)
    prenotification_days = models.PositiveSmallIntegerField(
        "Vorabankündigung (Tage vor dem Einzug)", default=14
    )

    class Meta:
        verbose_name = "Beitragseinstellungen"
        verbose_name_plural = "Beitragseinstellungen"

    def __str__(self) -> str:
        return f"Beitragseinstellungen {self.organization}"

    @property
    def periods(self) -> int:
        return PERIODS_PER_YEAR[self.rhythm]


class FeeRate(models.Model):
    """Jahresbeitrag je Mitgliedsart."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    member_type = models.OneToOneField(
        "members.MemberType", on_delete=models.CASCADE, related_name="fee_rate"
    )
    amount = models.DecimalField("Jahresbeitrag", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Beitragssatz"
        verbose_name_plural = "Beitragssätze"

    def __str__(self) -> str:
        return f"{self.member_type}: {self.amount}"

    def clean(self):
        if self.amount is not None and self.amount < 0:
            raise ValidationError({"amount": "Der Beitrag darf nicht negativ sein."})


class AgeRate(models.Model):
    """Altersstufe: eigener Jahresbeitrag oder Abschlag in Prozent.

    Maßgeblich ist das Alter zu Beginn des Beitragsjahres. Ohne Mitgliedsart gilt
    die Stufe für alle Mitgliedsarten; eine Stufe mit Mitgliedsart geht vor.
    """

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField("Bezeichnung", max_length=100)
    member_type = models.ForeignKey(
        "members.MemberType",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="nur für Mitgliedsart",
    )
    min_age = models.PositiveSmallIntegerField("ab Alter", null=True, blank=True)
    max_age = models.PositiveSmallIntegerField("bis Alter (einschließlich)", null=True, blank=True)
    amount = models.DecimalField(
        "eigener Jahresbeitrag", max_digits=10, decimal_places=2, null=True, blank=True
    )
    discount_percent = models.DecimalField(
        "Abschlag in Prozent", max_digits=5, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "Altersstufe"
        verbose_name_plural = "Altersstufen"
        ordering = ["min_age", "max_age", "name"]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        errors = {}
        if self.min_age is None and self.max_age is None:
            errors["max_age"] = "Bitte ein Mindest- oder Höchstalter angeben."
        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            errors["max_age"] = "Das Höchstalter liegt unter dem Mindestalter."
        if (self.amount is None) == (self.discount_percent is None):
            errors["amount"] = "Bitte entweder einen eigenen Beitrag oder einen Abschlag angeben."
        if self.amount is not None and self.amount < 0:
            errors["amount"] = "Der Beitrag darf nicht negativ sein."
        if self.discount_percent is not None and not (0 < self.discount_percent <= 100):
            errors["discount_percent"] = "Der Abschlag liegt zwischen 0 und 100 Prozent."
        if errors:
            raise ValidationError(errors)

    def matches(self, age: int) -> bool:
        if self.min_age is not None and age < self.min_age:
            return False
        return not (self.max_age is not None and age > self.max_age)


class FeeRun(models.Model):
    """Beitragslauf für einen Abrechnungszeitraum eines Geschäftsjahres."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    year = models.PositiveSmallIntegerField("Geschäftsjahr")
    rhythm = models.CharField("Rhythmus", max_length=12, choices=Rhythm.choices)
    period = models.PositiveSmallIntegerField("Zeitraum", default=1)
    start_date = models.DateField("von")
    end_date = models.DateField("bis")
    label = models.CharField("Bezeichnung", max_length=100)
    invoice_date = models.DateField("Rechnungsdatum")
    due_date = models.DateField("fällig am")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Kasse bestätigt, dass die Rechnungen ohne E-Mail per Post raus sind (UI-Audit NAF-06)
    post_done_at = models.DateField("Postversand erledigt am", null=True, blank=True)

    class Meta:
        verbose_name = "Beitragslauf"
        verbose_name_plural = "Beitragsläufe"
        ordering = ["-start_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "start_date", "end_date"], name="beitragslauf_einmal"
            )
        ]

    def __str__(self) -> str:
        return self.label


def invoice_pdf_path(instance, filename: str) -> str:
    return f"rechnungen/{instance.organization_id}/{instance.pk}-{filename}"


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        OPEN = "open", "offen"
        PAID = "paid", "bezahlt"
        CANCELLED = "cancelled", "storniert"

    class Recipient(models.TextChoices):
        MEMBER = "member", "Mitglied"
        DEPARTMENT = "department", "Abteilung"
        CLUB = "club", "Verein"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    # Nummer erst beim Festschreiben; Geschäftsjahr nach Rechnungsdatum
    year = models.PositiveSmallIntegerField("Geschäftsjahr", null=True, blank=True)
    number = models.PositiveIntegerField("Rechnungsnummer", null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    recipient_kind = models.CharField(max_length=12, choices=Recipient.choices)
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Mitglied",
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Abteilung",
    )
    # Dachverband an Verein
    club = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="received_invoices",
        verbose_name="Verein",
    )
    run = models.ForeignKey(
        FeeRun, on_delete=models.CASCADE, null=True, blank=True, related_name="invoices"
    )
    # Veranstaltung (Finanzen); Zahlungen werden ihr in der Kasse zugeordnet
    project = models.ForeignKey(
        "finance.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Veranstaltung",
    )
    # Anschrift und E-Mail, wie sie beim Festschreiben galten
    recipient_name = models.CharField("Empfänger", max_length=200)
    recipient_address = models.TextField("Anschrift", blank=True)
    recipient_email = models.EmailField("E-Mail", blank=True)
    date = models.DateField("Rechnungsdatum")
    due_date = models.DateField("fällig am")
    subject = models.CharField("Betreff", max_length=200, default="Rechnung")
    note = models.TextField("Hinweis", blank=True)
    total = models.DecimalField("Betrag", max_digits=12, decimal_places=2, default=ZERO)
    paid = models.DecimalField("bezahlt", max_digits=12, decimal_places=2, default=ZERO)
    sent_at = models.DateTimeField("per E-Mail verschickt", null=True, blank=True)
    # Die Rechnung, wie sie ausgegeben wurde (Fachfrage 4, Audit 31.10.): spätere Änderungen
    # an Briefkopf oder Bankverbindung ändern sie nicht mehr
    issued_pdf = PrivateFileField(
        "ausgegebene Rechnung", storage=private_storage, upload_to=invoice_pdf_path, blank=True
    )
    issued_pdf_sha256 = models.CharField(max_length=64, blank=True)
    cancelled_at = models.DateTimeField("storniert am", null=True, blank=True)
    dunning_level = models.PositiveSmallIntegerField("Mahnstufe", default=0)
    dunned_at = models.DateField("zuletzt gemahnt am", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rechnung"
        verbose_name_plural = "Rechnungen"
        ordering = ["-date", "-number", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year", "number"], name="rechnungsnummer_eindeutig"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recipient_kind="member", membership__isnull=False)
                    | models.Q(recipient_kind="department", department__isnull=False)
                    | models.Q(recipient_kind="club", club__isnull=False)
                ),
                name="rechnung_empfaenger",
            ),
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self) -> str:
        return f"{self.display_number} {self.recipient_name}"

    @property
    def display_number(self) -> str:
        if self.number is None:
            return "Entwurf"
        return f"R{self.organization.fiscal_label(self.year)}-{self.number:04d}"

    @property
    def outstanding(self) -> Decimal:
        if self.status in (self.Status.DRAFT, self.Status.CANCELLED):
            return ZERO
        return max(self.total - self.paid, ZERO)


class InvoiceLine(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField(default=0)
    text = models.CharField("Text", max_length=200)
    detail = models.CharField("Zusatz", max_length=200, blank=True)
    amount = models.DecimalField("Betrag", max_digits=10, decimal_places=2)
    # Beitragsposten: für welches Mitglied (auch in Sammelrechnungen)
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    is_fee = models.BooleanField("Beitrag aus Beitragslauf", default=False)
    is_dunning_fee = models.BooleanField("Mahngebühr", default=False)
    # Umsatzsteuer im Bruttobetrag enthalten (None/0 = keine)
    vat_rate = models.DecimalField(
        "Steuersatz", max_digits=4, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "Rechnungsposten"
        verbose_name_plural = "Rechnungsposten"
        ordering = ["position", "pk"]

    def __str__(self) -> str:
        return self.text


class Payment(models.Model):
    class Method(models.TextChoices):
        TRANSFER = "transfer", "Überweisung"
        CASH = "cash", "bar"
        DEBIT = "debit", "Lastschrift"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField("Datum")
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    method = models.CharField("Zahlungsweg", max_length=10, choices=Method.choices)
    booking = models.OneToOneField(
        "finance.Booking",
        on_delete=models.PROTECT,
        related_name="payment",
        verbose_name="Buchung",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zahlung"
        verbose_name_plural = "Zahlungen"
        ordering = ["date", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="zahlung_positiv")
        ]

    def __str__(self) -> str:
        return f"{self.amount} am {self.date}"


class DunningLevel(models.Model):
    """Mahnstufe: so viele Tage nach Fälligkeit, optional mit Gebühr."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    level = models.PositiveSmallIntegerField("Stufe")
    name = models.CharField("Bezeichnung", max_length=100)
    days = models.PositiveSmallIntegerField("Tage nach Fälligkeit")
    fee = models.DecimalField("Mahngebühr", max_digits=8, decimal_places=2, default=ZERO)
    text = models.TextField("Text", blank=True)

    class Meta:
        verbose_name = "Mahnstufe"
        verbose_name_plural = "Mahnstufen"
        ordering = ["level"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "level"], name="mahnstufe_einmal")
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if self.fee is not None and self.fee < 0:
            raise ValidationError({"fee": "Die Gebühr darf nicht negativ sein."})


class Dunning(models.Model):
    """Ausgelöste Mahnung zu einer Rechnung."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="dunnings")
    level = models.PositiveSmallIntegerField("Stufe")
    name = models.CharField("Bezeichnung", max_length=100)
    text = models.TextField("Text", blank=True)
    date = models.DateField("Datum")
    due_date = models.DateField("neue Zahlungsfrist")
    fee = models.DecimalField("Mahngebühr", max_digits=8, decimal_places=2, default=ZERO)
    sent_at = models.DateTimeField("per E-Mail verschickt", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mahnung"
        verbose_name_plural = "Mahnungen"
        ordering = ["date", "level"]

    def __str__(self) -> str:
        return f"{self.name} zu {self.invoice}"


class Mandate(models.Model):
    """SEPA-Lastschriftmandat (Basislastschrift) eines Mitglieds oder Vereins."""

    class Source(models.TextChoices):
        PAPER = "paper", "schriftlich"
        ONLINE = "online", "im Mitgliederbereich"

    class Status(models.TextChoices):
        ACTIVE = "active", "gültig"
        REVOKED = "revoked", "widerrufen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="mandates",
    )
    club = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Verein (Dachverband zieht ein)",
    )
    reference = models.CharField("Mandatsreferenz", max_length=35)
    # Verschlüsselt (core/encfields.py)
    holder = EncryptedCharField("Kontoinhaber", max_length=70)
    iban = EncryptedCharField("IBAN", max_length=34)
    bic = EncryptedCharField("BIC", max_length=11, blank=True)
    signed_on = models.DateField("Datum der Unterschrift")
    source = models.CharField("Erteilt", max_length=10, choices=Source.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    revoked_on = models.DateField("widerrufen am", null=True, blank=True)
    last_used_on = models.DateField("zuletzt eingezogen", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "SEPA-Mandat"
        verbose_name_plural = "SEPA-Mandate"
        ordering = ["-signed_on", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"], name="mandatsreferenz_eindeutig"
            ),
            models.CheckConstraint(
                condition=models.Q(membership__isnull=False, club__isnull=True)
                | models.Q(membership__isnull=True, club__isnull=False),
                name="mandat_zahler",
            ),
        ]

    def __str__(self) -> str:
        return self.reference


class DebitRun(models.Model):
    """Lastschriftlauf: eine SEPA-XML-Datei für das Online-Banking."""

    class Status(models.TextChoices):
        CREATED = "created", "erstellt"
        BOOKED = "booked", "gebucht"
        CANCELLED = "cancelled", "verworfen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    collection_date = models.DateField("Einzugsdatum")
    account = models.ForeignKey(
        "finance.Account", on_delete=models.PROTECT, related_name="+", verbose_name="Konto"
    )
    message_id = models.CharField(max_length=35)
    # Die einmal erzeugte Bankdatei: erneutes Herunterladen liefert genau diese,
    # auch wenn sich Bank- oder Vereinsdaten inzwischen geändert haben
    xml = models.TextField("SEPA-Datei", blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    booked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lastschriftlauf"
        verbose_name_plural = "Lastschriftläufe"
        ordering = ["-collection_date", "-pk"]

    def __str__(self) -> str:
        return f"Lastschrift {self.collection_date}"


class DebitItem(models.Model):
    class Sequence(models.TextChoices):
        FIRST = "FRST", "Erstlastschrift"
        RECURRING = "RCUR", "Folgelastschrift"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    run = models.ForeignKey(DebitRun, on_delete=models.CASCADE, related_name="items")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="debits")
    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="debits")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    sequence = models.CharField(max_length=4, choices=Sequence.choices)
    end_to_end_id = models.CharField(max_length=35)
    prenotified_at = models.DateTimeField(null=True, blank=True)
    payment = models.OneToOneField(
        Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="debit"
    )

    class Meta:
        verbose_name = "Lastschrift"
        verbose_name_plural = "Lastschriften"
        ordering = ["pk"]

    def __str__(self) -> str:
        return self.end_to_end_id
