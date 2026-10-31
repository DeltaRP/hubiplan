"""Obergrenzen für aufwendige Hintergrund-Jobs je Organisation (Gesamtaudit 30.10., B-V03).

Exporte und Importe sind teuer (Arbeitsspeicher, Dateien, Warteschlange). Ein einzelnes
(auch übernommenes) Konto soll die Instanz damit nicht auslasten können.
"""

from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.exceptions import Throttled


def ensure_capacity(qs, *, active_statuses, max_active: int, max_per_hour: int, what: str):
    """Fehler 429, wenn zu viele Jobs laufen oder in der letzten Stunde begonnen wurden.

    ``qs``: Jobs dieser Organisation (und Art).
    """
    if qs.filter(status__in=active_statuses).count() >= max_active:
        raise Throttled(
            detail=f"Es laufen schon {max_active} {what}. Bitte warten, bis einer fertig ist."
        )
    since = timezone.now() - datetime.timedelta(hours=1)
    if qs.filter(created_at__gte=since).count() >= max_per_hour:
        raise Throttled(
            detail=f"In der letzten Stunde wurden schon {max_per_hour} {what} begonnen. "
            "Bitte später erneut versuchen."
        )
