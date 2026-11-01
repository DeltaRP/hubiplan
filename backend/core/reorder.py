"""Reihenfolge einer Liste per Ziehen festlegen (Rollen, Untereinheiten, Mitgliedsarten …).

Die App schickt die Nummern aller Einträge der Liste in der neuen Reihenfolge.
Jeder Eintrag bekommt seine Stelle (1, 2, 3 …); Zahlenfelder gibt es in der
Oberfläche nicht mehr (Ralf 31.10.).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.response import Response

from audit.log import record


def parse_ids(data) -> list[int]:
    ids = data.get("ids") if hasattr(data, "get") else None
    if not isinstance(ids, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in ids
    ):
        raise serializers.ValidationError({"ids": gettext("Erwartet eine Liste von Nummern.")})
    if len(set(ids)) != len(ids):
        raise serializers.ValidationError({"ids": gettext("Ein Eintrag kommt doppelt vor.")})
    return ids


@transaction.atomic
def apply_order(
    queryset: QuerySet, ids: list[int], field: str, *, also: tuple[str, ...] = ()
) -> list:
    """Setzt ``field`` (und die Felder in ``also``) auf die Stelle in ``ids``.

    ``ids`` muss genau die Einträge von ``queryset`` enthalten; sonst hat sich die
    Liste inzwischen geändert und die App soll neu laden. Gibt die geänderten
    Einträge zurück, je mit ``_old_position``.
    """
    objects = {o.pk: o for o in queryset.select_for_update()}
    if set(objects) != set(ids):
        raise serializers.ValidationError(
            {"ids": gettext("Die Liste hat sich inzwischen geändert. Bitte neu laden.")}
        )
    changed = []
    for position, pk in enumerate(ids, start=1):
        obj = objects[pk]
        old = getattr(obj, field)
        if old == position and all(getattr(obj, f) == position for f in also):
            continue
        obj._old_position = old
        for f in (field, *also):
            setattr(obj, f, position)
        changed.append(obj)
    if changed:
        queryset.model._base_manager.bulk_update(changed, [field, *also])
    return changed


def reorder_response(request, org, queryset: QuerySet, field: str, *, also=()) -> Response:
    """Gemeinsamer Ablauf der Endpunkte ``…/reorder/``: prüfen, speichern, protokollieren."""
    ids = parse_ids(request.data)
    with transaction.atomic():
        changed = apply_order(queryset, ids, field, also=also)
        label = str(queryset.model._meta.get_field(field).verbose_name)
        for obj in changed:
            record(
                org, request.user, "update", obj, {label: [obj._old_position, getattr(obj, field)]}
            )
    return Response({"ids": ids})


def append_if_new(instance, field: str, siblings: QuerySet) -> None:
    """Neue Einträge ohne Stelle kommen ans Ende ihrer Liste."""
    if not instance._state.adding or getattr(instance, field):
        return
    last = siblings.order_by(f"-{field}").values_list(field, flat=True).first()
    setattr(instance, field, (last or 0) + 1)
