"""Öffentliche Webseite einer Einheit (Daten und Regeln; die Darstellung liegt
im eigenen Repository ``hubiplan-website``).

Eine Einheit hat erst dann eine Webseite, wenn sie hier eingerichtet ist. Die
Webseite liest nur die öffentliche Schnittstelle ``/api/public/site/v1/…``.
"""

from __future__ import annotations

import datetime
import hashlib
import re
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .designs import DEFAULT_DESIGN, DESIGNS

# Bausteine, die sich auf der Webseite einzeln ein- und ausschalten lassen.
# Name und Reihenfolge wie im Menü der Webseite; „units“ trägt in der Verwaltung
# die eigene Bezeichnung der Einheit (z. B. „Züge“).
BLOCKS = {
    "posts": "Aktuelles",
    "events": "Termine",
    "board": "Vorstand",
    "units": "Untereinheiten",
    "honors": "Majestäten",
    "results": "Ergebnisse",
    "history": "Chronik",
    "offices": "Ämter",
    "statutes": "Dokumente",
    "contact": "Kontakt",
    "social": "Social-Media-Symbole",
}
BLOCK_HINTS = {
    "posts": "Beiträge aus Instagram und Facebook (lokal gespeichert)",
    "events": "mit Kalender-Abo",
    "board": "Vorstand und Ansprechpartner",
    "units": "Seiten der Untereinheiten",
    "honors": "aktuelle und frühere Würdenträger",
    "results": "Wettbewerbe mit „auf der Webseite“, Reihen und Wanderpokale",
    "history": "Textseite zur Geschichte des Vereins (Webseite › Texte)",
    "offices": "heutige und frühere Inhaber der Rollen mit „unter Ämter zeigen“",
    "statutes": "Satzung, Beitragsordnung und Gründungsurkunde zum Herunterladen",
    "contact": "Kontaktformular",
    "social": "oben im Kopf, auf dem Handy im Menü",
}
DEFAULT_BLOCKS = {key: True for key in BLOCKS}
# Menüpunkte unter „Würdenträger“, die sich einzeln ausschalten lassen (Ralf 2026-10-31):
# ``dignity:<Nummer>`` je Würde und ``honorary`` für die Ehrungen. Ohne Eintrag: an.
EXTRA_BLOCK = re.compile(r"^(dignity:[1-9][0-9]{0,9}|honorary)$")


def is_extra_block(key) -> bool:
    return isinstance(key, str) and bool(EXTRA_BLOCK.match(key))


# Eigene Namen der Bausteine (Ralf 2026-11-01): erscheinen im Menü und als Überschrift
# auf der Webseite; leer = Standardname. Umbenennbar sind die Bausteine (ohne „social“),
# die Überschrift „Geschichte“ und die Ehrungen. Würden und Textseiten tragen ihren
# Namen schon selbst.
RENAMABLE_BLOCKS = tuple(k for k in BLOCKS if k != "social") + ("group:history", "honorary")
BLOCK_NAME_MAX = 60


# Bausteine der Startseite: ein- und ausschaltbar, Reihenfolge frei. Die
# Standardliste entspricht der Startseite vor der freien Zusammenstellung.
HOME_SECTIONS = {
    "carousel": "Bilderkarussell",
    "greeting": "Willkommenstext",
    "events": "Nächste Termine",
    "honors": "Majestäten",
    "units": "Untereinheiten",
    "results": "Aktuelle Ergebnisse",
    "instagram": "Instagram-Beiträge",
    "facebook": "Facebook-Beiträge",
}
HOME_HINTS = {
    "carousel": "Fotos zum Willkommenstext; bei einem Foto das Titelbild",
    "greeting": "Überschrift und Text unter Webseite › Texte",
    "events": "die nächsten drei öffentlichen Termine",
    "honors": "die aktuellen Majestäten",
    "units": "Kacheln mit Links zu den Seiten der Untereinheiten",
    "results": "die neuesten Wettbewerbe mit den Siegern, live mit Zwischenstand",
    "instagram": "neueste Beiträge, sobald ein Kanal verbunden ist",
    "facebook": "neueste Beiträge, sobald ein Kanal verbunden ist",
}
# Welcher Bereich der Webseite eingeschaltet sein muss, damit der Baustein erscheint
HOME_NEEDS_BLOCK = {"events": "events", "honors": "honors", "units": "units", "results": "results"}
# „Aktuelle Ergebnisse“ ist ein möglicher Block (Ralf 01.11.): erst an, wenn gewählt
DEFAULT_HOME_OFF = {"instagram", "facebook", "results"}


