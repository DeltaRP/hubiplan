"""Mitgliederverwaltung: Person, Vereinsmitgliedschaft mit Zeiträumen, Mitgliedsarten.

Datenhaltung und Sichtbarkeit:

- ``Person`` (Name, Vorname, Geburtsdatum) und ``FederationMember`` (Verbandsnummer)
  gelten im Verbandsbereich (``scope``): im Dachverband bzw. im eigenständigen
  Verein. So erkennt die Dublettenprüfung dieselbe Person in mehreren Vereinen.
- ``ContactDetails`` (E-Mail, Telefon, Anschrift) gibt es je nach
  Plattform-Einstellung einmal je Person (``organization`` leer) oder je Verein.
- ``Membership`` und alles darunter gehören genau einem Verein.
"""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from access.models import RoleAssignment, RoleAssignmentQuerySet


def today() -> datetime.date:
    return timezone.localdate()


class Gender(models.TextChoices):
    """Geschlecht einer Person. Leer = keine Angabe."""

    MALE = "männlich", "männlich"
    FEMALE = "weiblich", "weiblich"
    DIVERSE = "divers", "divers"


class Person(models.Model):
    scope = models.ForeignKey(
        "organizations.Organization",
        verbose_name="Verbandsbereich",
        on_delete=models.PROTECT,
        related_name="persons",
    )
    last_name = models.CharField("Name", max_length=100)
    first_name = models.CharField("Vorname", max_length=100)
    birth_date = models.DateField("Geburtsdatum")
    # Nach der Löschfrist bleibt nur das Geburtsjahr (Datum auf den 1. Januar gekürzt)
    birth_year_only = models.BooleanField("nur Geburtsjahr bekannt", default=False)
    gender = models.CharField(
        "Geschlecht", max_length=10, choices=Gender.choices, blank=True, default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Person"
        verbose_name_plural = "Personen"
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["scope", "last_name", "first_name"]),
            models.Index(fields=["scope", "birth_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.last_name}, {self.first_name}"


class ContactDetails(models.Model):
    """Kontakt und Anschrift. ``organization`` leer = für alle Vereine gemeinsam."""

    scope = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="contacts")
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    email = models.EmailField("E-Mail-Adresse", blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    street = models.CharField("Straße und Hausnummer", max_length=200)
    postal_code = models.CharField("PLZ", max_length=10)
    city = models.CharField("Ort", max_length=100)
    country = models.CharField("Land", max_length=100, default="Deutschland")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kontaktdaten"
        verbose_name_plural = "Kontaktdaten"
        constraints = [
            models.UniqueConstraint(
                fields=["person", "organization"], name="kontakt_je_person_und_verein"
            ),
            models.UniqueConstraint(
                fields=["person"],
                condition=Q(organization__isnull=True),
                name="gemeinsamer_kontakt_einmal",
            ),
        ]

    def __str__(self) -> str:
        return f"Kontakt {self.person}"


class FederationMember(models.Model):
    """Person im Dachverband: Verbandsmitgliedsnummer und ggf. manueller Eintritt."""

    scope = models.ForeignKey(
        "organizations.Organization",
        verbose_name="Dachverband",
        on_delete=models.PROTECT,
        related_name="federation_members",
    )
    person = models.OneToOneField(Person, on_delete=models.CASCADE, related_name="federation")
    member_number = models.PositiveIntegerField("Verbandsmitgliedsnummer")
    manual_entry_date = models.DateField(
        "Eintritt in den Dachverband (manuell)",
        null=True,
        blank=True,
        help_text="Nur für Altdaten. Sonst wird der Eintritt berechnet.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Verbandsmitglied"
        verbose_name_plural = "Verbandsmitglieder"
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "member_number"], name="verbandsnummer_eindeutig"
            )
        ]

    def __str__(self) -> str:
        return f"{self.member_number} {self.person}"


