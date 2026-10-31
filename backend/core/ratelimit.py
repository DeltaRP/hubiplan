"""Einfache Begrenzung von Aufrufen (z. B. Anmeldelinks, Foto-Uploads).

Der Zähler steigt atomar im Cache (Redis: INCR), damit parallele Anfragen nicht
denselben alten Stand lesen.
"""

from __future__ import annotations

from django.core.cache import cache


def client_ip(request) -> str:
    """Adresse des Aufrufers.

    Vor dem Backend steht genau ein Proxy (Caddy); er setzt X-Forwarded-For neu
    und ignoriert, was der Aufrufer selbst mitschickt. Genommen wird der letzte
    Eintrag, also der, den Caddy angehängt hat.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    return parts[-1] if parts else request.META.get("REMOTE_ADDR", "")


def too_many(key: str, limit: int, window: int) -> bool:
    """Zählt einen Aufruf; True, wenn im Zeitfenster mehr als ``limit`` waren."""
    if cache.add(key, 1, window):
        return limit < 1
    try:
        count = cache.incr(key)
    except ValueError:  # gerade abgelaufen
        cache.add(key, 1, window)
        count = 1
    return count > limit