def default_home_sections() -> list:
    return [{"key": k, "on": k not in DEFAULT_HOME_OFF} for k in HOME_SECTIONS]


def normalize_home_sections(value) -> list:
    """Gespeicherte Liste → vollständige Liste in Reihenfolge (neue Bausteine hinten)."""
    result, seen = [], set()
    for item in value or []:
        key = item.get("key") if isinstance(item, dict) else None
        if key in HOME_SECTIONS and key not in seen:
            seen.add(key)
            result.append({"key": key, "on": bool(item.get("on", True))})
    for key in HOME_SECTIONS:
        if key not in seen:
            result.append({"key": key, "on": key not in DEFAULT_HOME_OFF})
    return result


def default_blocks() -> dict:
    return dict(DEFAULT_BLOCKS)


class Website(models.Model):
    """Eingerichtete Webseite einer Einheit (höchstens eine je Einheit)."""

    class State(models.TextChoices):
        OFF = "off", "Aus"
        MAINTENANCE = "maintenance", "Wartung"
        PUBLIC = "public", "Öffentlich"

    class NameFormat(models.TextChoices):
        FULL = "full", "Vorname Name"
        INITIAL = "initial", "Vorname N."

    class MissingConsent(models.TextChoices):
        OMIT = "omit", "auslassen"
        NN = "nn", "als „N. N.“ zeigen"

    class Units(models.TextChoices):
        ALL = "all", "alle"
        SELECTED = "selected", "ausgewählte"
        NONE = "none", "keine"

    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, related_name="site"
    )
    state = models.CharField(
        "Zustand", max_length=12, choices=State.choices, default=State.MAINTENANCE
    )
    maintenance_text = models.TextField(
        "Hinweis auf der Wartungsseite",
        max_length=1000,
        blank=True,
        default="Hier entsteht unsere neue Webseite.",
    )
    # Kennung der Webseite in der öffentlichen Schnittstelle (kein Geheimnis,
    # aber ohne fortlaufende Nummern)
    public_key = models.CharField(max_length=40, unique=True)
    blocks = models.JSONField("Bausteine", default=default_blocks, blank=True)
    # Anordnung des Menüs (Reihenfolge, Unterpunkte); leer = Standard (website/menu.py)
    menu = models.JSONField("Menü", default=list, blank=True)
    # Eigene Namen der Bausteine: Schlüssel → Name (nur gesetzte; RENAMABLE_BLOCKS)
    block_names = models.JSONField("Eigene Namen der Bausteine", default=dict, blank=True)
    home_sections = models.JSONField(
        "Bausteine der Startseite", default=default_home_sections, blank=True
    )
    # Standarddesign der Webseite und eigene Farbzuordnung je Design (Ralf 2026-10-31)
    design = models.CharField(
        "Design",
        max_length=20,
        choices=[(k, d["label"]) for k, d in DESIGNS.items()],
        default=DEFAULT_DESIGN,
    )
    color_roles = models.JSONField("Farbzuordnung je Design", default=dict, blank=True)
    name_format = models.CharField(
        "Namensform", max_length=10, choices=NameFormat.choices, default=NameFormat.FULL
    )
    show_vacant = models.BooleanField(
        "unbesetzte Funktionen als „derzeit unbesetzt“ zeigen", default=False
    )
    missing_consent = models.CharField(
        "Personen ohne Einwilligung",
        max_length=10,
        choices=MissingConsent.choices,
        default=MissingConsent.OMIT,
    )
    units_mode = models.CharField(
        "Untereinheiten", max_length=10, choices=Units.choices, default=Units.ALL
    )
    unit_ids = models.JSONField("ausgewählte Untereinheiten", default=list, blank=True)
    include_unit_events = models.BooleanField(
        "Termine der Untereinheiten im Kalender der Webseite", default=True
    )
    include_parent_events = models.BooleanField(
        "Termine der übergeordneten Einheiten im Kalender der Webseite", default=False
    )
    include_parent_honors = models.BooleanField(
        "weitergegebene Würden der übergeordneten Einheiten zeigen", default=False
    )
    allow_indexing = models.BooleanField("Suchmaschinen erlauben", default=True)
    # Sprache der festen Texte auf der Webseite (konzepte/englisch.md, W1); Vereinsdaten
    # bleiben, wie sie sind
    language = models.CharField(
        "Sprache der Webseite", max_length=8, choices=settings.LANGUAGES, default="de"
    )
    contact_limit_per_hour = models.PositiveSmallIntegerField(
        "höchstens Formularmails je Stunde", default=20
    )
    # Datenschutzhinweise der Webseite (eigener Text, getrennt von denen für Mitglieder)
    privacy_mode = models.CharField(
        "Datenschutzhinweise der Webseite",
        max_length=10,
        choices=[("text", "eigener Text"), ("link", "auf eigene Seite verlinken")],
        default="text",
    )
    # Entwurf; öffentlich gilt die veröffentlichte Fassung (UI-Audit 29.10. NAF-02)
    privacy_text = models.TextField("Entwurf der Datenschutzhinweise", max_length=30000, blank=True)
    privacy_published_text = models.TextField(
        "Veröffentlichte Datenschutzhinweise", max_length=30000, blank=True
    )
    privacy_published_at = models.DateTimeField(
        "Datenschutzhinweise veröffentlicht am", null=True, blank=True
    )
    privacy_url = models.URLField("Adresse der Datenschutzhinweise", blank=True)
    # Stand der Einstellungen bei der letzten Erzeugung (Hinweis „passt nicht mehr“)
    privacy_facts = models.CharField(max_length=64, blank=True)
    privacy_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Webseite"
        verbose_name_plural = "Webseiten"

    def __str__(self) -> str:
        return f"Webseite ({self.get_state_display()})"

    @staticmethod
    def new_key() -> str:
        return secrets.token_urlsafe(18)

    def block_on(self, key: str) -> bool:
        default = True if is_extra_block(key) else DEFAULT_BLOCKS.get(key, False)
        return bool((self.blocks or {}).get(key, default))

    def block_name(self, key: str) -> str:
        """Eigener Name eines Bausteins oder leer (dann gilt der Standardname)."""
        name = (self.block_names or {}).get(key) if key in RENAMABLE_BLOCKS else None
        return name.strip() if isinstance(name, str) else ""

    def names(self) -> dict[str, str]:
        """Alle gesetzten eigenen Namen (für die öffentliche Schnittstelle)."""
        return {k: n for k in RENAMABLE_BLOCKS if (n := self.block_name(k))}

    def home(self) -> list[str]:
        """Eingeschaltete Bausteine der Startseite in ihrer Reihenfolge."""
        keys = []
        for s in normalize_home_sections(self.home_sections):
            needs = HOME_NEEDS_BLOCK.get(s["key"])
            if s["on"] and (needs is None or self.block_on(needs)):
                keys.append(s["key"])
        return keys

    def clean(self):
        unknown = {k for k in self.blocks or {} if k not in BLOCKS and not is_extra_block(k)}
        if unknown:
            raise ValidationError({"blocks": f"Unbekannter Baustein: {sorted(unknown)[0]}"})
        if not 1 <= (self.contact_limit_per_hour or 0) <= 100:
            raise ValidationError(
                {"contact_limit_per_hour": "Bitte einen Wert zwischen 1 und 100 angeben."}
            )


