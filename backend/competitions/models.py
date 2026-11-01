"""Wettbewerbe: eigene Schießen und andere Wettbewerbe mit Einzel- und Zugwertung.

Ein Wettbewerb (z. B. „Preisschießen 2027“) hat Grunddaten, Starter und eine oder
mehrere Wertungen. Eine Einzelwertung sammelt je Starter einen Wert; eine Wertung
der Untereinheiten (Zugwertung) rechnet aus den Werten einer Einzelwertung. Die
Rangliste rechnet ``ranking.py``; bei Gleichstand auf Preisplätzen entscheidet ein
Stechen. Konzept: konzepte/wettbewerbe.md, Doku docs/wettbewerbe.md.
"""

from __future__ import annotations

from django.db import models


class Competition(models.Model):
    class Status(models.TextChoices):
        PREPARATION = "vorbereitung", "Vorbereitung"
        RUNNING = "laeuft", "läuft"
        PROVISIONAL = "vorlaeufig", "vorläufig"
        FINAL = "endgueltig", "endgültig"

    class Website(models.TextChoices):
        OFF = "aus", "nicht auf der Webseite"
        LIVE = "live", "live während des Wettbewerbs"
        FINAL = "abschluss", "nach Abschluss"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    title = models.CharField("Titel", max_length=200)
    occasion = models.CharField("Anlass", max_length=200, blank=True)
    discipline = models.CharField("Art", max_length=100, blank=True)
    location = models.CharField("Ort", max_length=200, blank=True)
    date = models.DateField("Datum")
    description = models.TextField("Beschreibung", blank=True, max_length=5000)
    # Weitere Angaben frei: [{"label": "Entfernung", "value": "10 m"}, …]
    details = models.JSONField("weitere Angaben", default=list, blank=True)
    status = models.CharField(
        "Zustand", max_length=20, choices=Status.choices, default=Status.PREPARATION
    )
    # Webseite: nicht, live während des Wettbewerbs oder erst nach Abschluss (Ralf 2026-11-01)
    website = models.CharField(
        "auf der Webseite", max_length=10, choices=Website.choices, default=Website.OFF
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Wettbewerb"
        verbose_name_plural = "Wettbewerbe"
        ordering = ["-date", "title"]

    def __str__(self) -> str:
        return self.title


class Scoring(models.Model):
    """Wertung: eine Rangliste innerhalb des Wettbewerbs."""

    class Kind(models.TextChoices):
        INDIVIDUAL = "einzel", "Einzelwertung"
        UNIT = "einheit", "Wertung der Untereinheiten"

    class TeamMode(models.TextChoices):
        SUM_BEST = "beste", "Summe der besten"
        SUM_ALL = "summe", "Summe aller"
        AVERAGE = "durchschnitt", "Durchschnitt aller"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="scorings")
    name = models.CharField("Bezeichnung", max_length=100)
    kind = models.CharField("Art", max_length=10, choices=Kind.choices, default=Kind.INDIVIDUAL)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    # Einzelwertung: Schüsse je Starter und wie viele davon zählen (nur Angabe und Prüfung)
    shots = models.PositiveSmallIntegerField("Schüsse je Starter", null=True, blank=True)
    counted_shots = models.PositiveSmallIntegerField("davon in der Wertung", null=True, blank=True)
    max_per_shot = models.DecimalField(
        "Höchstwert je Schuss", max_digits=7, decimal_places=3, null=True, blank=True
    )
    unit_label = models.CharField("Einheit des Werts", max_length=30, default="Punkte")
    decimals = models.PositiveSmallIntegerField("Nachkommastellen", default=0)
    higher_better = models.BooleanField("größer ist besser", default=True)
    # Wertung der Untereinheiten: aus welcher Einzelwertung und wie gerechnet
    source = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="derived",
        verbose_name="aus der Wertung",
    )
    team_mode = models.CharField(
        "Rechenweise", max_length=15, choices=TeamMode.choices, default=TeamMode.SUM_BEST
    )
    team_size = models.PositiveSmallIntegerField("Anzahl der besten", null=True, blank=True)
    prize_places = models.PositiveSmallIntegerField("Preisplätze", default=3)
    # Stechen: eigene Bedingungen
    shootoff_shots = models.PositiveSmallIntegerField("Schüsse im Stechen", null=True, blank=True)
    shootoff_counted = models.PositiveSmallIntegerField(
        "davon im Stechen gewertet", null=True, blank=True
    )

    class Meta:
        verbose_name = "Wertung"
        verbose_name_plural = "Wertungen"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.name

    @property
    def max_value(self):
        """Höchster gültiger Wert je Starter (leer: keine Prüfung)."""
        if self.max_per_shot is None:
            return None
        count = self.counted_shots or self.shots
        return self.max_per_shot * count if count else None

    @property
    def shootoff_max(self):
        if self.max_per_shot is None:
            return None
        count = self.shootoff_counted or self.shootoff_shots
        return self.max_per_shot * count if count else None


