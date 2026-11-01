"""API: Änderung rückgängig machen bzw. wiederherstellen."""

from __future__ import annotations

from django.apps import apps
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import (
    AUDIT_VIEW,
    BILLING_EDIT,
    DEPT_DOCS_MANAGE,
    DEPT_EVENTS_MANAGE,
    DEPT_MEMBERS_EDIT,
    DEPT_ROLES_MANAGE,
    DOCS_MANAGE,
    EVENTS_MANAGE,
    FINANCE_EDIT,
    MEMBERS_EDIT,
    ORG_EDIT,
    THEME_EDIT,
)
from core.api_base import OrgScopedMixin
from portal.views import DepartmentScopedMixin

from . import tracking
from .models import ChangeSet
from .undo import UndoProblem, undo

# Welche Berechtigung (eine davon) braucht, wer Änderungen an diesen Daten zurücknimmt?
NEEDED: dict[str, set[str]] = {
    "members.membertype": {ORG_EDIT},
    "customfields.fielddefinition": {ORG_EDIT},
    # Nur Rollen und Inhaber von Untereinheiten (die übrigen sperren das Paket)
    "access.role": {ORG_EDIT},
    "access.roleassignment": {MEMBERS_EDIT},
}
NEEDED_BY_APP: dict[str, set[str]] = {
    "organizations": {ORG_EDIT},
    "members": {MEMBERS_EDIT},
    "customfields": {MEMBERS_EDIT},
    "events": {EVENTS_MANAGE},
    "finance": {FINANCE_EDIT},
    "billing": {BILLING_EDIT},
    "documents": {DOCS_MANAGE},
}

# Im Abteilungsbereich: nur eigene Änderungen, mit den Rechten der Abteilung
DEPT_NEEDED: dict[str, str] = {
    "access.role": DEPT_ROLES_MANAGE,
    "access.roleassignment": DEPT_ROLES_MANAGE,
    "events.event": DEPT_EVENTS_MANAGE,
    "events.eventexception": DEPT_EVENTS_MANAGE,
    "events.eventresponse": DEPT_EVENTS_MANAGE,
}
DEPT_NEEDED_BY_APP: dict[str, str] = {
    "members": DEPT_MEMBERS_EDIT,
    "customfields": DEPT_MEMBERS_EDIT,
    "documents": DEPT_DOCS_MANAGE,
}


# Felder der Organisation, die auch das Gestaltungsrecht ändern darf (Farben, Logo).
THEME_FIELDS = {
    "primary_color",
    "accent_color",
    "primary_color_name",
    "accent_color_name",
    "extra_colors",
    "logo",
}


def needed_for(label: str, fields: set[str]) -> set[str]:
    """Rechte (eines davon), die eine Rücknahme dieser Felder braucht; leer = verboten."""
    if label == "organizations.organization":
        # Gestaltungsrecht nur, wenn ausschließlich Darstellungsfelder betroffen sind
        return {ORG_EDIT, THEME_EDIT} if fields and fields <= THEME_FIELDS else {ORG_EDIT}
    return NEEDED.get(label) or NEEDED_BY_APP.get(label.split(".")[0], set())


def missing_permission(change_set: ChangeSet, user, perms: set[str]) -> str | None:
    if change_set.user_id != user.pk and AUDIT_VIEW not in perms:
        return "Fremde Änderungen kann nur zurücknehmen, wer das Änderungsprotokoll sehen darf."
    for label, before, after in change_set.records.values_list("model", "before", "after"):
        fields = set(before or {}) | set(after or {})
        needed = needed_for(label, fields)
        # Unbekannte Daten: standardmäßig nicht zurücknehmen
        if not needed & perms:
            return "Dafür fehlt dir die Berechtigung."
    return None


def missing_dept_permission(change_set: ChangeSet, user, perms: set[str]) -> str | None:
    if change_set.user_id != user.pk:
        return "Hier lassen sich nur eigene Änderungen zurücknehmen."
    for label in set(change_set.records.values_list("model", flat=True)):
        needed = DEPT_NEEDED.get(label) or DEPT_NEEDED_BY_APP.get(label.split(".")[0])
        if needed is None or needed not in perms:
            return "Dafür fehlt dir die Berechtigung."
    return None


class _Undo:
    def problem(self, change_set: ChangeSet) -> str | None:
        raise NotImplementedError

    def post(self, request, set_id, **kwargs):
        change_set = get_object_or_404(ChangeSet, organization=self.org, pk=set_id)
        problem = self.problem(change_set)
        if problem:
            return Response({"detail": problem}, status=status.HTTP_403_FORBIDDEN)
        try:
            undo(change_set, self.org, request.user, force=bool(request.data.get("force")))
        except UndoProblem as exc:
            return Response(
                {
                    "detail": gettext("Das lässt sich nicht ohne Weiteres rückgängig machen."),
                    "problems": exc.messages,
                    "can_force": exc.can_force,
                },
                status=status.HTTP_409_CONFLICT,
            )
        ctx = tracking.active()
        return Response({"change_set": str(ctx.set_id) if ctx else None})


class UndoView(OrgScopedMixin, _Undo, APIView):
    """POST: Paket rückgängig machen. Antwort enthält das neue Paket (für Wiederherstellen)."""

    def problem(self, change_set):
        return missing_permission(change_set, self.request.user, self.org_permissions)


OUTSIDE = "Diese Änderung betrifft Daten außerhalb deines heutigen Bereichs."


class DeptUndoView(DepartmentScopedMixin, _Undo, APIView):
    """Rückgängig im Bereich einer Untereinheit: nur eigene Änderungen und nur an Daten,
    die heute noch in diesem Bereich liegen (Gesamtaudit 31.10.b, AT-S03)."""

    read_permission = None
    write_permission = None

    def problem(self, change_set):
        return missing_dept_permission(
            change_set, self.request.user, self.dept_permissions
        ) or self.outside_scope(change_set)

    def outside_scope(self, change_set) -> str | None:
        from organizations.tree import subtree_ids

        units = set(subtree_ids(self.dept))
        members = self.dept_members()
        for rec in change_set.records.all():
            model = apps.get_model(rec.model)
            current = model._base_manager.filter(pk=rec.object_id).values().first()
            # Heutiger Stand und der Stand, der wiederhergestellt würde (bei Änderungen
            # stehen in ``before`` nur die geänderten Felder)
            rows = [current] if current else []
            if rec.before:
                rows.append({**(current or {}), **rec.before})
            if not rows and rec.after:
                rows.append(rec.after)
            if not rows:
                return OUTSIDE
            for row in rows:
                if not self._row_in_scope(row, rec, units, members):
                    return OUTSIDE
        return None

    @staticmethod
    def _row_in_scope(row: dict, rec, units: set[int], members) -> bool:
        from events.models import Event

        if row.get("department_id") is not None:
            return row["department_id"] in units
        if row.get("membership_id") is not None:
            return members.filter(pk=row["membership_id"]).exists()
        if row.get("event_id") is not None:
            return Event.objects.filter(pk=row["event_id"], department_id__in=units).exists()
        if rec.person_id is not None:
            return members.filter(person_id=rec.person_id).exists()
        return False