HOSTNAME_RE = r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"


class WebsiteDomain(models.Model):
    """Hostname, unter dem die Webseite erreichbar ist (die Webseite erkennt daran
    die Einheit)."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="domains")
    hostname = models.CharField("Domain", max_length=253, unique=True)
    is_primary = models.BooleanField("Hauptadresse", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Domain der Webseite"
        verbose_name_plural = "Domains der Webseite"
        ordering = ["-is_primary", "hostname"]

    def __str__(self) -> str:
        return self.hostname


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


PREVIEW_LINK_MAX_DAYS = 14


class PreviewLink(models.Model):
    """Zeitlich begrenzter, widerrufbarer Vorschau-Link zum Weitergeben."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="preview_links")
    label = models.CharField("Bezeichnung", max_length=100, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField("gültig bis")
    revoked_at = models.DateTimeField("widerrufen am", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vorschau-Link"
        verbose_name_plural = "Vorschau-Links"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Vorschau-Link {self.label}".strip()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @classmethod
    def create(cls, website: Website, days: int, label: str, user) -> tuple[PreviewLink, str]:
        token = secrets.token_urlsafe(24)
        link = cls.objects.create(
            organization=website.organization,
            website=website,
            label=label,
            token_hash=hash_token(token),
            expires_at=timezone.now() + datetime.timedelta(days=days),
            created_by=user,
        )
        return link, token


class PublicationConsent(models.Model):
    """Einwilligung bzw. Widerspruch eines Mitglieds zur Veröffentlichung.

    Je Kategorie gilt höchstens ein Eintrag ohne Enddatum. Endet ein Eintrag
    (Widerruf der Einwilligung, Rücknahme des Widerspruchs), bleibt er als
    Verlauf erhalten.
    """

    class Category(models.TextChoices):
        NAME = "name", "Name mit Funktion"
        PHOTO = "photo", "Foto"
        EMAIL = "email", "E-Mail-Adresse"
        PHONE = "phone", "Telefonnummer"
        HONORS = "honors", "Würden und Chronik"
        JUBILEES = "jubilees", "Jubiläen"
        RESULTS = "results", "Wettbewerbsergebnisse"
        RESULTS_MINOR = "minor_res", "Wettbewerbsergebnisse unter 18"

    class Source(models.TextChoices):
        BOARD = "board", "Vorstand"
        MEMBER = "member", "Mitglied selbst"
        PAPER = "paper", "Papierformular"

    # Name und Würden erscheinen aus berechtigtem Interesse, solange kein
    # Widerspruch vorliegt; alles andere nur mit Einwilligung.
    # Wettbewerbsergebnisse ebenso (Teilnahme an einem öffentlichen Wettbewerb); unter 18
    # nur mit ausdrücklicher Einwilligung (Kategorie „Wettbewerbsergebnisse unter 18“)
    OBJECTION_CATEGORIES = frozenset({Category.NAME, Category.HONORS, Category.RESULTS})

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="publication_consents"
    )
    category = models.CharField("Kategorie", max_length=10, choices=Category.choices)
    since = models.DateField("seit")
    source = models.CharField("erfasst durch", max_length=10, choices=Source.choices)
    ended_at = models.DateField("beendet am", null=True, blank=True)
    ended_source = models.CharField(
        "beendet durch", max_length=10, choices=Source.choices, blank=True
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Veröffentlichung (Einwilligung/Widerspruch)"
        verbose_name_plural = "Veröffentlichung (Einwilligungen/Widersprüche)"
        ordering = ["category", "-since", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "category"],
                condition=models.Q(ended_at__isnull=True),
                name="veroeffentlichung_einmal_aktiv",
            )
        ]

    def __str__(self) -> str:
        kind = "Widerspruch" if self.is_objection else "Einwilligung"
        return f"{kind}: {self.get_category_display()}"

    @property
    def is_objection(self) -> bool:
        return self.category in self.OBJECTION_CATEGORIES


from .contact_models import HeldMessage  # noqa: E402, F401
from .content_models import WebsiteImage, WebsiteRevision, WebsiteText  # noqa: E402, F401
from .social_models import SocialFeed, SocialPost, SocialPostImage  # noqa: E402, F401