class Starter(models.Model):
    """Wer antritt: ein Mitglied oder ein Gast (Nichtmitglied, nur Name und Verein)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="starters")
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Mitglied",
    )
    # Name als Text: für Gäste die Eingabe, für Mitglieder eine Kopie (bleibt nach Austritt)
    name = models.CharField("Name", max_length=200)
    club = models.CharField("Verein", max_length=200, blank=True)
    unit = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="zählt für",
    )
    number = models.CharField("Startnummer", max_length=20, blank=True)
    out_of_competition = models.BooleanField("außer Konkurrenz", default=False)
    # Kennung vom Gerät (Standmodus offline), damit ein Starter nicht doppelt ankommt
    client_key = models.UUIDField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Starter"
        verbose_name_plural = "Starter"
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["competition", "membership"],
                condition=models.Q(membership__isnull=False),
                name="competitions_starter_einmal",
            ),
            models.UniqueConstraint(
                fields=["competition", "client_key"],
                condition=models.Q(client_key__isnull=False),
                name="competitions_starter_geraet",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_guest(self) -> bool:
        return self.membership_id is None


class Score(models.Model):
    """Wert eines Starters in einer Einzelwertung."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    scoring = models.ForeignKey(Scoring, on_delete=models.CASCADE, related_name="scores")
    starter = models.ForeignKey(Starter, on_delete=models.CASCADE, related_name="scores")
    value = models.DecimalField("Wert", max_digits=10, decimal_places=3)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ergebnis"
        verbose_name_plural = "Ergebnisse"
        constraints = [
            models.UniqueConstraint(fields=["scoring", "starter"], name="competitions_score_einmal")
        ]

    def __str__(self) -> str:
        return f"{self.starter}: {self.value}"


class ShootOff(models.Model):
    """Stechen bei Gleichstand auf Preisplätzen; ``number`` zählt je Wertung hoch."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    scoring = models.ForeignKey(Scoring, on_delete=models.CASCADE, related_name="shootoffs")
    number = models.PositiveSmallIntegerField("Nr.")
    shots = models.PositiveSmallIntegerField("Schüsse", null=True, blank=True)
    counted_shots = models.PositiveSmallIntegerField("davon gewertet", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Stechen"
        verbose_name_plural = "Stechen"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["scoring", "number"], name="competitions_stechen_nr")
        ]

    def __str__(self) -> str:
        return f"{self.number}. Stechen"


class ShootOffEntry(models.Model):
    """Teilnehmer eines Stechens: ein Starter (Einzel) oder eine Untereinheit, für die ein
    Mitglied schießt (auch eines, das im Wettbewerb nicht angetreten ist)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    shootoff = models.ForeignKey(ShootOff, on_delete=models.CASCADE, related_name="entries")
    starter = models.ForeignKey(
        Starter, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    unit = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Schütze",
    )
    name = models.CharField("Schütze", max_length=200, blank=True)
    value = models.DecimalField("Wert", max_digits=10, decimal_places=3, null=True, blank=True)

    class Meta:
        verbose_name = "Teilnahme am Stechen"
        verbose_name_plural = "Teilnahmen am Stechen"
        ordering = ["pk"]

    def __str__(self) -> str:
        return self.name or str(self.unit or self.starter)

    @property
    def key(self) -> str:
        return f"u{self.unit_id}" if self.unit_id else f"s{self.starter_id}"
