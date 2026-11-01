"""Wettbewerbe: eigene Schießen und andere Wettbewerbe mit Einzel- und Zugwertung.

Ein Wettbewerb (z. B. „Preisschießen 2027“) hat Grunddaten, Starter und eine oder
mehrere Wertungen. Eine Einzelwertung sammelt je Starter einen Wert; eine Wertung
der Untereinheiten (Zugwertung) rechnet aus den Werten einer Einzelwertung. Die
Rangliste rechnet ``ranking.py``; bei Gleichstand auf Preisplätzen entscheidet ein
Stechen. Konzept: konzepte/wettbewerbe.md, Doku docs/wettbewerbe.md.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


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

    class Form(models.TextChoices):
        RANKING = "rangliste", "Rangliste"
        BIRD = "vogel", "Vogelschießen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    title = models.CharField("Titel", max_length=200)
    form = models.CharField("Form", max_length=10, choices=Form.choices, default=Form.RANKING)
    # Fremder Wettbewerb: ein anderer richtet aus, die Einheit trägt nur ihre eigenen
    # Starter mit Platz und Wert ein (Konzept Abschnitt 4 und 7)
    own = models.BooleanField("eigener Wettbewerb", default=True)
    organizer = models.CharField("Ausrichter", max_length=200, blank=True)
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
    # Vogelschießen (Konzept 5b)
    drop_out = models.BooleanField("wer ein Pfand errungen hat, scheidet aus", default=True)
    fixed_order = models.BooleanField("Pfänder in fester Reihenfolge", default=False)
    # Gesamtzahl der Schüsse, wenn nachträglich erfasst (live: Anzahl der Schüsse)
    total_shots = models.PositiveIntegerField("Schüsse insgesamt", null=True, blank=True)
    # Lose im Hut (Ralf 2026-11-01): „Nummer ziehen“ zieht aus 1 bis zu dieser Zahl; leer:
    # aus 1 bis Zahl der Starter, dann bekommt ein Nachzügler meist die nächste Nummer.
    lots = models.PositiveIntegerField("Lose im Hut", null=True, blank=True)
    # Zählt jedes Zurücksetzen; der Standmodus schickt ihn mit, damit alte Offline-Eingaben
    # nach dem Zurücksetzen nicht wieder auftauchen.
    generation = models.PositiveIntegerField("Zurückgesetzt", default=0, editable=False)
    # Termin im Kalender, zu dem der Wettbewerb gehört (Zusagen als Starter übernehmen)
    event = models.ForeignKey(
        "events.Event",
        verbose_name="Termin",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="competitions",
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
        # nur bei fremden Wettbewerben: die eigenen Mannschaften
        TEAM = "mannschaft", "Mannschaftswertung"

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
    # Fremder Wettbewerb: Teilnehmer insgesamt („Platz 2 von 14“)
    field_size = models.PositiveIntegerField("Teilnehmer insgesamt", null=True, blank=True)

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


class Presence(models.TextChoices):
    PRESENT = "", "dabei"
    ABSENT = "fehlt", "fehlt"
    WITHDRAWN = "zurueckgezogen", "zurückgezogen"


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
    # Vogelschießen: fehlt kurz oder hat sich zurückgezogen (wird übersprungen)
    presence = models.CharField(
        "Teilnahme", max_length=15, choices=Presence.choices, default=Presence.PRESENT, blank=True
    )
    # Losnummer: wie gezogen (Hut, digital, alle auf einmal) und wann
    drawn_how = models.CharField("gezogen", max_length=10, blank=True)
    drawn_at = models.DateTimeField("gezogen am", null=True, blank=True)
    # Kennung vom Gerät (Standmodus offline), damit ein Starter nicht doppelt ankommt
    client_key = models.UUIDField(null=True, blank=True, editable=False)
    # Gerätekennungen anderer Tablets, die dasselbe Mitglied offline angelegt haben
    aliases = models.JSONField(default=list, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Stand für die Live-Ansichten (services.version)
    updated_at = models.DateTimeField(auto_now=True)

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
    # Ohne Empfang angelegt (Ralf 2026-11-01): Kennung des Geräts; legen zwei Geräte dasselbe
    # Stechen an, wird das zweite zur weiteren Kennung (aliases) des ersten
    client_key = models.UUIDField(null=True, blank=True, editable=False)
    aliases = models.JSONField(default=list, blank=True, editable=False)

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

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Teilnahme am Stechen"
        verbose_name_plural = "Teilnahmen am Stechen"
        ordering = ["pk"]

    def __str__(self) -> str:
        return self.name or str(self.unit or self.starter)

    @property
    def key(self) -> str:
        return f"u{self.unit_id}" if self.unit_id else f"s{self.starter_id}"


class Prize(models.Model):
    """Pfand beim Vogelschießen (Kopf, Flügel, Schweif, Rumpf …) und wer es errungen hat.

    ``shot_number``: mit dem wievielten Schuss insgesamt; ``shots_for``: Schüsse seit dem
    vorher gefallenen Pfand. Live erfasst zeigt ``shot`` auf den Schuss."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="prizes")
    name = models.CharField("Pfand", max_length=100)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    award = models.CharField("Preis", max_length=200, blank=True)
    winner = models.ForeignKey(
        Starter, on_delete=models.SET_NULL, null=True, blank=True, related_name="prizes"
    )
    winner_name = models.CharField("errungen von", max_length=200, blank=True)
    shot_number = models.PositiveIntegerField("Schuss Nr.", null=True, blank=True)
    shots_for = models.PositiveIntegerField("Schüsse für dieses Pfand", null=True, blank=True)
    shot = models.ForeignKey(
        "Shot", on_delete=models.SET_NULL, null=True, blank=True, related_name="hits"
    )
    fallen_at = models.DateTimeField("gefallen um", null=True, blank=True)

    class Meta:
        verbose_name = "Pfand"
        verbose_name_plural = "Pfänder"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.name

    @property
    def fallen(self) -> bool:
        return self.winner_id is not None or bool(self.winner_name)


