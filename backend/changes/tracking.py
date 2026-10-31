"""Mitschreiben von Änderungen je Anfrage (für Rückgängig und Papierkorb).

Die Middleware öffnet für jede ändernde API-Anfrage ein Änderungspaket. Die
Signal-Empfänger schreiben für jeden gespeicherten oder gelöschten Datensatz der
erfassten Apps die Rohwerte vorher und nachher mit. Schreibt eine Anfrage in
Bereiche, die sich nicht zurücknehmen lassen (Rechnungen, Kasse, E-Mails,
Zugänge …), wird das Paket gesperrt und nur mit Begründung gespeichert.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import signals
from django.db.models.fields.files import FieldFile

# Apps, deren Daten sich rückgängig machen lassen
TRACKED_APPS = {
    "members",
    "events",
    "organizations",
    "customfields",
    "finance",
    "billing",
    "documents",
    "honors",
}

# Nie erfasst und kein Hindernis (Protokolle, Sitzungen, Anmeldung, Exporte)
IGNORED_APPS = {
    "changes",
    "audit",
    "sessions",
    "contenttypes",
    "admin",
    "auth",
    "account",
    "mfa",
    "socialaccount",
    "usersessions",
    "headless",
}
IGNORED_MODELS = {"exchange.exportjob", "exchange.exporttemplate", "organizations.platformsettings"}

# Schreiben hier sperrt das Paket – mit diesem Grund
BLOCKING_MODELS = {
    "members.memberphoto": "Betrifft Mitgliederfotos.",
    "members.photouploadlink": "Betrifft Mitgliederfotos.",
    "members.transferrequest": "Betrifft einen Vereinswechsel.",
    "events.eventattachment": "Betrifft Dateianhänge.",
    "events.personalcalendar": "Betrifft ein Kalender-Abo.",
    "finance.receipt": "Betrifft Belege (Dateien).",
    "honors.reignphoto": "Betrifft Fotos der Chronik.",
    "finance.yearclosing": "Betrifft einen Jahresabschluss.",
    "finance.donationstatement": "Betrifft eine Zuwendungsbestätigung.",
    "billing.payment": "Betrifft Zahlungen.",
    "billing.dunning": "Betrifft Mahnungen.",
    "billing.mandate": "Betrifft SEPA-Mandate.",
    "billing.debitrun": "Betrifft eine Lastschriftdatei.",
    "billing.debititem": "Betrifft eine Lastschriftdatei.",
}
BLOCKING_APPS = {
    "outbox": "Es wurden E-Mails verschickt.",
    "exchange": "Betrifft einen Import.",
    "datatransfer": "Betrifft eine Datenübernahme.",
    "accounts": "Betrifft Zugänge.",
    "access": "Betrifft Rollen und Rechte.",
    "portal": "Betrifft Zugänge für Mitglieder.",
    "cards": "Betrifft Mitgliedsausweise.",
    "statutes": "Betrifft Dateien von Satzung, Beitragsordnung oder Gründungsurkunde.",
    "website": "Betrifft die Webseite.",
}
DEFAULT_BLOCK = "Lässt sich nicht rückgängig machen."

TRACK, BLOCK, IGNORE = "track", "block", "ignore"

LOCKED_INVOICE = "Betrifft eine festgeschriebene Rechnung."


def lock_reason(model: type[models.Model], values: dict | None) -> str:
    """Festgeschriebenes (abgeschlossenes Geschäftsjahr, Rechnung) bleibt, wie es ist."""
    if not values:
        return ""
    label = model._meta.concrete_model._meta.label_lower
    if label == "finance.booking" and values.get("year") is not None:
        from finance.models import YearClosing

        closed = YearClosing._base_manager.filter(
            organization_id=values.get("organization_id"), year=values["year"]
        ).exists()
        if closed:
            return f"Das Geschäftsjahr {values['year']} ist abgeschlossen."
        return _booking_lock(values)
    # Bestätigte Zuwendung und abgeschlossene Quittung: nur über Storno änderbar,
    # auch nicht über ein älteres Änderungspaket (Audit 31.10. FIN31-07)
    if label == "finance.donation" and values.get("statement_id"):
        return "Die Zuwendung ist bestätigt."
    if label == "finance.cashreceipt" and values.get("status") not in (None, "draft"):
        return "Die Quittung ist abgeschlossen."
    if label == "billing.invoice" and values.get("status") not in (None, "draft"):
        return LOCKED_INVOICE
    if label == "billing.invoiceline" and values.get("invoice_id"):
        from billing.models import Invoice

        status = (
            Invoice._base_manager.filter(pk=values["invoice_id"])
            .values_list("status", flat=True)
            .first()
        )
        return LOCKED_INVOICE if status not in (None, "draft") else ""
    return ""


def _booking_lock(values: dict) -> str:
    """Festgeschriebene Buchungen und Storni bleiben, wie sie sind (GoBD)."""
    import datetime

    from finance import services
    from finance.models import Booking
    from organizations.models import Organization

    if values.get("cancels_id"):
        return "Betrifft ein Storno."
    if values.get("id") and Booking._base_manager.filter(cancels_id=values["id"]).exists():
        return "Betrifft eine stornierte Buchung."
    org = Organization._base_manager.filter(pk=values.get("organization_id")).first()
    date, created = values.get("date"), values.get("created_at")
    if isinstance(date, str):
        date = datetime.date.fromisoformat(date)
    if isinstance(created, str):
        created = datetime.datetime.fromisoformat(created)
    if org is None or not isinstance(date, datetime.date):
        return ""
    why = services.fixed_on(org, date, created)
    return f"Die Buchung ist festgeschrieben{why}" if why else ""


# Rollen und Inhaber von Untereinheiten lassen sich rückgängig machen, die übrigen
# Rollen (Zugänge) nicht. Kennzeichen: dieses Feld ist gefüllt bzw. das Modell ist die
# Sicht auf die Untereinheiten (``DepartmentRole``, ``DepartmentRoleHolder``).
UNIT_ROWS = {"access.role": "department_id", "access.roleassignment": "membership_id"}


def classify(model: type[models.Model], instance: models.Model | None = None) -> tuple[str, str]:
    meta = model._meta.concrete_model._meta
    label = meta.label_lower
    if label in UNIT_ROWS and (
        model._meta.proxy or (instance is not None and getattr(instance, UNIT_ROWS[label], None))
    ):
        return TRACK, ""
    if meta.app_label in IGNORED_APPS or label in IGNORED_MODELS:
        return IGNORE, ""
    if label in BLOCKING_MODELS:
        return BLOCK, BLOCKING_MODELS[label]
    if meta.app_label in TRACKED_APPS:
        return TRACK, ""
    return BLOCK, BLOCKING_APPS.get(meta.app_label, DEFAULT_BLOCK)


# --- Rohwerte ---


def to_json(f: models.Field, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(f, models.JSONField):
        return value
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        # Immer in UTC: frisch gespeicherte Werte tragen sonst die Zone der Eingabe, aus der
        # Datenbank gelesene UTC – der Vergleich beim Rückgängigmachen schlüge fehl.
        return value.astimezone(datetime.UTC).isoformat()
    if isinstance(value, datetime.date | datetime.time | datetime.datetime):
        return value.isoformat()
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def from_json(f: models.Field, value: Any) -> Any:
    if value is None or isinstance(f, models.JSONField):
        return value
    return f.to_python(value)


def dump(instance: models.Model) -> dict[str, Any]:
    return {
        f.attname: to_json(f, f.value_from_object(instance)) for f in instance._meta.concrete_fields
    }


def volatile(model: type[models.Model]) -> set[str]:
    """Automatisch gesetzte Zeitstempel: zählen nicht als Änderung."""
    return {
        f.attname
        for f in model._meta.concrete_fields
        if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)
    }


def file_fields(model: type[models.Model]) -> set[str]:
    return {f.attname for f in model._meta.concrete_fields if isinstance(f, models.FileField)}


# --- Kontext je Anfrage ---


@dataclass
class Context:
    set_id: uuid.UUID
    user_id: int | None
    org_id: int | None = None
    seq: int = 0
    blocked: str = ""
    suppressed: int = 0
    internal: int = 0
    reverts: uuid.UUID | None = None
    has_create: bool = False
    has_delete: bool = False
    written: bool = False
    # SET_NULL-Aktualisierungen beim Löschen, die erwartet und schon erfasst sind
    expected_nulls: set[tuple[str, str]] = field(default_factory=set)
    persons: dict[tuple[str, Any], int | None] = field(default_factory=dict)

    def block(self, reason: str) -> None:
        if not self.blocked:
            self.blocked = reason


_current: ContextVar[Context | None] = ContextVar("hubiplan_changes", default=None)


def active() -> Context | None:
    ctx = _current.get()
    if ctx is None or ctx.suppressed:
        return None
    return ctx


def current_set_id() -> uuid.UUID | None:
    ctx = active()
    return ctx.set_id if ctx else None


@contextmanager
def tracking(user_id: int | None) -> Iterator[Context]:
    ctx = Context(set_id=uuid.uuid4(), user_id=user_id)
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


@contextmanager
def suppress() -> Iterator[None]:
    """Nichts mitschreiben (z. B. beim Löschen nach Ablauf der Löschfrist)."""
    ctx = _current.get()
    if ctx is None:
        yield
        return
    ctx.suppressed += 1
    try:
        yield
    finally:
        ctx.suppressed -= 1


@contextmanager
def internal() -> Iterator[None]:
    """Eigene Sammel-Aktualisierungen beim Zurückspielen nicht als Hindernis werten."""
    ctx = _current.get()
    if ctx is None:
        yield
        return
    ctx.internal += 1
    try:
        yield
    finally:
        ctx.internal -= 1


# --- Schreiben ---


def _person_of(ctx: Context, instance: models.Model) -> int | None:
    label = instance._meta.label_lower
    if label == "members.person":
        return instance.pk
    if label == "members.membership":
        return getattr(instance, "person_id", None)
    pid = getattr(instance, "person_id", None)
    if pid:
        return pid
    mid = getattr(instance, "membership_id", None)
    if not mid:
        return None
    key = ("membership", mid)
    if key not in ctx.persons:
        from members.models import Membership

        ctx.persons[key] = (
            Membership._base_manager.filter(pk=mid).values_list("person_id", flat=True).first()
        )
    return ctx.persons[key]


def _write(
    ctx: Context,
    instance: models.Model,
    operation: str,
    before: dict | None,
    after: dict | None,
) -> None:
    from core.tenancy import get_rls

    from .models import ChangeRecord

    org_id = get_rls().org_id
    if org_id is None:
        ctx.block(DEFAULT_BLOCK)
        return
    if ctx.org_id is None:
        ctx.org_id = org_id
    elif ctx.org_id != org_id:
        ctx.block("Betrifft mehrere Organisationen.")
        return
    ctx.seq += 1
    ctx.written = True
    if operation == "create":
        ctx.has_create = True
    elif operation == "delete":
        ctx.has_delete = True
    ChangeRecord.objects.create(
        organization_id=org_id,
        change_set_id=ctx.set_id,
        seq=ctx.seq,
        model=instance._meta.concrete_model._meta.label_lower,
        object_id=str(instance.pk),
        operation=operation,
        before=before,
        after=after,
        person_id=_person_of(ctx, instance),
    )


def _relevant(model, instance: models.Model | None = None) -> tuple[Context | None, str]:
    ctx = active()
    if ctx is None:
        return None, IGNORE
    kind, reason = classify(model, instance)
    if kind == BLOCK:
        ctx.block(reason)
    if ctx.blocked:
        return None, kind
    return ctx, kind


def _pre_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    ctx, kind = _relevant(sender, instance)
    if ctx is None or kind != TRACK:
        return
    before = None
    if not instance._state.adding and instance.pk is not None:
        row = sender._base_manager.filter(pk=instance.pk).first()
        before = dump(row) if row is not None else None
    instance._changes_before = before


def _post_save(sender, instance, created=False, raw=False, **kwargs):
    if raw:
        return
    ctx, kind = _relevant(sender, instance)
    if ctx is None or kind != TRACK:
        return
    before = instance.__dict__.pop("_changes_before", None)
    after = dump(instance)
    reason = lock_reason(sender, before) or lock_reason(sender, after)
    if reason:
        ctx.block(reason)
        return
    if before is None:
        _write(ctx, instance, "create", None, after)
        return
    skip = volatile(sender)
    changed = [k for k in after if k not in skip and after[k] != before.get(k)]
    if not changed:
        return
    if file_fields(sender) & set(changed):
        ctx.block("Betrifft Dateien (z. B. ein Logo).")
        return
    _write(
        ctx,
        instance,
        "update",
        {k: before.get(k) for k in changed},
        {k: after[k] for k in changed},
    )


def _is_set_null(on_delete) -> bool:
    return on_delete in (models.SET_NULL, models.SET_DEFAULT) or (
        getattr(on_delete, "__name__", "") == "set_on_delete"
    )


def _pre_delete(sender, instance, **kwargs):
    ctx, kind = _relevant(sender, instance)
    if ctx is None or kind != TRACK:
        return
    before = dump(instance)
    reason = lock_reason(sender, before)
    if reason:
        ctx.block(reason)
        return
    _write(ctx, instance, "delete", before, None)
    # Verweise, die beim Löschen geleert werden, ebenfalls festhalten
    for rel in instance._meta.related_objects:
        if not _is_set_null(rel.on_delete) or rel.field.many_to_many:
            continue
        related_model = rel.related_model
        rows = list(related_model._base_manager.filter(**{rel.field.name: instance.pk}))
        if not rows:
            continue
        kinds = {classify(related_model, row) for row in rows}
        if all(kind == IGNORE for kind, _ in kinds):
            continue
        blocked = [reason for kind, reason in kinds if kind == BLOCK]
        if blocked:
            ctx.block(blocked[0])
            return
        attname = rel.field.attname
        ctx.expected_nulls.add((related_model._meta.label_lower, rel.field.name))
        for row in rows:
            new = (
                to_json(rel.field, rel.field.get_default())
                if rel.on_delete is not models.SET_NULL
                else None
            )
            _write(ctx, row, "update", {attname: instance.pk}, {attname: new})


# --- Sammeloperationen ---

_orig_update = models.QuerySet.update
_orig_bulk_create = models.QuerySet.bulk_create
_orig_bulk_update = models.QuerySet.bulk_update


def _qs_update(self, **kwargs):
    ctx = active()
    if ctx is not None and not ctx.internal:
        kind, reason = classify(self.model)
        label = self.model._meta.label_lower
        expected = all((label, name) in ctx.expected_nulls for name in kwargs) and all(
            v is None for v in kwargs.values()
        )
        # Leere Aktualisierungen (z. B. SET_NULL ohne Verweise beim Löschen) stören nicht
        if kind != IGNORE and not expected and self.exists():
            ctx.block(reason or "Sammeländerung, lässt sich nicht rückgängig machen.")
    return _orig_update(self, **kwargs)


def _qs_bulk_create(self, objs, *args, **kwargs):
    result = _orig_bulk_create(self, objs, *args, **kwargs)
    ctx, kind = _relevant(self.model)
    if ctx is not None and kind == TRACK:
        for obj in result:
            reason = lock_reason(self.model, dump(obj))
            if reason:
                ctx.block(reason)
                break
            if obj.pk is None:
                ctx.block("Sammeländerung, lässt sich nicht rückgängig machen.")
                break
            _write(ctx, obj, "create", None, dump(obj))
    return result


def _qs_bulk_update(self, objs, fields, *args, **kwargs):
    ctx = active()
    if ctx is not None and not ctx.internal:
        kind, reason = classify(self.model)
        if kind != IGNORE:
            ctx.block(reason or "Sammeländerung, lässt sich nicht rückgängig machen.")
    return _orig_bulk_update(self, objs, fields, *args, **kwargs)


def connect() -> None:
    signals.pre_save.connect(_pre_save, dispatch_uid="changes_pre_save")
    signals.post_save.connect(_post_save, dispatch_uid="changes_post_save")
    signals.pre_delete.connect(_pre_delete, dispatch_uid="changes_pre_delete")
    models.QuerySet.update = _qs_update
    models.QuerySet.bulk_create = _qs_bulk_create
    models.QuerySet.bulk_update = _qs_bulk_update