class MemberType(models.Model):
    """Mitgliedsart eines Vereins (z. B. aktiv, passiv, Ehrenmitglied)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="member_types"
    )
    name = models.CharField("Name", max_length=100)
    reported = models.BooleanField(
        "an Dachverband melden",
        default=True,
        help_text="Mitgliedschaften dieser Art zählen für den Dachverband.",
    )
    active = models.BooleanField(
        "aktiv",
        default=False,
        help_text="Gilt als aktive Mitgliedschaft. Im Dachverband nur in einem Verein erlaubt.",
    )
    counts_for_duration = models.BooleanField(
        "zählt für Mitgliedsdauer",
        default=True,
        help_text="Zeiten dieser Art zählen für die Dauer im Verein.",
    )
    is_archived = models.BooleanField("nicht mehr verwendet", default=False)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)

    class Meta:
        verbose_name = "Mitgliedsart"
        verbose_name_plural = "Mitgliedsarten"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="mitgliedsart_je_verein")
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        from core.reorder import append_if_new

        append_if_new(
            self, "sort_order", MemberType.objects.filter(organization_id=self.organization_id)
        )
        super().save(*args, **kwargs)


class Membership(models.Model):
    """Person in einem Verein. Die Zeiträume stehen in ``MembershipPeriod``."""

    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name="Verein",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    # Verbandsbereich des Vereins – für den Dachverbandszugriff (Meilenstein 6)
    scope = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="memberships")
    club_number = models.CharField("Mitgliedsnummer im Verein", max_length=30, blank=True)
    # Abteilungen zahlen den Beitrag ihrer Mitglieder gesammelt; Ausnahme je Mitglied
    pays_fee_self = models.BooleanField(
        "zahlt Beitrag selbst (keine Sammelrechnung über die Abteilung)", default=False
    )
    # Einwilligung in die Verwendung eines Fotos (Datum und wer sie erfasst hat)
    photo_consent_at = models.DateField("Foto-Einwilligung am", null=True, blank=True)
    photo_consent_source = models.CharField(
        "Foto-Einwilligung erfasst durch",
        max_length=10,
        blank=True,
        choices=[
            ("board", "Vorstand"),
            ("member", "Mitglied (Upload-Link)"),
            ("app", "Mitglied (App)"),
        ],
    )
    # Rundschreiben der Art „Information“ nicht mehr per Mail (Abmeldelink, Portal, Vorstand)
    info_opt_out_at = models.DateTimeField(
        "Informationen per Mail abbestellt am", null=True, blank=True
    )
    # Nach Ablauf der Löschfrist: nur noch das Minimum ist gespeichert
    purged_at = models.DateTimeField("Daten gelöscht am", null=True, blank=True)
    # Ausgegliederte Untereinheit (Verbund, Schritt 8): Kennung derselben Mitgliedschaft
    # beim abgebenden Verein. Darüber ordnet der Verein den Abgleich zu, nicht über Namen.
    origin_ref = models.CharField(
        "Kennung beim abgebenden Verein", max_length=40, blank=True, editable=False
    )
    # Fern geführt (Verbund, Schritt 8d): Stammdaten und Kontakt pflegt die ausgegliederte
    # Untereinheit auf ihrer Instanz; der Verein schlägt nur Korrekturen vor
    managed_by = models.ForeignKey(
        "peering.Coupling",
        verbose_name="fern geführt über",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="managed_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Vereinsmitgliedschaft"
        verbose_name_plural = "Vereinsmitgliedschaften"
        constraints = [
            models.UniqueConstraint(fields=["organization", "person"], name="mitgliedschaft_einmal")
        ]

    def __str__(self) -> str:
        return f"{self.person} in {self.organization}"

    def current_period(self, on: datetime.date | None = None) -> MembershipPeriod | None:
        on = on or today()
        return (
            self.periods.filter(entry_date__lte=on)
            .filter(Q(exit_date__isnull=True) | Q(exit_date__gte=on))
            .first()
        )

    def current_type(self, on: datetime.date | None = None) -> MemberTypeAssignment | None:
        on = on or today()
        return (
            self.type_assignments.filter(valid_from__lte=on)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
            .select_related("member_type")
            .first()
        )


class ExitReason(models.TextChoices):
    EXIT = "exit", "Austritt"
    EXCLUSION = "exclusion", "Ausschluss"
    STRIKE_OFF = "strike_off", "Streichung"
    DEATH = "death", "Tod"
    TRANSFER = "transfer", "Wechsel in anderen Verein"


class MembershipPeriod(models.Model):
    """Ein Zeitraum der Mitgliedschaft. Wiedereintritt = neuer Zeitraum."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="periods")
    entry_date = models.DateField("Eintritt")
    exit_date = models.DateField("Austritt", null=True, blank=True)
    exit_reason = models.CharField(
        "Austrittsgrund", max_length=20, choices=ExitReason.choices, blank=True
    )
    note = models.CharField("Bemerkung", max_length=200, blank=True)

    class Meta:
        verbose_name = "Mitgliedszeitraum"
        verbose_name_plural = "Mitgliedszeiträume"
        ordering = ["entry_date"]
        indexes = [models.Index(fields=["organization", "exit_date"])]

    def __str__(self) -> str:
        return (
            f"{self.entry_date:%d.%m.%Y} – {self.exit_date:%d.%m.%Y}"
            if self.exit_date
            else (f"seit {self.entry_date:%d.%m.%Y}")
        )

    def clean(self) -> None:
        if self.exit_date and self.exit_date < self.entry_date:
            raise ValidationError({"exit_date": "Der Austritt liegt vor dem Eintritt."})
        if self.exit_date and not self.exit_reason:
            raise ValidationError({"exit_reason": "Bitte einen Austrittsgrund angeben."})


