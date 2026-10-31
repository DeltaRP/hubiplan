"""Baum der Untereinheiten einer Einheit (z. B. Verein › Zug › Gruppe).

Untereinheiten können selbst Untereinheiten haben. Alle liegen im Datenbereich
derselben Einheit (``organization``); ``parent`` ist die direkt übergeordnete
Einheit. Wer einer Untereinheit angehört, gehört damit auch allen Einheiten
darüber an; eine Rolle in einer Einheit gilt auch für alle Einheiten darunter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Mehr Ebenen braucht kein Verein; schützt auch vor versehentlichen Ketten.
MAX_DEPTH = 6

PATH_SEPARATOR = " › "


@dataclass(frozen=True)
class Node:
    id: int
    parent_id: int | None  # None: direkt unter der Einheit mit dem Datenbereich
    name: str
    sort_order: int
    is_active: bool


class UnitTree:
    """Alle Untereinheiten einer Einheit, einmal geladen."""

    def __init__(self, nodes: Iterable[Node]):
        self.nodes = {n.id: n for n in nodes}
        self.children: dict[int | None, list[Node]] = {}
        for n in sorted(self.nodes.values(), key=lambda n: (n.sort_order, n.name.lower())):
            self.children.setdefault(n.parent_id, []).append(n)

    @classmethod
    def of(cls, org_id: int) -> UnitTree:
        from .models import Department

        rows = Department.objects.filter(organization_id=org_id).values_list(
            "id", "parent_id", "name", "sort_order", "is_active"
        )
        return cls(
            Node(pk, None if parent == org_id else parent, name, sort, active)
            for pk, parent, name, sort, active in rows
        )

    def ancestors(self, unit_id: int) -> list[int]:
        """[unit_id, Elternteil, …] bis zur obersten Untereinheit."""
        chain: list[int] = []
        node = self.nodes.get(unit_id)
        while node is not None and node.id not in chain:
            chain.append(node.id)
            node = self.nodes.get(node.parent_id) if node.parent_id else None
        return chain

    def subtree(self, unit_id: int) -> list[int]:
        """unit_id und alle Untereinheiten darunter (in Baumreihenfolge)."""
        result: list[int] = []
        stack = [unit_id]
        while stack:
            current = stack.pop()
            if current in result or current not in self.nodes:
                continue
            result.append(current)
            stack.extend(reversed([c.id for c in self.children.get(current, [])]))
        return result

    def with_descendants(self, unit_ids: Iterable[int]) -> set[int]:
        out: set[int] = set()
        for uid in unit_ids:
            out.update(self.subtree(uid))
        return out

    def with_ancestors(self, unit_ids: Iterable[int]) -> set[int]:
        out: set[int] = set()
        for uid in unit_ids:
            out.update(self.ancestors(uid))
        return out

    def depth(self, unit_id: int) -> int:
        """0 für Untereinheiten direkt unter der Einheit."""
        return max(len(self.ancestors(unit_id)) - 1, 0)

    def path(self, unit_id: int) -> str:
        names = [self.nodes[i].name for i in reversed(self.ancestors(unit_id))]
        return PATH_SEPARATOR.join(names)

    def ordered(self) -> list[int]:
        """Alle Untereinheiten in Baumreihenfolge (Eltern vor Kindern)."""
        result: list[int] = []
        for top in self.children.get(None, []):
            result.extend(self.subtree(top.id))
        return result


def subtree_ids(unit) -> list[int]:
    """Untereinheit und alle darunter."""
    return UnitTree.of(unit.organization_id).subtree(unit.pk)


def with_descendants(org_id: int, unit_ids: Iterable[int]) -> set[int]:
    ids = list(unit_ids)
    if not ids:
        return set()
    return UnitTree.of(org_id).with_descendants(ids)


def with_ancestors(org_id: int, unit_ids: Iterable[int]) -> set[int]:
    ids = list(unit_ids)
    if not ids:
        return set()
    return UnitTree.of(org_id).with_ancestors(ids)
