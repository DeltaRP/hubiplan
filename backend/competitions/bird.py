"""Vogelschießen (Konzept Abschnitt 5b): Pfänder, Losnummern, Schüsse, Ausscheiden.

Die Reihenfolge rechnet ``shooting_order``/``next_after`` ohne Datenbank; der Standmodus
rechnet dieselbe Regel auf dem Gerät nach (frontend/src/api/bird.ts), damit es auch ohne
Empfang weitergeht:

- In der Reihenfolge stehen alle Starter mit Losnummer, aufsteigend, ohne die, die fehlen
  oder sich zurückgezogen haben, und (wenn „scheidet aus“ gilt) ohne die mit einem Pfand.
- Dran ist, wer nach dem Schützen des letzten Schusses die nächsthöhere Nummer hat; nach der
  höchsten Nummer beginnt eine neue Runde.
"""

from __future__ import annotations

import datetime
import random
import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.log import diff, record, snapshot

from .models import Competition, Presence, Prize, Shot, Starter

PRIZE_TEMPLATE = ["Kopf", "linker Flügel", "rechter Flügel", "Schweif", "Rumpf"]


def lot(number: str) -> int | None:
    """Losnummer als Zahl (Startnummern sind sonst freier Text)."""
    text = (number or "").strip()
    return int(text) if text.isdigit() and 0 < int(text) < 100000 else None


@dataclass(frozen=True)
class Slot:
    starter: int
    number: int


def shooting_order(starters, winners: set[int], drop_out: bool) -> list[Slot]:
    slots = []
    for s in starters:
        n = lot(s.number)
        if n is None or s.presence:
            continue
        if drop_out and s.pk in winners:
            continue
        slots.append(Slot(s.pk, n))
    return sorted(slots, key=lambda x: (x.number, x.starter))


def next_after(order: list[Slot], last_number: int | None) -> int | None:
    """Index des nächsten Schützen nach der Losnummer ``last_number``."""
    if not order:
        return None
    if last_number is None:
        return 0
    for i, slot in enumerate(order):
        if slot.number > last_number:
            return i
    return 0


def rounds(numbers: list[int | None]) -> int:
    """Runden: eine neue beginnt, wenn die Losnummer nicht größer ist als beim Schuss davor."""
    count, prev = 0, None
    for n in numbers:
        if n is None:
            continue
        if prev is None or n <= prev:
            count += 1
        prev = n
    return count


def draw_report(starters) -> dict:
    """Doppelte Nummern, Lücken und Starter ohne Nummer."""
    seen: dict[int, list[str]] = {}
    missing = []
    for s in starters:
        if s.presence == Presence.WITHDRAWN:
            continue
        n = lot(s.number)
        if n is None:
            missing.append(s.name)
        else:
            seen.setdefault(n, []).append(s.name)
    top = max(seen) if seen else 0
    return {
        "missing": sorted(missing),
        "duplicates": [
            {"number": n, "names": names} for n, names in sorted(seen.items()) if len(names) > 1
        ],
        "gaps": [n for n in range(1, top + 1) if n not in seen],
    }


# --- Zustand für Standmodus und Auswertung ---


def _prize_data(p: Prize, units: dict[int, str]) -> dict:
    w = p.winner
    return {
        "id": p.pk,
        "name": p.name,
        "sort_order": p.sort_order,
        "award": p.award,
        "fallen": p.fallen,
        "winner": p.winner_id,
        "winner_name": (w.name if w else p.winner_name),
        "unit_name": (units.get(w.unit_id, "") if w and w.unit_id else ""),
        "club": w.club if w else "",
        "number": w.number if w else "",
        "shot_number": p.shot_number,
        "shots_for": p.shots_for,
        "live": p.shot_id is not None,
        "fallen_at": p.fallen_at.isoformat() if p.fallen_at else None,
    }


