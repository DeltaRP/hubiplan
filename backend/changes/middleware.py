"""Ein Änderungspaket je ändernder API-Anfrage."""

from __future__ import annotations

import logging
from urllib.parse import quote

from django.apps import apps

from audit.models import AuditEntry
from core.tenancy import rls_bypass

from . import tracking
from .models import ChangeRecord, ChangeSet

logger = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ChangeSetMiddleware:
    """Muss nach ``core.tenancy.TenantMiddleware`` stehen (RLS-Kontext)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in WRITE_METHODS or not request.path.startswith("/api/"):
            return self.get_response(request)
        user = getattr(request, "user", None)
        user_id = user.pk if user is not None and user.is_authenticated else None
        with tracking.tracking(user_id) as ctx:
            response = self.get_response(request)
            try:
                change_set = finalize(ctx)
            except Exception:  # noqa: BLE001
                # Die Änderung selbst ist schon gespeichert: kein 500 melden, nur ohne
                # Rückgängig-Möglichkeit für diesen Schritt
                logger.exception("Änderungspaket konnte nicht abgeschlossen werden")
                change_set = None
        if change_set is not None:
            response["X-Change-Set"] = str(change_set.pk)
            response["X-Change-Undoable"] = "0" if change_set.blocked_reason else "1"
            kinds = [k for k, on in (("create", ctx.has_create), ("delete", ctx.has_delete)) if on]
            response["X-Change-Kind"] = ",".join(kinds) or "update"
            try:
                text = label(change_set)
            except Exception:  # noqa: BLE001
                # Nur die Beschriftung fehlt; die Änderung ist gespeichert (kein 500)
                logger.exception("Beschriftung des Änderungspakets fehlgeschlagen")
                text = "Änderung"
            response["X-Change-Label"] = quote(text)
        return response


def finalize(ctx: tracking.Context) -> ChangeSet | None:
    if ctx.org_id is None:
        return None
    with tracking.suppress(), rls_bypass():
        records = ChangeRecord.objects.filter(change_set_id=ctx.set_id)
        if not records.exists():
            return None
        if ctx.blocked:
            # Gesperrte Pakete brauchen keine Rohdaten
            records.delete()
        return ChangeSet.objects.create(
            id=ctx.set_id,
            organization_id=ctx.org_id,
            user_id=ctx.user_id,
            blocked_reason=ctx.blocked,
            reverts=ctx.reverts,
            has_create=ctx.has_create,
            has_delete=ctx.has_delete,
        )


def label(change_set: ChangeSet) -> str:
    """Kurze Beschreibung für die Liste der letzten Schritte."""
    with tracking.suppress(), rls_bypass():
        entries = list(AuditEntry.objects.filter(change_set=change_set.pk).order_by("id")[:20])
        if entries:
            first = entries[0]
            from audit.log import type_label
            from organizations.terms import rename_word

            kind = rename_word(type_label(first.object_type), change_set.organization)
            text = f"{kind} „{first.object_repr}“ {first.get_action_display()}"
            if len(entries) > 1:
                text += f" (+{len(entries) - 1})"
            return text[:200]
        record = change_set.records.order_by("seq").first()
    if record is None:
        return "Änderung"
    model = apps.get_model(record.model)
    return f"{model._meta.verbose_name} {record.get_operation_display()}"
