"""Briefbogen je Einheit und die gemerkten Wahlen der Vorstände.

Erzeugte Word-Dateien werden nicht gespeichert. Je Person und Einheit merkt sich
HUBIplan nur die Wahl im Dialog und Prüfwerte der verwendeten Daten, damit es
später „Vorlage veraltet“ melden kann.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from organizations.models import Organization


class Letterhead(models.Model):
    class Mode(models.TextChoices):
        OWN = "own", gettext_lazy("eigener Briefbogen")
        INHERIT = "inherit", gettext_lazy("Briefbogen der übergeordneten Einheit")

    class Form(models.TextChoices):
        A = "a", gettext_lazy("DIN 5008 Form A (Anschriftfeld 27 mm von oben)")
        B = "b", gettext_lazy("DIN 5008 Form B (Anschriftfeld 45 mm von oben)")

    class LogoPosition(models.TextChoices):
        RIGHT = "right", "rechts"
        LEFT = "left", "links"
        NONE = "none", gettext_lazy("ohne Logo/Wappen")

    class Font(models.TextChoices):
        ARIAL = "Arial", gettext_lazy("Arial")
        CALIBRI = "Calibri", gettext_lazy("Calibri")
        CAMBRIA = "Cambria", gettext_lazy("Cambria")
        GEORGIA = "Georgia", gettext_lazy("Georgia")
        TIMES = "Times New Roman", gettext_lazy("Times New Roman")
        VERDANA = "Verdana", gettext_lazy("Verdana")

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="letterhead"
    )
    mode = models.CharField("Briefbogen", max_length=10, choices=Mode.choices)
    form = models.CharField("Form", max_length=1, choices=Form.choices, default=Form.B)
    logo_position = models.CharField(
        "Logo/Wappen", max_length=10, choices=LogoPosition.choices, default=LogoPosition.RIGHT
    )
    tagline = models.CharField(
        "Zusatzzeile im Kopf",
        max_length=150,
        blank=True,
        help_text="z. B. „gegründet 1920“; leer: keine Zusatzzeile.",
    )
    font = models.CharField("Schriftart", max_length=40, choices=Font.choices, default=Font.ARIAL)
    salutation = models.CharField(
        "Anrede", max_length=100, default="Sehr geehrte Damen und Herren,"
    )
    closing = models.CharField("Grußformel", max_length=100, default="Mit freundlichen Grüßen")
    show_bank = models.BooleanField("Bankverbindung zeigen", default=True)
    account = models.ForeignKey(
        "finance.Account",
        verbose_name="Bankkonto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Leer: erstes aktives Bankkonto mit IBAN.",
    )
    show_email = models.BooleanField("E-Mail der Einheit zeigen", default=True)
    show_phone = models.BooleanField("Telefon der Einheit zeigen", default=True)
    show_website = models.BooleanField("Webseite zeigen", default=True)
    show_board = models.BooleanField("Vorstand zeigen", default=True)
    show_register = models.BooleanField("Registerangaben und USt-IdNr. zeigen", default=True)
    show_social = models.BooleanField("Social-Media-Kanäle zeigen", default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Briefbogen"
        verbose_name_plural = "Briefbögen"

    def __str__(self) -> str:
        return f"Briefbogen {self.organization}"

    @staticmethod
    def default_mode(org: Organization) -> str:
        if org.type == Organization.Type.UNIT:
            return Letterhead.Mode.INHERIT
        return Letterhead.Mode.OWN


class LetterheadChoice(models.Model):
    """Was eine Person zuletzt für eine Einheit gewählt hat (ohne Inhalte)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="letterhead_choices"
    )
    unit = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    # Absenderkontext: „org:<id>“ (Rolle der Einheit) oder „dept:<id>“ (Rolle der Untereinheit)
    context = models.CharField(max_length=30)
    function = models.CharField(max_length=30, blank=True)
    function_text = models.CharField(max_length=150, blank=True)
    title = models.CharField(max_length=30, blank=True)
    contacts = models.JSONField(default=list, blank=True)
    with_logo = models.BooleanField(default=True)
    file_format = models.CharField(max_length=4, default="dotx")
    # Prüfwerte je Abschnitt (HMAC), nie die Werte selbst
    checksums = models.JSONField(default=dict, blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    hint_dismissed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Wahl für die Briefvorlage"
        verbose_name_plural = "Wahlen für die Briefvorlage"
        constraints = [
            models.UniqueConstraint(fields=["user", "unit"], name="briefvorlage_wahl_je_einheit")
        ]

    def __str__(self) -> str:
        return f"{self.user} – {self.unit}"
