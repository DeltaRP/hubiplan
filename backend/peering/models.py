"""Verbund: Kopplung von Einheiten über mehrere HUBIplan-Instanzen.

Eine Kopplung verbindet genau eine lokale Einheit mit einer Einheit auf einer
anderen Instanz. Die ferne Einheit ist hier ein Platzhalter (``Organization``
mit ``is_remote``): ohne Mitglieder, Kasse oder Zugänge, nur mit dem, was die
andere Seite übermittelt hat.

- Ferne Einheit darunter (Verein auf eigener Instanz unter einem Dachverband
  hier): Platzhalter hängt im Baum unter der lokalen Einheit.
- Ferne Einheit darüber (Dachverband auf anderer Instanz): Platzhalter hängt
  direkt unter der Plattform. Die lokale Einheit wird nicht umgehängt; ihr
  Verbandsbereich (Personen, Verbandsnummern) bleibt unverändert.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.privatefiles import PrivateFileField
from exchange.models import private_storage


def remote_file_path(instance, filename: str) -> str:
    return f"peering/{instance.coupling_id}/{instance.key}-{uuid.uuid4().hex[:8]}.pdf"


class Peer(models.Model):
    """Eine andere HUBIplan-Instanz, mit der hier mindestens eine Kopplung besteht."""

    instance_id = models.UUIDField("Instanz-ID", unique=True)
    base_url = models.CharField("Adresse", max_length=300)
    public_key = models.CharField("Schlüssel (Unterschrift)", max_length=100)
    enc_public_key = models.CharField("Schlüssel (Verschlüsselung)", max_length=100)
    fingerprint = models.CharField("Fingerabdruck", max_length=40)
    versions = models.JSONField("Schnittstellenversionen", default=list)
    country = models.CharField("Serverstandort", max_length=10, blank=True)
    last_seen_at = models.DateTimeField("zuletzt erreicht", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Schlüsselwechsel der Gegenstelle (Härtung H6)
    previous_public_key = models.CharField(
        "alter Schlüssel (Übergangszeit)", max_length=100, blank=True
    )
    previous_until = models.DateTimeField("alter Schlüssel gilt bis", null=True, blank=True)
    keys_changed_at = models.DateTimeField("Schlüssel zuletzt gewechselt", null=True, blank=True)
    # Notfallwechsel der Gegenstelle: neue Schlüssel, bis ein Vorstand den Fingerabdruck bestätigt
    pending_keys = models.JSONField("angekündigte neue Schlüssel", default=dict, blank=True)
    # Fingerabdruck unserer Schlüssel, den die Gegenstelle zuletzt bestätigt hat
    our_fingerprint = models.CharField("unser Fingerabdruck dort", max_length=40, blank=True)

    class Meta:
        verbose_name = "andere Instanz"
        verbose_name_plural = "andere Instanzen"

    def __str__(self) -> str:
        return self.base_url

    @property
    def valid_previous_key(self) -> str:
        if (
            self.previous_public_key
            and self.previous_until
            and self.previous_until > timezone.now()
        ):
            return self.previous_public_key
        return ""


class Coupling(models.Model):
    class Direction(models.TextChoices):
        PARENT = "parent", "ferne Einheit darüber"
        CHILD = "child", "ferne Einheit darunter"

    class State(models.TextChoices):
        REQUESTED = "requested", "angefragt, wartet auf die andere Seite"
        PENDING = "pending", "Anfrage eingegangen, wartet auf Bestätigung"
        ACTIVE = "active", "aktiv"
        PAUSED = "paused", "pausiert"
        # Gegenstelle meldet einen Umzug; erst nach Bestätigung hier geht es weiter
        MOVING = "moving", "Umzug angekündigt, wartet auf Bestätigung"
        ENDED = "ended", "gelöst"
        MOVED = "moved", "umgezogen"

    local_unit = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="couplings"
    )
    # Platzhalter der fernen Einheit (eigene lokale Kennung)
    remote_unit = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, related_name="remote_coupling"
    )
    # Feste Kennung der fernen Einheit auf ihrer Instanz
    remote_uuid = models.UUIDField("Kennung der fernen Einheit")
    peer = models.ForeignKey(Peer, on_delete=models.PROTECT, related_name="couplings")
    direction = models.CharField(max_length=10, choices=Direction.choices)
    state = models.CharField(max_length=10, choices=State.choices)
    # Pakete, die diese Seite freigibt: {schluessel: stufe}; Stufe True/"a"/"b"
    packets = models.JSONField("freigegebene Pakete", default=dict)
    # Pakete, die die andere Seite freigegeben hat (zur Anzeige)
    remote_packets = models.JSONField("Freigaben der anderen Seite", default=dict)
    # Einstellungen dieser Seite, z. B. {"circulars_auto": true}
    options = models.JSONField("Einstellungen", default=dict, blank=True)
    version = models.PositiveSmallIntegerField("Schnittstellenversion", default=1)
    out_seq = models.PositiveIntegerField("zuletzt vergebene Nummer", default=0)
    in_seq = models.PositiveIntegerField("zuletzt verarbeitete Nummer", default=0)
    # Prüfsummen der zuletzt gesendeten bzw. empfangenen Stände je Paket
    sent_hashes = models.JSONField(default=dict)
    received_hashes = models.JSONField(default=dict)
    last_sync_at = models.DateTimeField("zuletzt abgeglichen", null=True, blank=True)
    last_contact_at = models.DateTimeField("zuletzt Kontakt", null=True, blank=True)
    last_error = models.CharField("letzter Fehler", max_length=500, blank=True)
    error_since = models.DateTimeField(null=True, blank=True)
    warned_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Kopplung"
        verbose_name_plural = "Kopplungen"
        constraints = [
            # Eine Einheit hat höchstens eine Einheit darüber (lokal oder fern)
            models.UniqueConstraint(
                fields=["local_unit"],
                condition=models.Q(direction="parent") & ~models.Q(state__in=["ended", "moved"]),
                name="eine_ferne_einheit_darueber",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.local_unit} ↔ {self.remote_unit}"

    @property
    def is_open(self) -> bool:
        return self.state in (self.State.ACTIVE, self.State.PAUSED)

    def level(self, key: str):
        return (self.packets or {}).get(key)

    def remote_level(self, key: str):
        return (self.remote_packets or {}).get(key)


class CouplingCode(models.Model):
    """Einmaliger Kopplungscode, den die obere Einheit erzeugt."""

    unit = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="coupling_codes"
    )
    secret_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kopplungscode"
        verbose_name_plural = "Kopplungscodes"

    def __str__(self) -> str:
        return f"Kopplungscode für {self.unit}"

    @property
    def usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class Message(models.Model):
    """Ein Paket im Verbund-Postausgang bzw. -Eingang.

    Der Inhalt bleibt nur so lange, bis er zugestellt bzw. verarbeitet ist. Danach
    bleibt nur der Nachweis (Art, Nummer, Anzahl Personen, Zeitpunkte).
    """

    class Direction(models.TextChoices):
        OUT = "out", "gesendet"
        IN = "in", "empfangen"

    class State(models.TextChoices):
        QUEUED = "queued", "wartet"
        DONE = "done", "erledigt"
        FAILED = "failed", "fehlgeschlagen"
        REJECTED = "rejected", "abgelehnt"

    coupling = models.ForeignKey(Coupling, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    msg_id = models.UUIDField(default=uuid.uuid4)
    seq = models.PositiveIntegerField()
    kind = models.CharField(max_length=40)
    schema = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(null=True, blank=True)
    persons = models.PositiveIntegerField("Anzahl Personen", default=0)
    state = models.CharField(max_length=10, choices=State.choices, default=State.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_try_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Verbund-Paket"
        verbose_name_plural = "Verbund-Pakete"
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["direction", "msg_id"], name="paket_einmalig"),
            # Gesendete Pakete haben je Kopplung eine eindeutige Nummer (empfangen
            # werden auch veraltete Pakete mit schon bekannter Nummer protokolliert)
            models.UniqueConstraint(
                fields=["coupling", "seq"],
                condition=models.Q(direction="out"),
                name="paket_nummer_je_kopplung",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.kind} #{self.seq}"


class RemoteState(models.Model):
    """Übermittelter Stand eines Pakets der Gegenseite, der nur angezeigt wird
    (z. B. Vorstand, Satzung, Zahlen). Termine liegen dagegen als Termine des
    Platzhalters im Kalender."""

    coupling = models.ForeignKey(Coupling, on_delete=models.CASCADE, related_name="states")
    key = models.CharField(max_length=40)
    data = models.JSONField(default=dict)
    file = PrivateFileField(storage=private_storage, upload_to=remote_file_path, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "übermittelter Stand"
        verbose_name_plural = "übermittelte Stände"
        constraints = [
            models.UniqueConstraint(fields=["coupling", "key"], name="ein_stand_je_paket")
        ]

    def __str__(self) -> str:
        return f"{self.coupling} · {self.key}"

    def encryption_org_id(self) -> int | None:
        # Dateien gehören zur eigenen Einheit der Kopplung (core/privatefiles.py)
        return (
            Coupling.objects.filter(pk=self.coupling_id)
            .values_list("local_unit_id", flat=True)
            .first()
        )


class RemoteInvoice(models.Model):
    """Rechnung zwischen gekoppelten Einheiten (Paket „Rechnungen“, P8/P9).

    Beim Aussteller verweist sie auf die eigene Rechnung (``invoice``) und merkt
    sich die Zahlungsmeldung des Empfängers. Beim Empfänger ist sie eine
    Eingangsrechnung mit PDF; „bezahlt melden“ geht an den Aussteller zurück.
    Maßgeblich für den Ausgleich bleibt der Zahlungseingang beim Aussteller.
    """

    class Status(models.TextChoices):
        OPEN = "open", "offen"
        CANCELLED = "cancelled", "storniert"

    coupling = models.ForeignKey(Coupling, on_delete=models.CASCADE, related_name="invoices")
    uid = models.CharField(max_length=80)
    invoice = models.OneToOneField(
        "billing.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    number = models.CharField("Rechnungsnummer", max_length=40, blank=True)
    subject = models.CharField("Betreff", max_length=200, blank=True)
    date = models.DateField("Rechnungsdatum", null=True, blank=True)
    due_date = models.DateField("fällig am", null=True, blank=True)
    total = models.DecimalField("Betrag", max_digits=12, decimal_places=2, default=0)
    data = models.JSONField(default=dict)
    file = PrivateFileField(storage=private_storage, upload_to=remote_file_path, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    paid_reported_on = models.DateField("als bezahlt gemeldet am", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rechnung im Verbund"
        verbose_name_plural = "Rechnungen im Verbund"
        constraints = [
            models.UniqueConstraint(fields=["coupling", "uid"], name="verbundrechnung_einmalig")
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.subject}"

    def encryption_org_id(self) -> int | None:
        # Dateien gehören zur eigenen Einheit der Kopplung (core/privatefiles.py)
        return (
            Coupling.objects.filter(pk=self.coupling_id)
            .values_list("local_unit_id", flat=True)
            .first()
        )

    @property
    def key(self) -> str:  # für remote_file_path
        return f"rechnung-{self.uid}"


class RemoteMember(models.Model):
    """Eine namentlich gemeldete Mitgliedschaft im Verbund (Paket „Mitgliedermeldung“, Stufe B).

    Beim Verein (unten) verbindet sie die eigene Mitgliedschaft mit der
    Verbandsnummer, die der Dachverband vergeben hat. Beim Dachverband (oben)
    verbindet sie die gemeldete Zeile mit der Mitgliedschaft im Platzhalter des
    Vereins. Kennung ``uid`` ist die des Vereins.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "gemeldet"
        UNCLEAR = "unclear", "Klärfall: Person schon bekannt?"
        WITHDRAWN = "withdrawn", "nicht mehr gemeldet"

    coupling = models.ForeignKey(Coupling, on_delete=models.CASCADE, related_name="members")
    uid = models.CharField(max_length=40)
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    number = models.PositiveIntegerField("Verbandsnummer", null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Oben: gemeldete Zeile bei Klärfällen, Hinweise (z. B. doppelt aktiv)
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "gemeldete Mitgliedschaft im Verbund"
        verbose_name_plural = "gemeldete Mitgliedschaften im Verbund"
        constraints = [
            models.UniqueConstraint(fields=["coupling", "uid"], name="verbundmitglied_einmalig")
        ]

    def __str__(self) -> str:
        return f"{self.coupling} · {self.uid}"


class RemoteTransfer(models.Model):
    """Wechselanfrage über Instanzgrenzen (Verbund, nur mit namentlicher Meldung).

    ``role``: ``from`` = diese Seite führt die bisherige aktive Mitgliedschaft und
    entscheidet; ``to`` = diese Seite möchte aufnehmen. Oben hängt die Anfrage an der
    üblichen Wechselanfrage (``transfer``), unten an der eigenen Mitgliedschaft bzw.
    an den Aufnahmedaten (``data``).
    """

    class Role(models.TextChoices):
        FROM = "from", "bisheriger Verein"
        TO = "to", "neuer Verein"

    class Status(models.TextChoices):
        PENDING = "pending", "offen"
        ACCEPTED = "accepted", "bestätigt"
        REJECTED = "rejected", "abgelehnt"
        CANCELLED = "cancelled", "zurückgezogen"
        FAILED = "failed", "Aufnahme fehlgeschlagen"

    coupling = models.ForeignKey(Coupling, on_delete=models.CASCADE, related_name="transfers")
    tid = models.UUIDField(default=uuid.uuid4)
    role = models.CharField(max_length=4, choices=Role.choices)
    transfer = models.ForeignKey(
        "members.TransferRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    response = models.CharField("Antwort", max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Wechselanfrage im Verbund"
        verbose_name_plural = "Wechselanfragen im Verbund"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["coupling", "tid"], name="verbundwechsel_einmalig")
        ]

    def __str__(self) -> str:
        return f"Wechsel {self.tid} ({self.get_status_display()})"