def state(comp: Competition) -> dict:
    """Alles, was der Standmodus und die Auswertung zum Vogelschießen brauchen."""
    starters = list(comp.starters.select_related("unit"))
    units = {s.unit_id: s.unit.name for s in starters if s.unit_id}
    prizes = list(comp.prizes.select_related("winner"))
    winners = {p.winner_id for p in prizes if p.winner_id}
    order = shooting_order(starters, winners, comp.drop_out)
    shots = list(comp.shots.all())
    by_id = {s.pk: s for s in starters}
    last = shots[-1] if shots else None
    last_starter = by_id.get(last.starter_id) if last else None
    current = next_after(order, lot(last_starter.number) if last_starter else None)
    upcoming = []
    if current is not None:
        for k in range(min(4, len(order))):
            upcoming.append(order[(current + k) % len(order)].starter)
    fallen_numbers = [p.shot_number for p in prizes if p.shot_number]
    count = len(shots) if shots else (comp.total_shots or 0)
    since = count - max(fallen_numbers) if fallen_numbers else count
    numbers_by_starter = {s.pk: lot(s.number) for s in starters}
    duration = None
    if len(shots) > 1:
        duration = int((shots[-1].at - shots[0].at).total_seconds() // 60)
    per_unit: dict[str, int] = {}
    for p in prizes:
        if p.winner_id and p.winner and p.winner.unit_id:
            name = units.get(p.winner.unit_id, "")
            per_unit[name] = per_unit.get(name, 0) + 1
        elif p.fallen:
            key = (p.winner.club if p.winner else "") or "Gäste"
            per_unit[key] = per_unit.get(key, 0) + 1
    return {
        "prizes": [_prize_data(p, units) for p in prizes],
        "order": [s.starter for s in order],
        "upcoming": upcoming,
        "shots": count,
        "live_shots": len(shots),
        "since_last": max(since, 0),
        "round": rounds([numbers_by_starter.get(s.starter_id) for s in shots]) if shots else 0,
        "last": (
            {
                "number": last.number,
                "starter": last.starter_id,
                "name": last.name,
                "client_key": str(last.client_key) if last.client_key else None,
                "hits": [p.pk for p in prizes if p.shot_id == last.pk],
            }
            if last
            else None
        ),
        # die letzten Schüsse: damit der Standmodus ohne Netz rechnen und zurücknehmen kann
        "recent": [
            {
                "number": x.number,
                "starter": x.starter_id,
                "client_key": str(x.client_key) if x.client_key else None,
            }
            for x in shots[-50:]
        ],
        "draw": draw_report(starters),
        "stats": {
            "shots": count,
            "starters": len([s for s in starters if s.presence != Presence.WITHDRAWN]),
            "members": len([s for s in starters if s.membership_id]),
            "guests": len([s for s in starters if not s.membership_id]),
            "rounds": rounds([numbers_by_starter.get(s.starter_id) for s in shots])
            if shots
            else None,
            "duration_minutes": duration,
            "started": shots[0].at.isoformat() if shots else None,
            "per_unit": [{"name": k, "count": v} for k, v in sorted(per_unit.items())],
        },
    }


# --- Schreiben ---


def _open(comp: Competition) -> None:
    if comp.status == Competition.Status.FINAL:
        raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")
    if comp.form != Competition.Form.BIRD:
        raise ValidationError("Das ist kein Vogelschießen.")


def _running(comp: Competition) -> None:
    if comp.status == Competition.Status.PREPARATION:
        comp.status = Competition.Status.RUNNING
        comp.save(update_fields=["status", "updated_at"])


def _previous_fallen(comp: Competition, number: int, exclude: set[int]) -> int:
    m = (
        comp.prizes.filter(shot_number__lt=number)
        .exclude(pk__in=exclude)
        .aggregate(m=Max("shot_number"))["m"]
    )
    return m or 0


@transaction.atomic
def fire(org, user, comp: Competition, starter: Starter, hits: list, at=None, client_key=None):
    """Einen Schuss zählen; ``hits``: Nummern der Pfänder, die damit gefallen sind.
    Mit ``client_key`` kommt ein zweites Senden (Offline-Abgleich) nicht doppelt an."""
    _open(comp)
    Competition.objects.select_for_update().filter(pk=comp.pk).first()
    if client_key:
        same = comp.shots.filter(client_key=client_key).first()
        if same:
            return same
    hit_ids = {int(h) for h in (hits or [])}
    prizes = list(comp.prizes.select_for_update().filter(pk__in=hit_ids))
    if len(prizes) != len(hit_ids):
        raise ValidationError({"hits": "Unbekanntes Pfand."})
    for p in prizes:
        if p.fallen:
            raise ValidationError({"hits": f"{p.name} ist schon gefallen."})
    if comp.fixed_order and prizes:
        hanging = [p for p in comp.prizes.all() if not p.fallen]
        allowed = {p.pk for p in hanging[: len(prizes)]}
        if hit_ids != allowed:
            raise ValidationError(
                {"hits": f"Es gilt die feste Reihenfolge, als Nächstes fällt {hanging[0].name}."}
            )
    if comp.drop_out and starter.prizes.exists():
        raise ValidationError(
            {"starter": f"{starter.name} hat schon ein Pfand und ist ausgeschieden."}
        )
    number = (comp.shots.aggregate(m=Max("number"))["m"] or 0) + 1
    when = at or timezone.now()
    try:
        with transaction.atomic():
            shot = Shot.objects.create(
                organization=org,
                competition=comp,
                number=number,
                starter=starter,
                name=starter.name,
                at=when,
                client_key=client_key,
            )
    except IntegrityError as exc:
        raise ValidationError("Gleichzeitig ein anderer Schuss, bitte noch einmal.") from exc
    if prizes:
        before = _previous_fallen(comp, number, hit_ids)
        for p in prizes:
            old = snapshot(p)
            p.winner = starter
            p.winner_name = starter.name
            p.shot_number = number
            p.shots_for = number - before
            p.shot = shot
            p.fallen_at = when
            p.save()
            record(org, user, "update", p, diff(old, snapshot(p)))
    _running(comp)
    return shot


@transaction.atomic
def undo(org, user, comp: Competition, client_key=None) -> Shot | None:
    """Den letzten Schuss zurücknehmen (mit gefallenen Pfändern). ``client_key``: nur
    diesen Schuss; ist er schon weg, passiert nichts."""
    _open(comp)
    Competition.objects.select_for_update().filter(pk=comp.pk).first()
    last = comp.shots.order_by("-number").first()
    if client_key:
        target = comp.shots.filter(client_key=client_key).first()
        if target is None:
            return None
        if last is None or target.pk != last.pk:
            raise ValidationError("Nur der letzte Schuss lässt sich zurücknehmen.")
    if last is None:
        raise ValidationError("Es gibt keinen Schuss zum Zurücknehmen.")
    for p in comp.prizes.filter(shot=last):
        old = snapshot(p)
        _clear(p)
        record(org, user, "update", p, diff(old, snapshot(p)))
    record(org, user, "delete", last, {"Schuss": [f"Nr. {last.number}: {last.name}", None]})
    last.delete()
    return last


def _clear(p: Prize) -> None:
    p.winner = None
    p.winner_name = ""
    p.shot_number = None
    p.shots_for = None
    p.shot = None
    p.fallen_at = None
    p.save()


def _positive(raw, field: str) -> int | None:
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ValidationError({field: "Bitte eine ganze Zahl eingeben."}) from exc
    if value < 1 or value > 1000000:
        raise ValidationError({field: "Bitte eine Zahl ab 1 eingeben."})
    return value


@transaction.atomic
def set_result(org, user, prize: Prize, data) -> Prize:
    """Nachträglich erfassen: wer, mit dem wievielten Schuss gesamt, Schüsse für das Pfand."""
    comp = prize.competition
    _open(comp)
    old = snapshot(prize)
    if "winner" in data:
        if data["winner"] in (None, "", 0):
            _clear(prize)
            record(org, user, "update", prize, diff(old, snapshot(prize)))
            return prize
        starter = Starter.objects.filter(competition=comp, pk=data["winner"]).first()
        if starter is None:
            raise ValidationError({"winner": "Unbekannter Schütze."})
        prize.winner = starter
        prize.winner_name = starter.name
        prize.shot = None
        if prize.fallen_at is None:
            prize.fallen_at = timezone.now()
    for field in ("shot_number", "shots_for"):
        if field in data:
            setattr(prize, field, _positive(data[field], field))
            prize.shot = None
    if "shot_number" in data and "shots_for" not in data and prize.shot_number:
        before = _previous_fallen(comp, prize.shot_number, {prize.pk})
        prize.shots_for = prize.shot_number - before
    prize.save()
    changes = diff(old, snapshot(prize))
    if changes:
        record(org, user, "update", prize, changes)
    _running(comp)
    return prize


def _taken(comp: Competition, exclude: int | None = None) -> dict[int, Starter]:
    out = {}
    for s in comp.starters.exclude(pk=exclude):
        n = lot(s.number)
        if n is not None:
            out[n] = s
    return out


def _free(comp: Competition, taken: dict[int, Starter]) -> list[int]:
    count = comp.starters.exclude(presence=Presence.WITHDRAWN).count()
    top = max([count, *taken.keys()]) if taken else count
    free = [n for n in range(1, top + 1) if n not in taken]
    return free or [top + 1]


@transaction.atomic
def draw(org, user, comp: Competition, starter: Starter, number=None, how: str = "hut"):
    """Losnummer: ``number`` aus dem Hut eintragen oder (ohne) digital eine freie ziehen.
    Zurück: (Nummer, Hinweis); Hinweis, wenn eine digital gezogene Nummer vom Gerät
    inzwischen vergeben war und neu gezogen wurde."""
    _open(comp)
    Competition.objects.select_for_update().filter(pk=comp.pk).first()
    taken = _taken(comp, exclude=starter.pk)
    note = ""
    n = _positive(number, "number") if number not in (None, "") else None
    if n is not None and n in taken:
        if how != "digital":
            raise ValidationError({"number": f"Nummer {n} hat schon {taken[n].name}."})
        note = f"Nummer {n} war schon vergeben, neu gezogen."
        n = None
    if n is None:
        how = "digital" if how != "alle" else how
        n = random.SystemRandom().choice(_free(comp, taken))
    old = snapshot(starter)
    starter.number = str(n)
    starter.drawn_how = how if how in ("hut", "digital", "alle") else "hut"
    starter.drawn_at = timezone.now()
    starter.save()
    record(org, user, "update", starter, diff(old, snapshot(starter)))
    return n, note


@transaction.atomic
def draw_all(org, user, comp: Competition) -> int:
    """Alle ohne Losnummer auf einmal auslosen (für Wettbewerbe ohne Zeremonie)."""
    _open(comp)
    Competition.objects.select_for_update().filter(pk=comp.pk).first()
    without = [
        s for s in comp.starters.exclude(presence=Presence.WITHDRAWN) if lot(s.number) is None
    ]
    rng = random.SystemRandom()
    rng.shuffle(without)
    taken = _taken(comp)
    free = [n for n in _free(comp, taken) if n not in taken]
    top = max([*taken.keys(), *free, 0])
    while len(free) < len(without):
        top += 1
        free.append(top)
    free = free[: len(without)]
    rng.shuffle(free)
    now = timezone.now()
    for s, n in zip(without, free, strict=True):
        old = snapshot(s)
        s.number = str(n)
        s.drawn_how = "alle"
        s.drawn_at = now
        s.save()
        record(org, user, "update", s, diff(old, snapshot(s)))
    return len(without)


def create_template(org, comp: Competition, names=None) -> None:
    for i, name in enumerate(names or PRIZE_TEMPLATE, start=1):
        Prize.objects.create(organization=org, competition=comp, name=name, sort_order=i)


def parse_key(raw):
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise ValidationError({"client_key": "Ungültige Kennung."}) from exc


def parse_at(raw) -> datetime.datetime | None:
    from django.utils.dateparse import parse_datetime

    if not raw:
        return None
    at = parse_datetime(str(raw))
    if at is None:
        return None
    if timezone.is_naive(at):
        at = timezone.make_aware(at)
    # Uhr des Geräts: nicht in der Zukunft
    return min(at, timezone.now())
