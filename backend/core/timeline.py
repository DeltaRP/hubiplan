"""Zeitraster für Auswertungen über die Zeit (Mitglieder- und Finanzentwicklung).

Der Zeitraum kommt als ``von``/``bis`` (``JJJJ-MM`` oder ``JJJJ-MM-TT``) und
``raster`` (``monat`` oder ``jahr``). Standard: die letzten zwölf Monate.
``von=alles`` beginnt bei den ältesten Daten. Der Zeitraum endet nie nach heute.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework import serializers

MONTHS = [
    "Jan.",
    "Feb.",
    "März",
    "Apr.",
    "Mai",
    "Juni",
    "Juli",
    "Aug.",
    "Sept.",
    "Okt.",
    "Nov.",
    "Dez.",
]
MONTH = "monat"
YEAR = "jahr"
MAX_MONTHS = 240
MAX_YEARS = 200
ONE_DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class Bucket:
    start: datetime.date
    end: datetime.date  # letzter Tag (einschließlich)
    label: str

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "label": self.label}


@dataclass(frozen=True)
class Timeline:
    start: datetime.date
    end: datetime.date
    raster: str
    buckets: list[Bucket]

    def as_dict(self) -> dict:
        return {"von": self.start, "bis": self.end, "raster": self.raster}


def _parse(value: str, field: str, *, end: bool) -> datetime.date:
    value = value.strip()
    try:
        if len(value) == 7:
            day = datetime.date.fromisoformat(f"{value}-01")
            return day + relativedelta(months=1) - ONE_DAY if end else day
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise serializers.ValidationError({field: "Bitte ein gültiges Datum angeben."}) from exc


def _month_start(day: datetime.date) -> datetime.date:
    return day.replace(day=1)


def build(params, *, earliest: datetime.date | None, year_start=None, year_label=None) -> Timeline:
    """Zeitraster aus den Abfrageparametern.

    ``year_start(jahr) -> Datum`` und ``year_label(jahr) -> Text`` legen fest, was
    ein Jahr ist (Kalenderjahr oder Geschäftsjahr); ``earliest`` ist der Beginn
    der Daten (für ``von=alles``).
    """
    year_start = year_start or (lambda y: datetime.date(y, 1, 1))
    year_label = year_label or str
    today = timezone.localdate()

    raw_from = (params.get("von") or "").strip()
    raw_until = (params.get("bis") or "").strip()
    end = _parse(raw_until, "bis", end=True) if raw_until else today
    end = min(end, today)
    if raw_from == "alles":
        start = earliest or _month_start(end)
    elif raw_from:
        start = _parse(raw_from, "von", end=False)
    else:
        start = _month_start(end) - relativedelta(months=11)
    if raw_from and raw_from != "alles" and start > end:
        # Nicht still umdeuten: ein umgedrehter Zeitraum ist ein Eingabefehler
        raise serializers.ValidationError({"bis": "Das Ende liegt vor dem Beginn."})
    start = min(start, end)
    if end < start:
        raise serializers.ValidationError({"bis": "Das Ende liegt vor dem Beginn."})

    months = (end.year - start.year) * 12 + end.month - start.month + 1
    raster = params.get("raster") or (MONTH if months <= 36 else YEAR)
    if raster not in (MONTH, YEAR):
        raise serializers.ValidationError({"raster": "Bitte Monat oder Jahr wählen."})

    buckets: list[Bucket] = []
    if raster == MONTH:
        if months > MAX_MONTHS:
            raise serializers.ValidationError(
                {"raster": "Zu viele Monate. Bitte einen kürzeren Zeitraum oder Jahre wählen."}
            )
        start = _month_start(start)
        day = start
        while day <= end:
            nxt = day + relativedelta(months=1)
            buckets.append(
                Bucket(day, min(nxt - ONE_DAY, end), f"{MONTHS[day.month - 1]} {day.year}")
            )
            day = nxt
    else:
        year = start.year if start >= year_start(start.year) else start.year - 1
        start = year_start(year)
        while year_start(year) <= end:
            if len(buckets) >= MAX_YEARS:
                raise serializers.ValidationError({"von": "Der Zeitraum ist zu lang."})
            last = min(year_start(year + 1) - ONE_DAY, end)
            buckets.append(Bucket(year_start(year), last, year_label(year)))
            year += 1
    return Timeline(start=start, end=end, raster=raster, buckets=buckets)