class RemoteCircular(models.Model):
    """Rundschreiben zur Weitergabe nach unten (P10).

    Oben verweist es auf das eigene Rundschreiben, unten auf den Entwurf bzw. das
    weitergegebene Rundschreiben des Vereins. Zurück kommt nur die Zahl der
    versandten und fehlgeschlagenen Mails.
    """

    class Status(models.TextChoices):
        FORWARDED = "forwarded", "weitergegeben"
        DRAFT = "draft", "liegt als Entwurf vor"
        SENT = "sent", "versendet"
        DISCARDED = "discarded", "nicht weitergegeben"

    coupling = models.ForeignKey(Coupling, on_delete=models.CASCADE, related_name="circulars")
    uid = models.UUIDField(default=uuid.uuid4)
    circular = models.ForeignKey(
        "circulars.Circular", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    subject = models.CharField("Betreff", max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.FORWARDED)
    report = models.JSONField("Rückmeldung", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rundschreiben im Verbund"
        verbose_name_plural = "Rundschreiben im Verbund"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["coupling", "uid"], name="verbundrundschreiben_einmalig"
            )
        ]

    def __str__(self) -> str:
        return self.subject


class LoginLink(models.Model):
    """Hier: Dieses Konto darf sich mit seinem Zugang auf einer anderen Instanz anmelden.

    Angelegt nur von der Person selbst, angemeldet hier (mit 2FA, falls eingerichtet)
    und angemeldet auf der anderen Instanz. Rechte gibt die Verknüpfung keine.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="peering_logins"
    )
    peer = models.ForeignKey(Peer, on_delete=models.CASCADE, related_name="login_links")
    subject = models.CharField("Kennung dort", max_length=64)
    email = models.CharField("E-Mail dort", max_length=254, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Anmeldung über andere Instanz"
        verbose_name_plural = "Anmeldungen über andere Instanzen"
        constraints = [
            models.UniqueConstraint(fields=["peer", "subject"], name="anmeldung_fern_einmalig"),
            models.UniqueConstraint(fields=["user", "peer"], name="anmeldung_fern_je_konto"),
        ]

    def __str__(self) -> str:
        return f"{self.user} über {self.peer}"


class RemoteAccount(models.Model):
    """Heimat-Instanz: Dieses Konto ist mit einem Zugang auf einer anderen Instanz verknüpft.

    Nur für die Einheitenauswahl (Wechsel per Klick, schon angemeldet)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="remote_accounts"
    )
    peer = models.ForeignKey(Peer, on_delete=models.CASCADE, related_name="remote_accounts")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Zugang auf anderer Instanz"
        verbose_name_plural = "Zugänge auf anderen Instanzen"
        constraints = [
            models.UniqueConstraint(fields=["user", "peer"], name="fernzugang_je_konto"),
        ]

    def __str__(self) -> str:
        return f"{self.user} auf {self.peer}"


