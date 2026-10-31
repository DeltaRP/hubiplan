"""Kontaktformular der Webseite mit Spam-Schutz in Schichten, ohne Drittanbieter.

1. Honigtopf-Feld (für Menschen unsichtbar)
2. Zeitprüfung (signierter Zeitstempel: nicht schneller als 3 Sekunden, höchstens 2 Stunden)
3. Rechenaufgabe im Browser (Proof of Work, jede Aufgabe nur einmal)
4. Drosselung je IP und je Webseite (harte Obergrenze je Stunde)
5. Inhaltsprüfung (Links, Spamwörter deutsch und englisch, fremde Schrift, Doppelte):
   Auffälliges wird zurückgehalten statt verschickt
"""

from __future__ import annotations

import datetime
import hashlib
import re
import secrets
import time

from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from core.ratelimit import too_many
from outbox.mail import send

from .contact_models import HELD_DAYS, HeldMessage

SALT = "website.contact"
DIFFICULTY = 17  # führende Null-Bits; etwa 130 000 Versuche, im Browser ein bis zwei Sekunden
MIN_SECONDS = 3
MAX_SECONDS = 2 * 60 * 60
IP_LIMIT = 5  # Nachrichten je Stunde und IP
MAX_LINKS = 3
# Wörter und Wendungen, die in Vereinspost praktisch nie vorkommen. Verglichen wird ab
# Wortanfang („betting“ trifft nicht „abetting“, „kryptowährung“ trifft „Kryptowährungen“).
SPAM_WORDS = (
    # englisch
    "viagra",
    "cialis",
    "casino",
    "crypto",
    "bitcoin",
    "forex",
    "seo service",
    "seo agency",
    "backlink",
    "guest post",
    "loan offer",
    "porn",
    "betting",
    "investment opportunity",
    # deutsch
    "potenzmittel",
    "online-casino",
    "online casino",
    "sportwetten",
    "kryptowährung",
    "kredit ohne schufa",
    "sofortkredit",
    "schnell geld",
    "geld verdienen von zu hause",
    "passives einkommen",
    "nebenverdienst",
    "suchmaschinenoptimierung",
    "seo-agentur",
    "seo agentur",
    "erotik",
    "sexkontakt",
    "abnehmen ohne",
)
SPAM_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in SPAM_WORDS) + ")")
FOREIGN_SHARE = 0.3  # ab diesem Anteil kyrillischer oder ostasiatischer Buchstaben
FOREIGN = re.compile(r"[\u0400-\u04ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
KIND = "website-contact"


def challenge(website) -> dict:
    salt = secrets.token_hex(12)
    token = signing.dumps(
        {"w": website.public_key, "s": salt, "t": int(time.time())}, salt=SALT, compress=True
    )
    return {"token": token, "salt": salt, "difficulty": DIFFICULTY, "algorithm": "SHA-256"}


def _leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        return bits + (8 - byte.bit_length())
    return bits


def solve(salt: str, difficulty: int = DIFFICULTY) -> int:
    """Löst die Aufgabe (für Tests und als Vorlage für die Webseite)."""
    nonce = 0
    while _leading_zero_bits(hashlib.sha256(f"{salt}{nonce}".encode()).digest()) < difficulty:
        nonce += 1
    return nonce


class Rejected(Exception):
    """Formular abgelehnt; ``status`` ist der HTTP-Status für die Webseite."""

    def __init__(self, message: str, status: int = 400, code: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        # Für die Webseite: „expired“ = neue Aufgabe holen und erneut senden,
        # „used“ = diese Nachricht ist schon angekommen (UX-Audit 31.10. S03)
        self.code = code


EXPIRED = "Das Formular ist abgelaufen. Bitte die Seite neu laden."
USED = "Dieses Formular wurde schon abgeschickt. Bitte die Seite neu laden."
BUSY = "Die Nachricht wird gerade verarbeitet. Bitte in zwei Minuten noch einmal absenden."
# Solange gilt eine Aufgabe als „in Arbeit“; bricht die Verarbeitung ab, ist sie danach
# wieder frei (Audit 31.10. R-CL-02: „used“ erst nach haltbarer Annahme)
PENDING_SECONDS = 120
DONE = "done"


def check_challenge(
    website, token: str, nonce, now: float | None = None, consume: bool = True
) -> str:
    """Prüft die Aufgabe; gibt ihr Salz zurück. consume=False: noch nicht verbrauchen."""
    now = now or time.time()
    try:
        data = signing.loads(token or "", salt=SALT, max_age=MAX_SECONDS)
    except signing.BadSignature as exc:
        raise Rejected(EXPIRED, code="expired") from exc
    if data.get("w") != website.public_key:
        raise Rejected("Das Formular gehört zu einer anderen Webseite.")
    if now - data.get("t", 0) > MAX_SECONDS:
        raise Rejected(EXPIRED, code="expired")
    if now - data.get("t", 0) < MIN_SECONDS:
        raise Rejected("Das ging zu schnell. Bitte noch einmal absenden.", code="too_fast")
    digest = hashlib.sha256(f"{data['s']}{nonce}".encode()).digest()
    if _leading_zero_bits(digest) < DIFFICULTY:
        raise Rejected(
            "Die Sicherheitsprüfung ist fehlgeschlagen. Bitte die Seite neu laden.", code="expired"
        )
    _raise_if_taken(cache.get(f"website:pow:{data['s']}"))
    if consume:
        consume_challenge(data["s"])
    return data["s"]


def _raise_if_taken(state) -> None:
    if state == "pending":
        raise Rejected(BUSY, 409, code="busy")
    if state:
        raise Rejected(USED, code="used")


def consume_challenge(salt: str) -> None:
    """Aufgabe vorläufig belegen; als verbraucht gilt sie erst nach ``finish_challenge``."""
    if not cache.add(f"website:pow:{salt}", "pending", PENDING_SECONDS):
        _raise_if_taken(cache.get(f"website:pow:{salt}") or "pending")


def finish_challenge(salt: str) -> None:
    cache.set(f"website:pow:{salt}", DONE, MAX_SECONDS)


def release_challenge(salt: str) -> None:
    cache.delete(f"website:pow:{salt}")


def suspicious(subject: str, body: str, email: str) -> str:
    """Grund, warum eine Nachricht zurückgehalten wird (leer = unauffällig)."""
    text = f"{subject}\n{body}".lower()
    links = len(re.findall(r"https?://|www\.", text))
    if links > MAX_LINKS:
        return f"enthält {links} Links"
    found = SPAM_PATTERN.search(text)
    if found:
        return f"enthält „{found.group(1)}“"
    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if FOREIGN.match(c)) >= FOREIGN_SHARE * len(letters):
        return "überwiegend kyrillische oder ostasiatische Schrift"
    if re.search(r"<a\s|\[url=", text):
        return "enthält HTML- oder Forenlinks"
    fingerprint = hashlib.sha256(re.sub(r"\s+", " ", body.strip().lower()).encode()).hexdigest()
    if not cache.add(f"website:msg:{fingerprint}", 1, 24 * 60 * 60):
        return "gleiche Nachricht wurde schon einmal geschickt"
    return ""


def deliver(website, recipient_name: str, emails: list[str], data: dict) -> bool:
    org = website.organization
    body = (
        f"Nachricht über das Kontaktformular der Webseite von {org.name}\n"
        f"An: {recipient_name}\n"
        f"Von: {data['name']} <{data['email']}>\n\n"
        f"{data['message']}\n\n"
        "Antworten geht direkt an den Absender (Antwort-an)."
    )
    return send(
        emails,
        f"Webseite: {data['subject']}",
        body,
        organization=org,
        kind=KIND,
        reply_to=[data["email"]],
        fail_silently=True,
    )


def copy_to_sender(website, recipient_name: str, data: dict) -> None:
    org = website.organization
    body = (
        f"Hallo {data['name']},\n\ndeine Nachricht an {recipient_name} ({org.name}) ist "
        f"angekommen. Zur Erinnerung dein Text:\n\n{data['message']}\n"
    )
    send(
        [data["email"]],
        f"Deine Nachricht an {org.name}",
        body,
        organization=org,
        kind=KIND,
        fail_silently=True,
    )


def submit(view, ip: str, data: dict) -> str:
    """Nimmt eine Formularnachricht an. Gibt „sent“, „held“ oder „dropped“ zurück."""
    website = view.site
    if data.get("homepage"):
        return "dropped"  # Honigtopf: still verwerfen, der Bot erfährt nichts
    # Erst verbrauchen, wenn die Nachricht angenommen wird: Nach einem Fehler davor
    # (z. B. Empfänger fehlt) sendet das Formular mit derselben Aufgabe erneut (W-V01)
    salt = check_challenge(website, data.get("challenge", ""), data.get("nonce"), consume=False)
    if too_many(f"website:contact:ip:{ip}", IP_LIMIT, 60 * 60):
        raise Rejected("Zu viele Nachrichten. Bitte später noch einmal versuchen.", 429)
    target = view.resolve_recipient(data.get("recipient", ""))
    if target is None:
        raise Rejected("Bitte einen Empfänger wählen.")
    consume_challenge(salt)
    try:
        result = _accept(website, target, data)
    except BaseException:
        release_challenge(salt)
        raise
    # „Schon abgeschickt“ erst, wenn die Nachricht gespeichert bzw. übergeben ist
    transaction.on_commit(lambda: finish_challenge(salt))
    return result


def _accept(website, target, data: dict) -> str:
    recipient_name, emails = target
    reason = suspicious(data["subject"], data["message"], data["email"])
    if not reason and too_many(
        f"website:contact:site:{website.pk}", website.contact_limit_per_hour, 60 * 60
    ):
        reason = "Obergrenze an Formularmails je Stunde erreicht"
    if reason:
        hold(website, recipient_name, data, reason)
        return "held"
    if not deliver(website, recipient_name, emails, data):
        # Versand gescheitert: nichts bestätigen, die Nachricht bleibt zur Freigabe liegen
        hold(website, recipient_name, data, HOLD_FAILED)
        return "held"
    if data.get("copy"):
        copy_to_sender(website, recipient_name, data)
    return "sent"


HOLD_FAILED = "Zustellung gescheitert, bitte erneut freigeben"


def hold(website, recipient_name: str, data: dict, reason: str) -> None:
    HeldMessage.objects.create(
        organization=website.organization,
        website=website,
        recipient=data["recipient"],
        recipient_name=recipient_name,
        sender_name=data["name"],
        sender_email=data["email"],
        subject=data["subject"],
        body=data["message"],
        reason=reason,
    )


def purge_held(now: datetime.datetime | None = None) -> int:
    from core.tenancy import rls_bypass

    cutoff = (now or timezone.now()) - datetime.timedelta(days=HELD_DAYS)
    with rls_bypass():
        count, _ = HeldMessage.objects.filter(created_at__lt=cutoff).delete()
    return count
