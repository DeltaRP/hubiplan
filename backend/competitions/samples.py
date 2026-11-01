"""Bestätigte Spiegelausschnitte sammeln (Schießscheiben Schritt 6).

Es gibt keine ausgewerteten echten Scheiben, mit denen sich die Fotoerkennung prüfen ließe.
Deshalb kann ein Verein erlauben, dass HUBIplan im Betrieb bestätigte Spiegel sammelt (Ralf
01.11.2026: „Ja, mit Einwilligung je Verein“):

- standardmäßig aus; wer Wettbewerbe verwalten darf, schaltet es für den Verein ein oder aus;
- beim Foto wird je Spiegel der entzerrte Ausschnitt kurz im Cache gehalten (``TTL``) und
  nur ein Schlüssel an das Gerät gegeben;
- erst wenn die Treffer bestätigt gespeichert werden, kommt der Ausschnitt mit den
  bestätigten und den erkannten Treffern in ``PhotoSample``, ohne Starter, Wettbewerb,
  Uhrzeit oder Namen;
- der Verein kann alle gesammelten Ausschnitte jederzeit löschen; Ausschalten löscht nichts.
"""

from __future__ import annotations

import secrets
from decimal import Decimal

from django.core.cache import cache

from . import targets
from .models import PhotoSample, PhotoSampleConsent, Scoring

TTL = 12 * 3600  # Standmodus kann offline sein; danach verfällt der Ausschnitt einfach
MAX_PER_SAVE = 5  # höchstens so viele Spiegel je Karte
PREFIX = "spiegelausschnitt:"


def enabled(org) -> bool:
    return PhotoSampleConsent.objects.filter(organization=org, enabled=True).exists()


def keep(org, scoring: Scoring, target: targets.Target, found, px_per_mm: float) -> list[dict]:
    """Ausschnitte einer Erkennung bereitlegen; zurück ``[{key, spot}]`` für das Gerät."""
    out = []
    for n, crop in enumerate(found.crops, start=1):
        spot = n if found.spots else None
        mine = [
            [float(x), float(y)]
            for (x, y), s in zip(found.hits, found.spots or [None] * len(found.hits), strict=True)
            if s == spot
        ]
        key = secrets.token_urlsafe(18)
        cache.set(
            PREFIX + key,
            {
                "org": org.pk,
                "scoring": scoring.pk,
                "spot": spot,
                "target": scoring.target,
                "target_data": target.as_dict(),
                "px_per_mm": px_per_mm,
                "image": crop,
                "detected": mine,
            },
            TTL,
        )
        out.append({"key": key, "spot": spot})
    return out


def store(org, scoring: Scoring, keys, hits: list[dict]) -> int:
    """Nach dem Bestätigen: bereitgelegte Ausschnitte mit den bestätigten Treffern speichern.

    Ungültige oder verfallene Schlüssel werden still übergangen; das Speichern der Treffer
    hängt nie davon ab. Zurück: Zahl der gespeicherten Ausschnitte."""
    if not isinstance(keys, list) or not keys or not enabled(org):
        return 0
    saved = 0
    for key in keys[:MAX_PER_SAVE]:
        if not isinstance(key, str) or not 10 <= len(key) <= 64:
            continue
        entry = cache.get(PREFIX + key)
        if not entry or entry["org"] != org.pk or entry["scoring"] != scoring.pk:
            continue
        cache.delete(PREFIX + key)
        spot = entry["spot"]
        confirmed = [
            [float(h["x"]), float(h["y"])] for h in hits if spot is None or h.get("spot") == spot
        ]
        PhotoSample.objects.create(
            organization=org,
            target=entry["target"],
            target_data=entry["target_data"],
            image=entry["image"],
            px_per_mm=Decimal(str(entry["px_per_mm"])),
            hits=confirmed,
            detected=entry["detected"],
        )
        saved += 1
    return saved