class UsedAssertion(models.Model):
    """Schon eingelöste Anmeldebestätigung (zusätzlich zum Cache: übersteht Neustarts)."""

    peer = models.ForeignKey(Peer, on_delete=models.CASCADE, related_name="+")
    jti = models.CharField(max_length=64)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "eingelöste Anmeldebestätigung"
        verbose_name_plural = "eingelöste Anmeldebestätigungen"
        constraints = [
            models.UniqueConstraint(fields=["peer", "jti"], name="bestaetigung_einmalig"),
        ]

    def __str__(self) -> str:
        return f"Bestätigung {self.jti}"


class SpinOff(models.Model):
    """Ausgliederung einer Untereinheit auf eine eigene Instanz (Verbund, Schritt 8).

    Der Vereinsvorstand bereitet sie vor: Weg, Stichtag, Prüfliste. Dabei entstehen ein
    Kopplungscode, der an diese Untereinheit gebunden ist, und ein Export mit diesem Code.
    Bestätigt der Verein die Kopplung, wird die Untereinheit zum Platzhalter der fernen
    Einheit (``is_remote``)."""

    class Way(models.TextChoices):
        KEEP = "keep", "Mitglieder bleiben Vereinsmitglieder"
        MOVE = "move", "Mitglieder werden Mitglieder der Untereinheit"

    class State(models.TextChoices):
        PREPARED = "prepared", "vorbereitet (Export und Code erstellt)"
        REQUESTED = "requested", "Kopplung angefragt"
        DONE = "done", "ausgegliedert"
        CANCELLED = "cancelled", "abgebrochen"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="spin_offs"
    )
    unit = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="spin_off_of"
    )
    way = models.CharField("Weg", max_length=10, choices=Way.choices, default=Way.KEEP)
    cutoff = models.DateField("Stichtag")
    checklist = models.JSONField("Prüfliste", default=dict, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PREPARED)
    code = models.OneToOneField(
        CouplingCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="spin_off"
    )
    coupling = models.OneToOneField(
        Coupling, on_delete=models.SET_NULL, null=True, blank=True, related_name="spin_off"
    )
    export_job = models.ForeignKey(
        "datatransfer.TransferJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)
    # Weg B: Sammelaustritt zum Stichtag ausgeführt (Schritt 8e)
    exited_at = models.DateTimeField("Sammelaustritt am", null=True, blank=True)
    exited_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Ausgliederung"
        verbose_name_plural = "Ausgliederungen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Ausgliederung {self.unit}"

    @property
    def is_open(self) -> bool:
        return self.state in (self.State.PREPARED, self.State.REQUESTED)