class Shot(models.Model):
    """Ein Schuss beim Vogelschießen, live im Standmodus gezählt."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="shots")
    number = models.PositiveIntegerField("Nr.")
    starter = models.ForeignKey(
        Starter, on_delete=models.SET_NULL, null=True, blank=True, related_name="shots"
    )
    name = models.CharField("Schütze", max_length=200, blank=True)
    at = models.DateTimeField("Zeit")
    client_key = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Schuss"
        verbose_name_plural = "Schüsse"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["competition", "number"], name="competitions_schuss_nr"
            ),
            models.UniqueConstraint(
                fields=["competition", "client_key"],
                condition=models.Q(client_key__isnull=False),
                name="competitions_schuss_geraet",
            ),
        ]

    def __str__(self) -> str:
        return f"Schuss {self.number}"


class Team(models.Model):
    """Eigene Mannschaft in einem fremden Wettbewerb (z. B. „Mannschaft 1“)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField("Mannschaft", max_length=100)
    sort_order = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    members = models.ManyToManyField(
        Starter, blank=True, related_name="teams", through="TeamMember"
    )

    class Meta:
        verbose_name = "Mannschaft"
        verbose_name_plural = "Mannschaften"
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.name


class TeamMember(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="+")
    starter = models.ForeignKey(Starter, on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = "Mitglied der Mannschaft"
        verbose_name_plural = "Mitglieder der Mannschaft"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "starter"], name="competitions_mannschaft_einmal"
            )
        ]

    def __str__(self) -> str:
        return f"{self.team_id}: {self.starter_id}"


class Placing(models.Model):
    """Platz und Wert, den der Ausrichter eines fremden Wettbewerbs vergeben hat."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    scoring = models.ForeignKey(Scoring, on_delete=models.CASCADE, related_name="placings")
    starter = models.ForeignKey(
        Starter, on_delete=models.CASCADE, null=True, blank=True, related_name="placings"
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True, related_name="placings"
    )
    place = models.PositiveIntegerField("Platz", null=True, blank=True)
    value = models.DecimalField("Wert", max_digits=10, decimal_places=3, null=True, blank=True)
    note = models.CharField("Bemerkung", max_length=200, blank=True)

    class Meta:
        verbose_name = "Platzierung"
        verbose_name_plural = "Platzierungen"
        constraints = [
            models.UniqueConstraint(
                fields=["scoring", "starter"],
                condition=models.Q(starter__isnull=False),
                name="competitions_platz_starter",
            ),
            models.UniqueConstraint(
                fields=["scoring", "team"],
                condition=models.Q(team__isnull=False),
                name="competitions_platz_team",
            ),
        ]

    def __str__(self) -> str:
        return f"Platz {self.place or '–'}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class StandAccess(models.Model):
    """Standzugang: Link bzw. QR-Code, der nur diesen Wettbewerb im Standmodus öffnet
    (für ein geliehenes Tablet ohne eigenes Konto). Nur Erfassen; läuft am Ende des Tages
    ab oder wird beendet."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="stand_accesses"
    )
    label = models.CharField("Bezeichnung", max_length=100, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField("gültig bis")
    revoked_at = models.DateTimeField("beendet am", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Standzugang"
        verbose_name_plural = "Standzugänge"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Standzugang {self.label}".strip()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @classmethod
    def create(cls, comp: Competition, label: str, user, until: datetime.datetime):
        token = secrets.token_urlsafe(24)
        access = cls.objects.create(
            organization=comp.organization,
            competition=comp,
            label=label,
            token_hash=hash_token(token),
            expires_at=until,
            created_by=user,
        )
        return access, token
