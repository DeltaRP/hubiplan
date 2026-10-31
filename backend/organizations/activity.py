"""Stilllegen und Reaktivieren wirkt auf alle Untereinheiten darunter (FQ-14).

Wird eine Einheit stillgelegt, werden alle noch aktiven Untereinheiten darunter mit
stillgelegt und als „mit der Einheit darüber stillgelegt“ markiert. Wird sie wieder
aktiv, kommen genau diese zurück; was vorher schon von Hand stillgelegt war, bleibt es.
"""

from __future__ import annotations

from .tree import UnitTree


def cascade_active(org) -> int:
    """Untereinheiten unter ``org`` dem neuen Zustand anpassen; Anzahl geänderter."""
    from .models import Organization

    if org.type == Organization.Type.UNIT:
        tree = UnitTree.of(org.organization_id)
        below = tree.subtree(org.pk)[1:]
    else:
        tree = UnitTree.of(org.pk)
        below = tree.ordered()
    if not below:
        return 0
    if not org.is_active:
        return Organization.objects.filter(pk__in=below, is_active=True).update(
            is_active=False, inactive_by_parent=True
        )
    flagged = set(
        Organization.objects.filter(pk__in=below, inactive_by_parent=True).values_list(
            "pk", flat=True
        )
    )
    active = {pk for pk in below if tree.nodes[pk].is_active}
    revive: list[int] = []
    for pk in below:  # Baumreihenfolge: Eltern vor Kindern
        parent = tree.nodes[pk].parent_id
        parent_active = parent is None or parent == org.pk or parent in active
        if pk in flagged and parent_active:
            revive.append(pk)
            active.add(pk)
    if revive:
        Organization.objects.filter(pk__in=revive).update(is_active=True, inactive_by_parent=False)
    return len(revive)
