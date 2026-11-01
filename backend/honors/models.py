"""Würden und Chronik: „Wer war wann König?“

Jede Einheit legt ihre Würden selbst an (z. B. König, Prinz, Kaiser, Zugkönig);
nichts ist vorgegeben. Eine Regentschaft verbindet Würde, Jahr (oder Zeitraum)
und Person. Die Person ist ein Mitglied aus HUBIplan oder ein Name als Text (für
die Zeit vor HUBIplan, Verstorbene und Nichtmitglieder). Begleitpersonen
(Königin, Minister, Adjutant …) hängen an der Regentschaft.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext

from core.plural import guess_plural  # noqa: F401  (hier weiter importierbar)
from core.privatefiles import PrivateFileField
from exchange.models import private_storage


class Dignity(models.Model):
    """Würde einer Einheit; ``unit`` ist die Untereinheit (leer: die Einheit selbst)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    unit = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Untereinheit",
    )
    name = models.CharField("Bezeichnung", max_length=100)
    # Mehrzahl für Überschrift und Menü der Webseite (leer: aus der Bezeichnung abgeleitet)
    name_plural = models.CharField("Mehrzahl", max_length=100, blank=True)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    is_public = models.BooleanField("in der Chronik auf der Webseite", default=True)
    is_archived = models.BooleanField("nicht mehr verwendet", default=False)
    # Ordnungszahl je gleichem Vornamen: erster Michael „Michael I.“, zweiter „Michael II.“
    numbered = models.BooleanField("Ordnungszahl je Vorname", default=False)
    # Mehrfacher Würdenträger: jede Regentschaft zählt neu (sonst behält er seine Zahl)
    count_each_reign = models.BooleanField("bei mehrfacher Würde neu zählen", default=False)
    # Einheiten darunter (z. B. Vereine unter einem Dachverband, Züge eines Vereins) sehen
    # die Würdenträger lesend und können sie auf ihrer Webseite zeigen (Ralf 2026-10-31)
    share_down = models.BooleanField("an Untereinheiten weitergeben", default=False)

    class Meta:
        verbose_name = "Würde"
        verbose_name_plural = "Würden"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        from core.reorder import append_if_new

        # Neue Würden kommen ans Ende der Würden ihrer Einheit
        siblings = Dignity.objects.filter(
            organization_id=self.organization_id, unit_id=self.unit_id
        )
        append_if_new(self, "sort_order", siblings)
        super().save(*args, **kwargs)

    @property
    def plural(self) -> str:
        return self.name_plural.strip() or guess_plural(self.name)


