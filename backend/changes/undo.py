"""Änderungspakete zurückspielen (Rückgängig) – Wiederherstellen ist Rückgängig des Rückgängig."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from django.apps import apps
from django.db import IntegrityError, models, transaction
from django.db.models.deletion import ProtectedError, RestrictedError

from audit.log import diff, record, snapshot

from . import tracking
from .models import ChangeRecord, ChangeSet


@dataclass
class UndoProblem(Exception):
    messages: list[str] = field(default_factory=list)
    # True: nur Werte wurden inzwischen geändert, „trotzdem“ ist möglich
    can_force: bool = False


def _label(model: type[models.Model], obj: models.Model | None) -> str:
    name = str(model._meta.verbose_name)
    text = ""
    if obj is not None:
        try:
            text = str(obj)
        except Exception:  # noqa: BLE001 - nur für die Anzeige
            text = ""
    return f"{name} „{text}“" if text else name


def _build(model: type[models.Model], values: dict) -> models.Model:
    obj = model()
    for f in model._meta.concrete_fields:
        if f.attname in values:
            setattr(obj, f.attname, tracking.from_json(f, values[f.attname]))
    return obj


def _expected(rec: ChangeRecord) -> tuple[str, str, str]:
    inverse = {"create": "delete", "delete": "create", "update": "update"}
    return (rec.model, rec.object_id, inverse[rec.operation])


def undo(change_set: ChangeSet, org, user, *, force: bool = False) -> None:
    """Macht ``change_set`` rückgängig. Muss in einer ändernden Anfrage laufen."""
    with transaction.atomic():
        # Paket sperren und frisch lesen: Zwei gleichzeitige Klicks auf „Rückgängig“
        # (z. B. aus zwei Tabs) machen es sonst zweimal rückgängig. Die Sperre hält
        # bis zum Ende dieser Transaktion.
        fresh = ChangeSet.objects.select_for_update().filter(pk=change_set.pk).first()
        if fresh is None:
            raise UndoProblem(["Für diese Änderung sind keine Daten mehr vorhanden."])
        change_set.blocked_reason = fresh.blocked_reason
        change_set.reverted_by = fresh.reverted_by
        _undo(change_set, org, user, force=force)


def _undo(change_set: ChangeSet, org, user, *, force: bool) -> None:
    ctx = tracking.active()
    if ctx is None:
        raise RuntimeError("Rückgängig nur innerhalb einer ändernden Anfrage.")
    if change_set.blocked_reason:
        raise UndoProblem([change_set.blocked_reason])
    if change_set.reverted_by:
        raise UndoProblem(["Das wurde bereits rückgängig gemacht."])
    records = list(change_set.records.order_by("-seq"))
    if not records:
        raise UndoProblem(["Für diese Änderung sind keine Daten mehr vorhanden."])

    ctx.reverts = change_set.pk
    soft: list[str] = []
    hard: list[str] = []
    audit: list[tuple[str, models.Model, dict, int | None]] = []
    first_seq = ctx.seq

    with transaction.atomic():
        for rec in records:
            model = apps.get_model(rec.model)
            manager = model._base_manager
            skip = tracking.volatile(model)
            current_row = manager.filter(pk=rec.object_id).first()
            locked = tracking.lock_reason(
                model, tracking.dump(current_row) if current_row else None
            ) or tracking.lock_reason(model, rec.before)
            if locked:
                hard.append(locked)
                continue
            if rec.operation == "update":
                obj = manager.filter(pk=rec.object_id).first()
                if obj is None:
                    hard.append(
                        f"{_label(model, _build(model, rec.before or {}))} "
                        "wurde inzwischen gelöscht."
                    )
                    continue
                current = tracking.dump(obj)
                if any(current.get(k) != v for k, v in (rec.after or {}).items() if k not in skip):
                    soft.append(f"{_label(model, obj)} wurde inzwischen erneut geändert.")
                before_snap = snapshot(obj)
                for f in model._meta.concrete_fields:
                    if f.attname in (rec.before or {}):
                        setattr(obj, f.attname, tracking.from_json(f, rec.before[f.attname]))
                try:
                    with transaction.atomic():
                        obj.save()
                except IntegrityError:
                    hard.append(f"{_label(model, obj)} lässt sich nicht zurücksetzen.")
                    continue
                audit.append(("update", obj, diff(before_snap, snapshot(obj)), rec.person_id))
            elif rec.operation == "create":
                obj = manager.filter(pk=rec.object_id).first()
                if obj is None:
                    continue  # schon weg – Ziel erreicht
                current = tracking.dump(obj)
                if any(current.get(k) != v for k, v in (rec.after or {}).items() if k not in skip):
                    soft.append(f"{_label(model, obj)} wurde seit dem Anlegen geändert.")
                before_snap = snapshot(obj)
                label = _label(model, obj)
                try:
                    with transaction.atomic():
                        obj.delete()
                except (ProtectedError, RestrictedError, IntegrityError):
                    hard.append(f"{label} wird inzwischen an anderer Stelle verwendet.")
                    continue
                obj.pk = rec.object_id
                audit.append(("delete", obj, diff(before_snap, {}), rec.person_id))
            else:  # delete → wiederherstellen
                if manager.filter(pk=rec.object_id).exists():
                    hard.append(f"{_label(model, None)} existiert bereits wieder.")
                    continue
                obj = _build(model, rec.before or {})
                try:
                    with transaction.atomic():
                        obj.save(force_insert=True)
                        # Zeitstempel wie vor dem Löschen
                        fixed = {
                            f.attname: tracking.from_json(f, rec.before[f.attname])
                            for f in model._meta.concrete_fields
                            if f.attname in skip and f.attname in (rec.before or {})
                        }
                        if fixed:
                            with tracking.internal():
                                manager.filter(pk=obj.pk).update(**fixed)
                except IntegrityError:
                    hard.append(
                        f"{_label(model, obj)} lässt sich nicht wiederherstellen, "
                        "weil inzwischen ein gleicher Eintrag existiert."
                    )
                    continue
                audit.append(("create", obj, diff({}, snapshot(obj)), rec.person_id))

        # Hat das Zurückspielen mehr bewirkt als erwartet (z. B. mitgelöschte
        # Daten, die erst später entstanden sind)?
        expected = {_expected(r) for r in records}
        done = ChangeRecord.objects.filter(change_set_id=ctx.set_id, seq__gt=first_seq)
        for model_label, object_id, operation in done.values_list(
            "model", "object_id", "operation"
        ):
            if (model_label, object_id, operation) not in expected:
                model = apps.get_model(model_label)
                hard.append(
                    "Dabei wären auch später angelegte Daten betroffen "
                    f"({model._meta.verbose_name})."
                )
                break
        if ctx.blocked:
            hard.append(ctx.blocked)

        if hard or (soft and not force):
            messages = hard + soft
            raise UndoProblem(list(dict.fromkeys(messages)), can_force=not hard)

        for action, obj, changes, person_id in audit:
            person = SimpleNamespace(pk=person_id) if person_id else None
            record(org, user, action, obj, changes, person=person)
        ChangeSet.objects.filter(pk=change_set.pk).update(reverted_by=ctx.set_id)
        if change_set.reverts:
            # Rückgängig des Rückgängig: das ursprüngliche Paket gilt wieder
            ChangeSet.objects.filter(pk=change_set.reverts).update(reverted_by=None)