class MemberTypeAssignment(models.Model):
    """Mitgliedsart einer Mitgliedschaft mit Von-/Bis-Datum."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="type_assignments"
    )
    member_type = models.ForeignKey(MemberType, on_delete=models.PROTECT, related_name="+")
    valid_from = models.DateField("von")
    valid_until = models.DateField("bis", null=True, blank=True)

    class Meta:
        verbose_name = "Mitgliedsart-Zuordnung"
        verbose_name_plural = "Mitgliedsart-Zuordnungen"
        ordering = ["valid_from"]

    def __str__(self) -> str:
        return f"{self.member_type} ab {self.valid_from:%d.%m.%Y}"


class DepartmentMembership(models.Model):
    """Zugehörigkeit zu einer Abteilung (optional), mit Zeitraum."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="department_memberships"
    )
    department = models.ForeignKey(
        "organizations.Department", on_delete=models.PROTECT, related_name="unit_memberships"
    )
    valid_from = models.DateField("von")
    valid_until = models.DateField("bis", null=True, blank=True)

    class Meta:
        verbose_name = "Abteilungszugehörigkeit"
        verbose_name_plural = "Abteilungszugehörigkeiten"
        ordering = ["valid_from"]

    def __str__(self) -> str:
        return f"{self.department}"


class DepartmentRoleHolderManager(models.Manager.from_queryset(RoleAssignmentQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(membership__isnull=False)


class DepartmentRoleHolder(RoleAssignment):
    """Inhaber einer Rolle einer Untereinheit (z. B. Zugführer), mit Zeitraum.

    Dieselbe Zuordnung wie ``access.RoleAssignment``, nur auf Mitgliedschaften beschränkt.
    """

    objects = DepartmentRoleHolderManager()

    class Meta:
        proxy = True
        verbose_name = "Rolle der Untereinheit (Inhaber)"
        verbose_name_plural = "Rollen der Untereinheiten (Inhaber)"
        ordering = ["valid_from"]
        default_manager_name = "objects"


class HonoraryTitle(models.Model):
    """Ehrung eines Vereins oder Dachverbands (z. B. Ehrenmitglied, Ehrenmajor),
    optional mit Beitragsanpassung. Vergeben wird er am Mitglied mit Von-/Bis-Datum.

    Ehrungen eines Vereins ändern den Vereinsbeitrag, Ehrungen eines Dachverbands den
    Verbandsbeitrag, den der Verein für das Mitglied zahlt."""

    class FeeMode(models.TextChoices):
        NONE = "none", "keine Beitragsänderung"
        FREE = "free", "beitragsfrei"
        AMOUNT = "amount", "fester Jahresbeitrag"
        DISCOUNT = "discount", "Abschlag in Prozent"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="honorary_titles"
    )
    name = models.CharField("Bezeichnung", max_length=100)
    # Mehrzahl als Überschrift auf der Webseite bei mehreren Trägern (leer: abgeleitet)
    name_plural = models.CharField("Mehrzahl", max_length=100, blank=True)
    fee_mode = models.CharField(
        "Beitrag", max_length=10, choices=FeeMode.choices, default=FeeMode.NONE
    )
    fee_amount = models.DecimalField(
        "fester Jahresbeitrag", max_digits=10, decimal_places=2, null=True, blank=True
    )
    fee_discount_percent = models.DecimalField(
        "Abschlag in Prozent", max_digits=5, decimal_places=2, null=True, blank=True
    )
    is_archived = models.BooleanField("nicht mehr verwendet", default=False)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    # Inhaber erscheinen auf der Webseite (z. B. Ehrenmitglieder), solange sie
    # nicht widersprochen haben
    is_public = models.BooleanField("auf der Webseite zeigen", default=False)
    # Nur das Jahr der Verleihung statt Zeitraum von–bis (Ralf 2026-10-31);
    # gespeichert als 1.1. des Jahres ohne Ende
    year_only = models.BooleanField("nur Jahr der Verleihung", default=False, db_default=False)

    class Meta:
        verbose_name = "Ehrung"
        verbose_name_plural = "Ehrungen"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="ehrentitel_je_organisation"
            )
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        from core.reorder import append_if_new

        append_if_new(
            self, "sort_order", HonoraryTitle.objects.filter(organization_id=self.organization_id)
        )
        super().save(*args, **kwargs)

    @property
    def plural(self) -> str:
        from core.plural import guess_plural

        return self.name_plural.strip() or guess_plural(self.name)

    def fee_text(self) -> str:
        if self.fee_mode == self.FeeMode.FREE:
            return "beitragsfrei"
        if self.fee_mode == self.FeeMode.AMOUNT and self.fee_amount is not None:
            return f"{self.fee_amount:.2f} € im Jahr".replace(".", ",")
        if self.fee_mode == self.FeeMode.DISCOUNT and self.fee_discount_percent is not None:
            return f"{self.fee_discount_percent.normalize():f} % Abschlag".replace(".", ",")
        return ""


