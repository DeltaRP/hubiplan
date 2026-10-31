"""Datenpakete, die über eine Kopplung fließen dürfen.

Jedes Paket ist ein **Stand** (Schnappschuss): Die Absenderin baut ihn aus ihren
eigenen Daten, die Empfängerin ersetzt damit ihre Kopie. Weil jedes Datum nur
eine Heimat hat, gibt es keine Konflikte. Ob sich ein Stand geändert hat,
zeigt seine Prüfsumme.

Die Heimat der Daten entscheidet über die Freigabe (``Coupling.packets``). Was
nicht freigegeben ist, wird nicht gebaut und nicht gesendet; nimmt die
Freigabe weg, schickt die Absenderin einen leeren Stand, und die Empfängerin
löscht ihre Kopie.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from .models import Coupling

UP = "up"  # von der unteren an die obere Einheit
DOWN = "down"  # von der oberen an die untere Einheit
BOTH = (UP, DOWN)


@dataclass(frozen=True)
class Packet:
    key: str
    label: str
    directions: tuple[str, ...]
    # Stufen: (wert, beschriftung); erste Stufe nach "aus" ist die kleinste
    levels: tuple[tuple[str, str], ...] = (("on", "an"),)
    personal: str = ""  # Hinweis auf Personenbezug für die Datenflussübersicht
    default: str | None = None  # Vorbelegung beim Koppeln (None = aus)
    build: Callable | None = None  # (coupling, level) -> dict
    apply: Callable | None = None  # (coupling, data) -> None
    persons: Callable | None = None  # (data) -> int
    # Auch zwischen einem Verein und seiner fernen Untereinheit (Schritt 8)?
    under_club: bool = False
    # Nur zwischen einem Verein und seiner fernen Untereinheit (Schritt 8d)
    only_club: bool = False


REGISTRY: dict[str, Packet] = {}


def register(packet: Packet) -> Packet:
    REGISTRY[packet.key] = packet
    return packet


def direction_of(coupling: Coupling) -> str:
    """Richtung, in die diese Seite sendet."""
    return DOWN if coupling.direction == Coupling.Direction.CHILD else UP


CLUB = "club"
FEDERATION = "federation"


def upper_kind(coupling: Coupling) -> str:
    """Art der oberen Seite: Dachverband (bisher) oder Verein mit ferner Untereinheit.

    Die obere Seite kennt ihre eigene Art; die untere hat sie aus dem Kopplungscode."""
    if coupling.direction == Coupling.Direction.CHILD:
        unit = coupling.local_unit if coupling.local_unit_id else None
        return CLUB if unit is not None and unit.type == CLUB else FEDERATION
    return CLUB if (coupling.options or {}).get("upper") == CLUB else FEDERATION


def _fits(coupling: Coupling, packet: Packet) -> bool:
    club = upper_kind(coupling) == CLUB
    if packet.only_club:
        return club
    return packet.under_club or not club


def sendable(coupling: Coupling) -> list[Packet]:
    return [
        p
        for p in REGISTRY.values()
        if direction_of(coupling) in p.directions and _fits(coupling, p)
    ]


def receivable(coupling: Coupling) -> list[Packet]:
    mine = direction_of(coupling)
    other = UP if mine == DOWN else DOWN
    return [p for p in REGISTRY.values() if other in p.directions and _fits(coupling, p)]


def defaults(coupling: Coupling) -> dict:
    return {p.key: p.default for p in sendable(coupling) if p.default}


def clean_levels(coupling: Coupling, given: dict) -> dict:
    result = {}
    for p in sendable(coupling):
        value = (given or {}).get(p.key)
        if value in {lvl for lvl, _ in p.levels}:
            result[p.key] = value
    return result


def digest(data) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def build(coupling: Coupling, packet: Packet) -> dict:
    """Aktueller Stand eines Pakets (leer, wenn nicht freigegeben)."""
    level = coupling.level(packet.key)
    if not level or packet.build is None:
        return {"level": None}
    return {"level": level, **packet.build(coupling, level)}


def file_b64(field, limit: int) -> str | None:
    if not field:
        return None
    try:
        field.open("rb")
        content = field.read(limit + 1)
    except OSError:
        return None
    finally:
        try:
            field.close()
        except OSError:
            pass
    if len(content) > limit:
        return None
    return base64.b64encode(content).decode()
