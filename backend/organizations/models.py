"""Organisationseinheiten: ein Baum von Einheiten unter der Plattform.

Jede Einheit ist eine ``Organization``. Wie sie heißt (z. B. „Verein“, „Zug“),
legt sie selbst fest (``label``-Felder). Technisch gibt es noch drei Arten
(``type``): Einheiten mit eigenem Datenbereich (``federation``, ``club``) und
Untereinheiten (``unit``, früher „Abteilung“), deren Daten im Bereich der
Einheit ``organization`` liegen.
"""

from __future__ import annotations

import datetime
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from access.models import Role

from .theme import validate_hex_color

MAX_LOGO_BYTES = 2 * 1024 * 1024


def validate_logo(file) -> None:
    if file and file.size > MAX_LOGO_BYTES:
        raise ValidationError("Das Logo darf höchstens 2 MB groß sein.")


def logo_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    if ext not in {"png", "jpg", "jpeg", "webp"}:
        ext = "png"  # nie eine Endung, die der Webserver als Seite ausliefert
    prefix = "abteilungen" if getattr(instance, "type", "") == "unit" else "organisationen"
    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return f"logos/{prefix}/{instance.pk or 'neu'}-{stamp}.{ext}"


def homepage_image_path(instance, filename: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return f"homepages/{instance.pk or 'neu'}-{stamp}.jpg"


def default_jubilee_years() -> list[int]:
    return [10, 25, 40, 50, 60]


def default_unit_jubilee_years() -> list[int]:
    return [10, 25, 50, 60, 75, 100, 125, 150, 175, 200]


class DatePrecision(models.TextChoices):
    """Wie genau Mitgliedschaften angezeigt und Jubiläen berechnet werden.

    Gespeichert wird immer tagesgenau; die Genauigkeit wirkt nur auf Anzeige
    und Berechnung.
    """

    DAY = "day", "tagesgenau"
    MONTH = "month", "monatsgenau"
    YEAR = "year", "jahresgenau"


def founding_year_validators():
    return [MinValueValidator(800), MaxValueValidator(2100)]


SHORT_NAME_MAX = 50

# Arbeitsbereich einer Untereinheit: diese Module sind immer eingeschaltet
WORKSPACE_MODULES = frozenset({"finance", "billing"})

# Vorgabe für die Bezeichnung neuer Einheiten (Einzahl, Mehrzahl, Genus, Genitiv);
# jede Einheit kann sie in der App ändern.
DEFAULT_LABELS = {
    "platform": ("Plattform", "Plattformen", "f", ""),
    "federation": ("Dachverband", "Dachverbände", "m", "Dachverbands"),
    "club": ("Verein", "Vereine", "m", "Vereins"),
}
# Vorgabe für die Bezeichnung der Untereinheiten (``department_label*``)
DEFAULT_CHILD_LABELS = {
    "platform": ("Einheit", "Einheiten", "f", ""),
    "federation": ("Verein", "Vereine", "m", "Vereins"),
    "unit": ("Gruppe", "Gruppen", "f", ""),
}


class ShortNameMixin:
    """Optionaler Kurzname für enge Stellen (Navigation, Listen, Auswahlfelder).

    Dokumente (Rechnungen, PDFs, Ausweise, Mails) verwenden immer den
    vollständigen Namen ``name``.
    """

    @property
    def display_name(self) -> str:
        return self.short_name or self.name


class ThemeFields(models.Model):
    """Erscheinungsbild: leer bedeutet „von der übergeordneten Ebene erben“."""

    primary_color = models.CharField(
        "Primärfarbe", max_length=7, blank=True, validators=[validate_hex_color]
    )
    accent_color = models.CharField(
        "Akzentfarbe", max_length=7, blank=True, validators=[validate_hex_color]
    )
    # Namen und weitere Farben der Palette (Ralf 2026-10-31, bis sechs Farben)
    primary_color_name = models.CharField("Name der Hauptfarbe", max_length=30, blank=True)
    accent_color_name = models.CharField("Name der Zweitfarbe", max_length=30, blank=True)
    extra_colors = models.JSONField("weitere Farben", default=list, blank=True)
    logo = models.ImageField(
        "Logo/Wappen", upload_to=logo_path, blank=True, validators=[validate_logo]
    )

    class Meta:
        abstract = True


class FiscalYearFields(models.Model):
    """Geschäftsjahr: Beginn als Tag und Monat, es dauert immer zwölf Monate.

    Ein Geschäftsjahr heißt nach dem Kalenderjahr, in dem es beginnt. Beginnt es
    nicht am 1. Januar, wird es als „2025/26“ angezeigt.
    """

    fiscal_start_month = models.PositiveSmallIntegerField(
        "Geschäftsjahr beginnt im Monat",
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    fiscal_start_day = models.PositiveSmallIntegerField(
        "Geschäftsjahr beginnt am Tag",
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        try:
            datetime.date(2001, self.fiscal_start_month, self.fiscal_start_day)
        except ValueError as exc:
            raise ValidationError(
                {"fiscal_start_day": "Diesen Tag gibt es in dem Monat nicht (in jedem Jahr)."}
            ) from exc

    @property
    def fiscal_is_calendar(self) -> bool:
        return self.fiscal_start_month == 1 and self.fiscal_start_day == 1

    def fiscal_start(self, year: int) -> datetime.date:
        return datetime.date(year, self.fiscal_start_month, self.fiscal_start_day)

    def fiscal_range(self, year: int) -> tuple[datetime.date, datetime.date]:
        """Erster Tag und letzter Tag des Geschäftsjahres ``year``."""
        start = self.fiscal_start(year)
        end = self.fiscal_start(year + 1) - datetime.timedelta(days=1)
        return start, end

    def fiscal_year_of(self, day: datetime.date) -> int:
        return day.year if day >= self.fiscal_start(day.year) else day.year - 1

    def fiscal_label(self, year: int) -> str:
        if self.fiscal_is_calendar:
            return str(year)
        return f"{year}/{(year + 1) % 100:02d}"


class Organization(ShortNameMixin, FiscalYearFields, ThemeFields):
    class Type(models.TextChoices):
        PLATFORM = "platform", "Plattform"
        FEDERATION = "federation", "Dachverband"
        CLUB = "club", "Verein"
        UNIT = "unit", "Untereinheit"

    class MemberAccess(models.TextChoices):
        NONE = "none", "kein Zugriff"
        READ = "read", "nur lesen"
        WRITE = "write", "lesen und ändern"

    class ContactSource(models.TextChoices):
        OWN = "own", "eigene Angaben"
        ROLE = "role", "von einer Vorstandsrolle übernehmen"

    type = models.CharField("Art", max_length=20, choices=Type.choices)
    # Feste Kennung, auch über Instanzen hinweg (Verbund) und beim Umzug unverändert
    uuid = models.UUIDField("feste Kennung", default=uuid.uuid4, unique=True, editable=False)
    parent = models.ForeignKey(
        "self",
        verbose_name="übergeordnete Organisation",
        on_delete=models.PROTECT,
        related_name="children",
        null=True,
        blank=True,
    )
    # Einheit mit dem Datenbereich, zu dem eine Untereinheit gehört (bei
    # Einheiten mit eigenem Datenbereich leer)
    organization = models.ForeignKey(
        "self",
        verbose_name="Datenbereich",
        on_delete=models.CASCADE,
        related_name="departments",
        null=True,
        blank=True,
    )
    name = models.CharField("Name", max_length=200)
    short_name = models.CharField(
        "Kurzname",
        max_length=SHORT_NAME_MAX,
        blank=True,
        help_text="Optional, für Navigation, Listen und Auswahlfelder.",
    )
    # Dachverband: Grammatik seines Namens in den Texten seiner Vereine
    name_gender = models.CharField(
        "Artikel des Namens",
        max_length=1,
        choices=[("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
        default="m",
        help_text="Für Texte der Vereine, z. B. „an den BSV melden“.",
    )
    name_genitive = models.CharField(
        "Name im Genitiv, falls abweichend",
        max_length=200,
        blank=True,
        help_text="Leer: Der Name bleibt unverändert (des BSV).",
    )
    founding_year = models.PositiveSmallIntegerField(
        "Gründungsjahr", null=True, blank=True, validators=founding_year_validators()
    )
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    # Bezeichnung der Einheit selbst (z. B. „Verein“, „Zug“), mit Grammatik
    label = models.CharField("Bezeichnung (Einzahl)", max_length=50, blank=True)
    label_plural = models.CharField("Bezeichnung (Mehrzahl)", max_length=50, blank=True)
    label_gender = models.CharField(
        "Bezeichnung (Genus)",
        max_length=1,
        choices=[("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
        default="m",
    )
    label_genitive = models.CharField(
        "Bezeichnung (Genitiv, falls abweichend)", max_length=50, blank=True
    )
    street = models.CharField("Straße und Hausnummer", max_length=200, blank=True)
    postal_code = models.CharField("PLZ", max_length=10, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)
    country = models.CharField("Land", max_length=100, blank=True, default="Deutschland")

    contact_source = models.CharField(
        "Kontaktdaten", max_length=10, choices=ContactSource.choices, default=ContactSource.OWN
    )
    contact_role = models.ForeignKey(
        "access.Role",
        verbose_name="Kontakt-Rolle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Die Kontaktdaten kommen von der Person, die diese Rolle gerade innehat.",
    )
    contact_email = models.EmailField("E-Mail", blank=True)
    contact_phone = models.CharField("Telefon", max_length=50, blank=True)
    website = models.URLField("Website", blank=True)
    # Untereinheiten: eigene Homepage auf ihrer Seite der Vereinswebseite verlinken
    website_on_site = models.BooleanField(
        "Homepage auf der Webseite verlinken", default=False, db_default=False
    )
    # Vorschaubild der Homepage: einmal von dort geholt (og:image) oder selbst hochgeladen
    website_image = models.ImageField(
        "Vorschaubild der Homepage", upload_to=homepage_image_path, blank=True
    )
    website_image_custom = models.BooleanField(
        "Vorschaubild selbst hochgeladen", default=False, db_default=False
    )
    # Für diese Adresse wurde zuletzt automatisch geholt (nur einmal je Adresse)
    website_image_for = models.CharField(max_length=200, blank=True, default="", db_default="")
    # Speicherbudget der Dokumentablage in GB (leer: DOCUMENT_BUDGET_GB, Standard 5);
    # erhöhen darf nur die Plattform (Gesamtaudit 01.11., GA-S04)
    document_budget_gb = models.PositiveSmallIntegerField(
        "Speicherbudget Dokumente (GB)", null=True, blank=True
    )

    # Vereinseinstellungen zu Abteilungen
    department_label = models.CharField(
        "Bezeichnung für Abteilungen (Einzahl)", max_length=50, default="Abteilung"
    )
    department_label_plural = models.CharField(
        "Bezeichnung für Abteilungen (Mehrzahl)", max_length=50, default="Abteilungen"
    )
    department_label_gender = models.CharField(
        "Bezeichnung für Abteilungen (Genus)",
        max_length=1,
        choices=[("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
        default="f",
    )
    department_label_genitive = models.CharField(
        "Bezeichnung für Abteilungen (Genitiv, falls abweichend)",
        max_length=50,
        blank=True,
        help_text="Leer: wird gebildet (des Zugs, des Kreises). Nur bei Ausnahmen eintragen.",
    )
    allow_multiple_departments = models.BooleanField(
        "Mitglied darf mehreren Abteilungen angehören", default=True
    )
    photo_approval_required = models.BooleanField(
        "Fotos von Mitgliedern erst nach Freigabe anzeigen", default=False
    )
    # Zugänge (Phase 2)
    member_portal_enabled = models.BooleanField(
        "Mitgliederbereich freigeschaltet",
        default=False,
        help_text="Mitglieder können sich anmelden und ihre Daten und Rechnungen sehen.",
    )
    contact_changes_need_approval = models.BooleanField(
        "Änderungen an Kontaktdaten erst nach Bestätigung durch den Verein", default=False
    )
    department_access_enabled = models.BooleanField(
        "Zugang für Abteilungen freigeschaltet",
        default=False,
        help_text="Abteilungsrollen mit Rechten können sich anmelden.",
    )

    # Plattform-Schalter je Dachverband (Wirkung ab späteren Meilensteinen)
    federation_member_access = models.CharField(
        "Zugriff des Dachverbands auf Mitgliedsdaten",
        max_length=10,
        choices=MemberAccess.choices,
        default=MemberAccess.NONE,
    )
    federation_show_former_memberships = models.BooleanField(
        "Frühere Mitgliedschaften für Vereine sichtbar", default=False
    )

    # Jubiläen und Mitgliedsdauer (Meilenstein 4)
    jubilee_years = models.JSONField(
        "Jubiläumsstufen (Jahre)", default=default_jubilee_years, blank=True
    )
    # Jubiläen der Einheit selbst und ihrer Untereinheiten (aus dem Gründungsjahr)
    unit_jubilee_years = models.JSONField(
        "Jubiläumsstufen für Einheiten (Jahre)",
        default=default_unit_jubilee_years,
        blank=True,
    )
    federation_duration_rule = models.CharField(
        "Regel für die Mitgliedsdauer im Dachverband",
        max_length=20,
        choices=[
            ("all_reported", "alle gemeldeten Zeiten"),
            ("active_reported", "nur gemeldete aktive Zeiten"),
        ],
        default="all_reported",
    )
    date_precision = models.CharField(
        "Genauigkeit für Mitgliedschaften und Jubiläen",
        max_length=10,
        choices=DatePrecision.choices,
        default=DatePrecision.DAY,
        blank=True,
        help_text="Bei Untereinheiten leer: wie die übergeordnete Einheit.",
    )

    enabled_modules = models.JSONField("freigeschaltete Module", default=list, blank=True)
    # Vereinssprache (konzepte/englisch.md, Fachfrage F10): Sprache der Belege, Briefe,
    # Rechnungen und der Vereinswebseite. Vorerst immer Deutsch, noch nicht einstellbar.
    language = models.CharField(
        "Vereinssprache", max_length=5, choices=settings.LANGUAGES, default="de", db_default="de"
    )
    # Kasse: Kategorien den vier steuerlichen Bereichen zuordnen (entscheidet die Organisation)
    tax_areas_enabled = models.BooleanField("steuerliche Bereiche in der Kasse", default=False)
    # Kasse: Buchungen bis einschließlich diesem Tag sind festgeschrieben (GoBD); nur vorwärts
    finance_locked_until = models.DateField("Kasse festgeschrieben bis", null=True, blank=True)
    # Kasse: Zählprotokoll (Kassensturz) und Kassenbericht für Feste (offene Ladenkasse)
    cash_counts_enabled = models.BooleanField(
        "Zählprotokoll und Kassenbericht für Feste", default=False
    )
    # Kasse: Rücklagen nach § 62 AO führen (Finanzamt-Prüfung C4)
    reserves_enabled = models.BooleanField("Rücklagen führen", default=False, db_default=False)
    # Kasse: DATEV-Export für die Steuerberatung (Buchungsstapel, zuschaltbar)
    datev_enabled = models.BooleanField("DATEV-Export", default=False)
    datev_consultant = models.CharField("DATEV Beraternummer", max_length=7, blank=True)
    datev_client = models.CharField("DATEV Mandantennummer", max_length=5, blank=True)
    datev_account_length = models.PositiveSmallIntegerField("DATEV Sachkontenlänge", default=4)
    datev_chart = models.CharField("Kontenrahmen", max_length=20, blank=True)
    # Untereinheiten: eigener Arbeitsbereich mit eigener Kasse und eigenen Rollen.
    # Die Mitglieder bleiben in der Einheit mit den Mitgliedschaften.
    own_workspace = models.BooleanField(
        "eigener Arbeitsbereich",
        default=False,
        help_text="Eigene Kasse und eigene Rollen mit Zugängen.",
    )
    # Untereinheiten: Rolleninhaber bekommen eigene Zugänge mit Rechten. Aus: die
    # Einheit darüber verwaltet sie, ihre Rollen sind reine Ämter.
    self_managed = models.BooleanField(
        "verwaltet sich selbst",
        default=False,
        help_text="Rolleninhaber der Untereinheit bekommen Zugänge mit Rechten.",
    )
    # Oberste Einheit mit Untereinheiten (Dachverband): führt auch selbst
    # Mitglieder, z. B. passive Mitglieder ohne Mitgliedschaft darunter.
    direct_members = models.BooleanField(
        "führt eigene Mitglieder",
        default=False,
        help_text="Mitglieder direkt in dieser Einheit, ohne Mitgliedschaft darunter.",
    )
    # Termine: Weitergabe der eigenen, nicht internen Termine an die Einheiten
    # darüber bzw. darunter. Einzelne Termine können abweichen (Event.share_*).
    events_share_up = models.BooleanField(
        "eigene Termine nach oben freigeben",
        default=False,
        help_text="Die eigenen Termine erscheinen im Kalender der übergeordneten Einheit.",
    )
    events_share_down = models.BooleanField(
        "eigene Termine nach unten freigeben",
        default=True,
        help_text="Die eigenen Termine erscheinen bei den Untereinheiten und ihren Mitgliedern.",
    )
    # Untereinheiten: wer ihr (oder einer Einheit darunter) angehört, zahlt keinen
    # Vereinsbeitrag. Der Verbandsbeitrag an den Dachverband bleibt.
    fee_exempt = models.BooleanField(
        "Mitglieder beitragsfrei",
        default=False,
        help_text="Mitglieder dieser Einheit und der Einheiten darunter zahlen keinen Beitrag.",
    )
    is_active = models.BooleanField("aktiv", default=True)
    # Mit einer Einheit darüber stillgelegt: wird mit ihr wieder aktiv (FQ-14)
    inactive_by_parent = models.BooleanField(default=False, editable=False)
    # Platzhalter einer gekoppelten Einheit auf einer anderen Instanz (App peering):
    # ohne Mitglieder, Kasse und Zugänge, nur mit übermittelten Daten
    is_remote = models.BooleanField("auf anderer Instanz", default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organisation"
        verbose_name_plural = "Organisationen"
        ordering = ["type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["type"],
                condition=models.Q(type="platform"),
                name="nur_eine_plattform",
            ),
            # Dazu kommt der Index „untereinheit_name_je_einheit“ (Migration 0014):
            # Namen von Untereinheiten sind je übergeordneter Einheit eindeutig.
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        loaded = getattr(self, "_loaded_active", None)
        active_changed = not self._state.adding and loaded is not None and loaded != self.is_active
        if active_changed and self.is_active:
            self.inactive_by_parent = False
            fields = kwargs.get("update_fields")
            if fields is not None and "is_active" in fields:
                kwargs["update_fields"] = {*fields, "inactive_by_parent"}
        self._save_with_labels(*args, **kwargs)
        self._loaded_active = self.is_active
        if active_changed and self.type in (self.Type.FEDERATION, self.Type.CLUB, self.Type.UNIT):
            from .activity import cascade_active

            cascade_active(self)

    def _save_with_labels(self, *args, **kwargs):
        if self._state.adding and self.type in DEFAULT_CHILD_LABELS:
            if self.department_label == "Abteilung":
                (
                    self.department_label,
                    self.department_label_plural,
                    self.department_label_gender,
                    self.department_label_genitive,
                ) = DEFAULT_CHILD_LABELS[self.type]
        if not self.label and self.type in DEFAULT_LABELS:
            (self.label, self.label_plural, self.label_gender, self.label_genitive) = (
                DEFAULT_LABELS[self.type]
            )
        super().save(*args, **kwargs)
        if self.type in (self.Type.FEDERATION, self.Type.CLUB, self.Type.UNIT):
            # Solange Untereinheiten keine eigene Bezeichnung pflegen, folgt sie der
            # Vorgabe der direkt übergeordneten Einheit („Bezeichnung der Untereinheiten“).
            Organization.objects.filter(parent=self, type=self.Type.UNIT).update(
                label=self.department_label,
                label_plural=self.department_label_plural,
                label_gender=self.department_label_gender,
                label_genitive=self.department_label_genitive,
            )

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_active = instance.__dict__.get("is_active")
        return instance

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.type == self.Type.PLATFORM:
            if self.parent_id:
                errors["parent"] = "Die Plattform hat keine übergeordnete Organisation."
        elif self.type == self.Type.FEDERATION:
            if self.parent and self.parent.type != self.Type.PLATFORM:
                errors["parent"] = "Ein Dachverband hängt direkt unter der Plattform."
        elif self.type == self.Type.CLUB:
            if self.parent and self.parent.type not in (self.Type.PLATFORM, self.Type.FEDERATION):
                errors["parent"] = "Ein Verein gehört zur Plattform oder zu einem Dachverband."
        elif self.type == self.Type.UNIT:
            if self.parent_id is None or self.organization_id is None:
                errors["parent"] = "Eine Untereinheit braucht eine übergeordnete Einheit."
            else:
                error = self.parent_error()
                if error:
                    errors["parent"] = error
        if self.type in (self.Type.FEDERATION, self.Type.CLUB):
            for field in ("founding_year", "street", "postal_code", "city"):
                if not getattr(self, field):
                    errors[field] = "Pflichtfeld."
        if self.contact_role_id and (
            self.contact_role.organization_id != self.pk or self.contact_role.department_id
        ):
            errors["contact_role"] = "Die Rolle muss zu dieser Organisation gehören."
        if self.contact_source == self.ContactSource.ROLE and not self.contact_role_id:
            errors["contact_role"] = "Bitte eine Rolle wählen."
        if errors:
            raise ValidationError(errors)

    def parent_error(self) -> str | None:
        """Prüft die übergeordnete Einheit einer Untereinheit (Datenbereich, Kreis, Tiefe)."""
        from .tree import MAX_DEPTH

        if self.parent_id == self.organization_id:
            return None
        parent = Organization.objects.filter(pk=self.parent_id).first()
        if (
            parent is None
            or parent.type != self.Type.UNIT
            or parent.organization_id != self.organization_id
        ):
            return "Die übergeordnete Einheit muss zum selben Bereich gehören."
        depth, node = 1, parent
        while node is not None and node.type == self.Type.UNIT:
            if self.pk and node.pk == self.pk:
                return "Eine Einheit kann nicht unter sich selbst oder ihren Untereinheiten hängen."
            depth += 1
            node = node.parent
        if self.pk:
            # Beim Umhängen wandern die Untereinheiten mit
            from .tree import UnitTree

            tree = UnitTree.of(self.organization_id)
            depth += max((tree.depth(i) for i in tree.subtree(self.pk)), default=0) - (
                tree.depth(self.pk)
            )
        if depth > MAX_DEPTH:
            return f"Mehr als {MAX_DEPTH} Ebenen sind nicht möglich."
        return None

    @property
    def kind_label(self) -> str:
        """Bezeichnung der Einheit (z. B. „Verein“), sonst die technische Art."""
        return self.label or self.get_type_display()

    @property
    def effective_date_precision(self) -> str:
        """Genauigkeit; leer bei Untereinheiten heißt: wie die übergeordnete Einheit."""
        node = self
        while node is not None:
            if node.date_precision:
                return node.date_precision
            node = node.parent
        return DatePrecision.DAY

    @property
    def keeps_members(self) -> bool:
        """Führt diese Einheit selbst Mitgliedschaften?"""
        if self.type == self.Type.CLUB:
            return True
        return self.type == self.Type.FEDERATION and self.direct_members

    @property
    def federation(self) -> Organization | None:
        if self.type == self.Type.CLUB and self.parent and self.parent.type == self.Type.FEDERATION:
            return self.parent
        return None

    def ancestors(self) -> list[Organization]:
        """Kette nach oben: [self, parent, …, Plattform]."""
        chain, node = [], self
        while node is not None:
            chain.append(node)
            node = node.parent
        return chain

    @classmethod
    def platform(cls) -> Organization:
        org, _ = cls.objects.get_or_create(type=cls.Type.PLATFORM, defaults={"name": "HUBIplan"})
        return org


class PlatformSettings(models.Model):
    """Globale Einstellungen der Plattform (genau ein Datensatz)."""

    class PersonData(models.TextChoices):
        SHARED = "shared", "gemeinsam gepflegt"
        PER_CLUB = "per_club", "eigene Kopie je Verein"

    person_data_mode = models.CharField(
        "Personendaten bei mehreren Vereinen",
        max_length=10,
        choices=PersonData.choices,
        default=PersonData.SHARED,
    )
    deletion_period_months = models.PositiveSmallIntegerField(
        "Löschfrist nach Austritt (Monate)",
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(600)],
    )
    # Verbund: Einheiten dieser Instanz dürfen sich mit Einheiten auf anderen
    # HUBIplan-Instanzen koppeln. Aus: alles wie bisher auf einer Instanz.
    peering_enabled = models.BooleanField("Kopplung mit anderen Instanzen", default=False)
    peering_allowed_hosts = models.TextField(
        "erlaubte Instanzen (leer = alle)",
        blank=True,
        help_text="Domains, eine je Zeile, z. B. verband.example.org",
    )
    # Verbund Schritt 7: Personen melden sich hier mit ihrem Zugang einer gekoppelten
    # Instanz an (nach eigener Verknüpfung). Aus: nur Zugänge dieser Instanz.
    peering_login = models.BooleanField("Anmeldung über gekoppelte Instanzen", default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plattform-Einstellungen"
        verbose_name_plural = "Plattform-Einstellungen"

    def __str__(self) -> str:
        return "Plattform-Einstellungen"

    @classmethod
    def load(cls) -> PlatformSettings:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DepartmentManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type=Organization.Type.UNIT)


class Department(Organization):
    """Untereinheit (früher „Abteilung“): eine Einheit ohne eigenen Datenbereich.

    Sie liegt in derselben Tabelle wie alle Einheiten. ``organization`` ist die
    Einheit, in deren Datenbereich ihre Daten liegen, ``parent`` die direkt
    übergeordnete Einheit.
    """

    objects = DepartmentManager()

    # Im Änderungsprotokoll nur die Felder, die Untereinheiten pflegen
    audit_fields = frozenset(
        {
            "name",
            "short_name",
            "founding_year",
            "website",
            "website_on_site",
            "website_image",
            "sort_order",
            "date_precision",
            "is_active",
            "fee_exempt",
            "fiscal_start_month",
            "fiscal_start_day",
            "primary_color",
            "accent_color",
            "primary_color_name",
            "accent_color_name",
            "extra_colors",
            "logo",
            "own_workspace",
            "self_managed",
            "parent",
        }
    )

    class Meta:
        proxy = True
        verbose_name = "Abteilung"
        verbose_name_plural = "Abteilungen"
        ordering = ["sort_order", "name"]

    def __init__(self, *args, **kwargs):
        # Neue Untereinheiten erben die Genauigkeit, solange keine gesetzt ist
        if not args and "date_precision" not in kwargs:
            kwargs["date_precision"] = ""
        # Termine von Untereinheiten erscheinen wie bisher auch darüber
        if not args and "events_share_up" not in kwargs:
            kwargs["events_share_up"] = True
        super().__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.type = Organization.Type.UNIT
        if self.own_workspace:
            # Ein Arbeitsbereich hat Zugänge, also verwaltet sich die Einheit selbst
            self.self_managed = True
        if self.own_workspace and not WORKSPACE_MODULES <= set(self.enabled_modules or []):
            # Arbeitsbereich: Kasse und Rechnungen
            self.enabled_modules = sorted({*(self.enabled_modules or []), *WORKSPACE_MODULES})
        if self.parent_id is None:
            self.parent_id = self.organization_id
        from core.reorder import append_if_new

        append_if_new(self, "sort_order", Organization.objects.filter(parent_id=self.parent_id))
        if self._state.adding and self.parent_id and not self.label:
            # Bezeichnung nach der Vorgabe der direkt übergeordneten Einheit
            above = Organization.objects.get(pk=self.parent_id)
            self.label = above.department_label
            self.label_plural = above.department_label_plural
            self.label_gender = above.department_label_gender
            self.label_genitive = above.department_label_genitive
        super().save(*args, **kwargs)


class DepartmentRoleManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(department__isnull=False)


class DepartmentRole(Role):
    """Rolle einer Untereinheit (z. B. Zugführer, Kassierer): dieselbe Rolle wie
    ``access.Role``, nur auf die Rollen von Untereinheiten beschränkt.

    Mit Rechten aus dem Katalog der Untereinheiten (``access.catalog.DEPARTMENT_MODULES``)
    und freigeschaltetem Zugang dürfen sich Inhaber anmelden.
    """

    objects = DepartmentRoleManager()

    class Meta:
        proxy = True
        verbose_name = "Rolle der Untereinheit"
        verbose_name_plural = "Rollen der Untereinheiten"
        ordering = ["position", "name"]
        default_manager_name = "objects"


def new_imprint_key() -> str:
    import secrets

    return secrets.token_urlsafe(6)


class Imprint(models.Model):
    """Impressum und Datenschutzhinweise einer Einheit oder der Plattform.

    Leere Felder werden aus den Stammdaten der Einheit ergänzt (Name, Anschrift,
    Kontakt) und bei den Vertretungsberechtigten aus den Rollen mit dem Kennzeichen
    „vertritt die Einheit“. Wie das Impressum nach außen aussieht, berechnet
    ``organizations.imprint``.
    """

    class Mode(models.TextChoices):
        INHERIT = "inherit", "von der übergeordneten Einheit übernehmen"
        OWN = "own", "eigenes Impressum"
        LINK = "link", "auf eigenes Impressum verlinken"

    class PrivacyMode(models.TextChoices):
        TEXT = "text", "Text in HUBIplan"
        LINK = "link", "auf eigene Seite verlinken"

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="imprint"
    )
    # Fester Teil der öffentlichen Adresse (/impressum/<key>); ändert sich nie
    public_key = models.CharField(max_length=20, unique=True, default=new_imprint_key)
    mode = models.CharField("Impressum", max_length=10, choices=Mode.choices)
    external_url = models.URLField("Adresse des eigenen Impressums", blank=True)
    name = models.CharField(
        "Name bzw. Firma", max_length=200, blank=True, help_text="Leer: Name der Einheit."
    )
    legal_form = models.CharField(
        "Rechtsform", max_length=100, blank=True, help_text="z. B. eingetragener Verein"
    )
    street = models.CharField("Straße und Hausnummer", max_length=200, blank=True)
    postal_code = models.CharField("PLZ", max_length=10, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)
    representatives = models.TextField(
        "Vertretungsberechtigt",
        blank=True,
        help_text="Leer: aus den Rollen mit dem Kennzeichen „vertritt die Einheit“.",
    )
    email = models.EmailField("E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    # Nur eingetragene Einheiten (e.V., bei der Plattform z. B. GmbH) haben
    # Registerangaben; dann gehören Registergericht und -nummer ins Impressum.
    registered = models.BooleanField(
        "im Register eingetragen",
        default=False,
        help_text="z. B. eingetragener Verein (e.V.) im Vereinsregister",
    )
    register_court = models.CharField("Registergericht", max_length=100, blank=True)
    register_number = models.CharField("Registernummer", max_length=50, blank=True)
    vat_id = models.CharField("Umsatzsteuer-Identifikationsnummer", max_length=30, blank=True)
    responsible = models.TextField(
        "Verantwortlich nach § 18 Abs. 2 MStV", blank=True, help_text="Name und Anschrift"
    )
    data_protection_officer = models.TextField("Datenschutzbeauftragte(r)", blank=True)
    extra_text = models.TextField("Weitere Angaben", blank=True)
    privacy_mode = models.CharField(
        "Datenschutzhinweise",
        max_length=10,
        choices=PrivacyMode.choices,
        default=PrivacyMode.TEXT,
    )
    # privacy_text ist der Entwurf; öffentlich gilt erst die veröffentlichte Fassung
    # (UI-Audit 29.10. NAF-02)
    privacy_text = models.TextField("Entwurf der Datenschutzhinweise", blank=True)
    privacy_published_text = models.TextField("Veröffentlichte Datenschutzhinweise", blank=True)
    privacy_published_at = models.DateTimeField("Datenschutzhinweise veröffentlicht am", null=True)
    privacy_url = models.URLField("Adresse der Datenschutzhinweise", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Impressum"
        verbose_name_plural = "Impressen"

    def __str__(self) -> str:
        return f"Impressum {self.organization}"

    def clean(self) -> None:
        errors = {}
        if self.mode == self.Mode.LINK and not self.external_url:
            errors["external_url"] = "Bitte die Adresse des Impressums angeben."
        if self.mode == self.Mode.INHERIT and self.organization.type == Organization.Type.PLATFORM:
            errors["mode"] = "Die Plattform braucht ein eigenes Impressum."
        if self.privacy_mode == self.PrivacyMode.LINK and not self.privacy_url:
            errors["privacy_url"] = "Bitte die Adresse der Datenschutzhinweise angeben."
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def default_mode(org: Organization) -> str:
        """Untereinheiten übernehmen, alle anderen haben ein eigenes Impressum."""
        if org.type == Organization.Type.UNIT:
            return Imprint.Mode.INHERIT
        return Imprint.Mode.OWN


class SocialLink(models.Model):
    """Social-Media-Kanal einer Einheit (Stammdaten, z. B. für Briefvorlage und Webseite)."""

    class Kind(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        YOUTUBE = "youtube", "YouTube"
        TIKTOK = "tiktok", "TikTok"
        X = "x", "X"
        MASTODON = "mastodon", "Mastodon"
        BLUESKY = "bluesky", "Bluesky"
        THREADS = "threads", "Threads"
        WHATSAPP = "whatsapp", "WhatsApp-Kanal"
        LINKEDIN = "linkedin", "LinkedIn"
        OTHER = "other", "Sonstiges"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="social_links"
    )
    kind = models.CharField("Art", max_length=20, choices=Kind.choices)
    url = models.URLField("Adresse")
    label = models.CharField(
        "Anzeigename",
        max_length=100,
        blank=True,
        help_text="Kurz, z. B. @hubertus1920; leer: aus der Adresse.",
    )
    position = models.PositiveSmallIntegerField("Reihenfolge", default=0)

    class Meta:
        verbose_name = "Social-Media-Kanal"
        verbose_name_plural = "Social-Media-Kanäle"
        ordering = ["position", "pk"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.display}"

    @property
    def display(self) -> str:
        """Anzeigename oder die Adresse ohne https:// und www."""
        if self.label.strip():
            return self.label.strip()
        text = self.url.split("://", 1)[-1]
        text = text[4:] if text.startswith("www.") else text
        return text.rstrip("/")