class HonoraryTitleAward(models.Model):
    """Verliehene Ehrung mit Zeitraum (Verlauf bleibt erhalten).

    ``organization`` ist die verleihende Organisation (Verein oder Dachverband).
    Die Ehrung hängt an der Person: Ein Verein verleiht nur an eigene Mitglieder,
    ein Dachverband an Mitglieder seiner Vereine. Vereine sehen die Ehrungen des
    Dachverbands ihrer Mitglieder.
    """

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="honorary_titles")
    title = models.ForeignKey(HonoraryTitle, on_delete=models.PROTECT, related_name="awards")
    valid_from = models.DateField("von")
    valid_until = models.DateField("bis", null=True, blank=True)
    note = models.CharField("Bemerkung", max_length=200, blank=True)

    class Meta:
        verbose_name = "Ehrung (Verleihung)"
        verbose_name_plural = "Ehrungen (Verleihungen)"
        ordering = ["valid_from"]
        indexes = [models.Index(fields=["organization", "person"])]

    def __str__(self) -> str:
        return f"{self.title}"


def overlaps(a_from, a_until, b_from, b_until) -> bool:
    """Überschneiden sich zwei Zeiträume (offenes Ende = unbegrenzt)?"""
    a_end = a_until or datetime.date.max
    b_end = b_until or datetime.date.max
    return a_from <= b_end and b_from <= a_end


class TransferRequest(models.Model):
    """Wechselanfrage: neuer Verein möchte eine Person aktiv aufnehmen, die im
    alten Verein noch aktiv ist. Der alte Verein bestätigt Austritt oder Wechsel
    zu einer nicht aktiven Art – danach wird die Aufnahme aktiv gespeichert."""

    class Status(models.TextChoices):
        PENDING = "pending", "offen"
        ACCEPTED = "accepted", "bestätigt"
        REJECTED = "rejected", "abgelehnt"
        CANCELLED = "cancelled", "zurückgezogen"

    class Decision(models.TextChoices):
        EXIT = "exit", "Austritt im alten Verein"
        CHANGE_TYPE = "change_type", "Wechsel zu nicht aktiver Art"

    scope = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="transfers")
    from_org = models.ForeignKey(
        "organizations.Organization",
        verbose_name="bisheriger Verein",
        on_delete=models.CASCADE,
        related_name="transfers_out",
    )
    to_org = models.ForeignKey(
        "organizations.Organization",
        verbose_name="neuer Verein",
        on_delete=models.CASCADE,
        related_name="transfers_in",
    )
    member_type = models.ForeignKey(
        MemberType,
        verbose_name="gewünschte Mitgliedsart",
        on_delete=models.PROTECT,
        related_name="+",
    )
    # Name der Art gespeichert, weil der alte Verein die Arten des neuen nicht sieht (RLS)
    member_type_name = models.CharField("Mitgliedsart (Name)", max_length=100, blank=True)
    entry_date = models.DateField("Eintritt im neuen Verein")
    # Aufnahmedaten des neuen Vereins (Kontakt, Abteilungen, Vereinsnummer)
    admission = models.JSONField(default=dict, blank=True)
    message = models.CharField("Nachricht", max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decision = models.CharField(max_length=20, choices=Decision.choices, blank=True)
    response = models.CharField("Antwort", max_length=500, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    decided_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Wechselanfrage"
        verbose_name_plural = "Wechselanfragen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.person}: {self.from_org} → {self.to_org}"


from .photo_models import MemberPhoto, PhotoUploadLink  # noqa: E402, F401
