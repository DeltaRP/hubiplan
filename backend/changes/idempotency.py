"""Doppelt gesendete Anfragen nur einmal ausführen (Kopfzeile ``Idempotency-Key``).

Verwendung in einer Ansicht, innerhalb ihrer Transaktion::

    claim = idempotency.claim(request, "billing.payment")
    if claim.done:
        return ...  # Ergebnis aus claim.result
    ...             # eigentliche Arbeit
    claim.remember({"id": obj.pk})

Der Schlüssel wird in derselben Transaktion gespeichert wie die Arbeit: Schlägt sie
fehl, ist er wieder frei. Kommt dieselbe Anfrage gleichzeitig zweimal, wartet die
zweite an der Eindeutigkeit des Schlüssels, bis die erste fertig ist.

Zum Schlüssel wird eine Prüfsumme der Angaben gespeichert. Kommt derselbe Schlüssel mit
anderen Angaben (z. B. nach Verbindungsabbruch einen anderen Betrag eingetragen), wird
die Anfrage mit 409 abgewiesen statt stillschweigend das alte Ergebnis zu melden.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from .models import RequestKey

HEADER = "Idempotency-Key"
KEEP = datetime.timedelta(days=2)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Diese Anfrage wurde schon mit anderen Angaben gesendet und ausgeführt. "
        "Bitte die Seite neu laden und den aktuellen Stand prüfen."
    )
    default_code = "conflict"


def fingerprint(request) -> str:
    """Prüfsumme der gesendeten Angaben (Pfad und Inhalt)."""
    try:
        data = request.data
        if hasattr(data, "lists"):
            data = {k: v for k, v in data.lists()}
        body = json.dumps(data, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 – ohne lesbaren Inhalt nur der Pfad
        body = ""
    raw = f"{request.method} {request.path}\n{body}".encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass
class Claim:
    key: RequestKey | None = None
    done: bool = False
    result: dict = field(default_factory=dict)

    def remember(self, result: dict) -> None:
        if self.key is not None:
            self.key.result = result
            self.key.save(update_fields=["result"])


def claim(request, scope: str, *, required: bool = False) -> Claim:
    """``required``: ohne Schlüssel abweisen (z. B. Zahlungen, die sonst doppelt buchten)."""
    raw = (request.headers.get(HEADER) or "").strip()
    if not raw:
        if required:
            raise ValidationError(
                f"Die Kopfzeile {HEADER} fehlt (Schutz gegen doppeltes Buchen). "
                "Bitte die Seite neu laden und erneut senden."
            )
        return Claim()
    try:
        key = uuid.UUID(raw)
    except ValueError as exc:
        raise ValidationError(f"Ungültige Kopfzeile {HEADER}.") from exc
    digest = fingerprint(request)
    RequestKey.objects.filter(created_at__lt=timezone.now() - KEEP).delete()
    try:
        with transaction.atomic():
            obj = RequestKey.objects.create(
                key=key, user=request.user, scope=scope, fingerprint=digest
            )
    except IntegrityError:
        old = RequestKey.objects.filter(key=key, user=request.user, scope=scope).first()
        if old is None:
            msg = f"Die Kopfzeile {HEADER} passt nicht zu dieser Anfrage."
            raise ValidationError(msg) from None
        if old.fingerprint and old.fingerprint != digest:
            raise Conflict() from None
        return Claim(done=True, result=old.result)
    return Claim(key=obj)