class Reign(models.Model):
    """Regentschaft: wer in welchem Jahr, welchen Jahren oder welchem Zeitraum eine Würde trug."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    dignity = models.ForeignKey(
        Dignity, on_delete=models.PROTECT, related_name="reigns", verbose_name="Würde"
    )
    year = models.PositiveSmallIntegerField("Jahr", null=True, blank=True)
    # Startjahr/Endjahr ohne genaues Datum: year ist das Startjahr
    end_year = models.PositiveSmallIntegerField("bis Jahr", null=True, blank=True)
    valid_from = models.DateField("von", null=True, blank=True)
    valid_until = models.DateField("bis", null=True, blank=True)
    person = models.ForeignKey(
        "members.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reigns",
        verbose_name="Mitglied",
    )
    # Name als Text: ohne Mitglied der einzige Name, mit Mitglied ein Stand für
    # die Chronik, falls die Mitgliedsdaten später gelöscht werden
    name = models.CharField("Name", max_length=200, blank=True)
    note = models.CharField("Bemerkung", max_length=200, blank=True)
    # Woher der Würdenträger kam (Ralf 2026-10-31): eine Einheit darunter (Verein unter dem
    # Dachverband, Zug eines Vereins) oder frei als Text, z. B. für längst aufgelöste Vereine.
    # Bei weitergegebenen Würden sieht eine Einheit darunter nur ihre eigenen Träger.
    origin = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="aus Einheit",
    )
    origin_name = models.CharField("aus (frei)", max_length=200, blank=True)
    # Von Hand gesetzte Ordnungszahl (leer: automatisch je Vorname, siehe honors.numbering)
    ordinal = models.PositiveSmallIntegerField("Ordnungszahl", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regentschaft"
        verbose_name_plural = "Regentschaften"
        ordering = ["-year", "-valid_from", "-pk"]
        indexes = [models.Index(fields=["organization", "dignity", "year"])]

    def __str__(self) -> str:
        return f"{self.dignity} {self.period_text}: {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.person_id and self.person:
            return f"{self.person.first_name} {self.person.last_name}".strip()
        return self.name

    @property
    def origin_text(self) -> str:
        return self.origin.name if self.origin_id and self.origin else self.origin_name

    @property
    def period_text(self) -> str:
        if self.year:
            if self.end_year and self.end_year != self.year:
                return f"{self.year}–{self.end_year}"
            return str(self.year)
        start = self.valid_from.year if self.valid_from else ""
        end = self.valid_until.year if self.valid_until else ""
        return f"{start}–{end}" if end != start else str(start)

    @property
    def sort_year(self) -> int:
        if self.year:
            return self.year
        return self.valid_from.year if self.valid_from else 0

    def clean(self):
        if not self.year and not self.valid_from:
            raise ValidationError({"year": gettext("Bitte ein Jahr oder einen Zeitraum angeben.")})
        if self.year and not (1000 <= self.year <= 2999):
            raise ValidationError({"year": gettext("Bitte ein vierstelliges Jahr angeben.")})
        if self.end_year and not self.year:
            raise ValidationError({"end_year": gettext("Bitte zuerst das Startjahr angeben.")})
        if self.end_year and not (1000 <= self.end_year <= 2999):
            raise ValidationError({"end_year": gettext("Bitte ein vierstelliges Jahr angeben.")})
        if self.year and self.end_year and self.end_year < self.year:
            raise ValidationError({"end_year": gettext("Das Endjahr liegt vor dem Startjahr.")})
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": gettext("Das Ende liegt vor dem Beginn.")})
        if self.ordinal is not None and not (1 <= self.ordinal <= 3999):
            raise ValidationError({"ordinal": gettext("Bitte eine Zahl von 1 bis 3999 angeben.")})
        if not self.person_id and not self.name.strip():
            raise ValidationError(
                {"name": gettext("Bitte ein Mitglied wählen oder einen Namen angeben.")}
            )


class Companion(models.Model):
    """Begleitperson einer Regentschaft (z. B. Königin, Minister, Adjutant)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    reign = models.ForeignKey(Reign, on_delete=models.CASCADE, related_name="companions")
    label = models.CharField("Funktion", max_length=60)
    person = models.ForeignKey(
        "members.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Mitglied",
    )
    name = models.CharField("Name", max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)

    class Meta:
        verbose_name = "Begleitperson"
        verbose_name_plural = "Begleitpersonen"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return f"{self.label}: {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.person_id and self.person:
            return f"{self.person.first_name} {self.person.last_name}".strip()
        return self.name


def photo_path(instance, filename: str) -> str:
    return f"honors/{instance.organization_id}/{instance.key}-{filename}"


class ReignPhoto(models.Model):
    """Foto einer Regentschaft (z. B. Königspaar), verkleinert und ohne Metadaten."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    reign = models.OneToOneField(Reign, on_delete=models.CASCADE, related_name="photo")
    key = models.CharField(max_length=24, unique=True)
    file = PrivateFileField("Foto", storage=private_storage, upload_to=photo_path)
    small = PrivateFileField("Foto klein", storage=private_storage, upload_to=photo_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Foto einer Regentschaft"
        verbose_name_plural = "Fotos von Regentschaften"

    def __str__(self) -> str:
        return f"Foto: {self.reign}"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(12)
