"""Ersten Verwalter einer Untereinheit in einem Schritt einrichten.

Fasst zusammen, was sonst an vier Stellen passiert: Zugang für Untereinheiten
einschalten, Rolle „Leitung“ mit allen Rechten der Einheit anlegen, sie dem
Mitglied geben und ihm einen Zugang einrichten. Hat die Einheit einen eigenen
Arbeitsbereich, bekommt das Konto dort zusätzlich die Rolle „Vorstand“.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from access.catalog import DEPARTMENT_CODES
from access.models import Role, RoleAssignment
from accounts.invitations import send_invitation
from audit.log import record
from core.tenancy import tenant_context
from members.models import DepartmentRoleHolder, Membership, today
from organizations.models import Department, DepartmentRole, Organization

from . import services

MANAGER_ROLE = "Leitung"


@dataclass
class ManagerResult:
    email: str
    role: str
    workspace_role: str | None
    mail: str  # "link", "password", "invitation" oder "none" (Versand fehlgeschlagen)


def setup_unit_manager(
    club: Organization, unit: Department, membership: Membership, actor
) -> ManagerResult:
    on = today()
    if membership.organization_id != club.pk or membership.current_period(on) is None:
        raise ValidationError({"member": "Bitte ein aktuelles Mitglied auswählen."})
    if not unit.is_active:
        raise ValidationError("Die Einheit ist inaktiv.")

    with transaction.atomic():
        if not unit.self_managed:
            unit.self_managed = True
            unit.save(update_fields=["self_managed"])
            record(club, actor, "update", unit, {"self_managed": [False, True]})
        if not club.department_access_enabled:
            club.department_access_enabled = True
            club.save(update_fields=["department_access_enabled"])
            record(club, actor, "update", club, {"department_access_enabled": [False, True]})

        role, created = DepartmentRole.objects.get_or_create(
            department=unit,
            name=MANAGER_ROLE,
            defaults={"organization": club, "permissions": sorted(DEPARTMENT_CODES)},
        )
        if created:
            record(club, actor, "create", role)
        elif not DEPARTMENT_CODES <= set(role.permissions or []):
            role.permissions = sorted(DEPARTMENT_CODES | set(role.permissions or []))
            role.save(update_fields=["permissions"])
            record(club, actor, "update", role, {"Rechte": [None, "alle Rechte"]})

        holds = (
            DepartmentRoleHolder.objects.filter(
                membership=membership, role=role, valid_from__lte=on
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
            .exists()
        )
        if not holds:
            holder = DepartmentRoleHolder.objects.create(
                organization=club, membership=membership, role=role, valid_from=on
            )
            record(
                club,
                actor,
                "create",
                holder,
                {"Rolle": [None, f"{role.name} ({unit.name})"]},
                person=membership.person,
            )

        # legt das Konto an, falls es noch keins gibt (braucht eine E-Mail-Adresse)
        access = services.ensure_access(club, membership, actor)
        user = access.user

        workspace_role = None
        if unit.own_workspace:
            from organizations.views import DEFAULT_BOARD_ROLE, ensure_workspace_role

            ensure_workspace_role(unit)
            with tenant_context(unit.pk):
                board = (
                    Role.objects.filter(organization=unit, name=DEFAULT_BOARD_ROLE).first()
                    or Role.objects.filter(organization=unit).order_by("pk").first()
                )
                if not RoleAssignment.objects.active(on).filter(user=user, role=board).exists():
                    RoleAssignment.objects.create(
                        organization=unit, role=board, user=user, person=membership.person
                    )
            workspace_role = board.name

    # Mail erst nach dem Speichern: neues Konto → Link zum Passwort-Festlegen,
    # bestehendes Konto → Hinweis bzw. Anmeldelink wie beim Knopf „Zugang“
    if not user.has_usable_password():
        kind = "invitation" if send_invitation(user, unit, role.name) else "none"
    else:
        kind = services.send_access_mail(club, access, actor)
    record(
        club,
        actor,
        "update",
        membership,
        {"Verwaltung": [None, f"{role.name} in {unit.name}, Zugang {user.email}"]},
        person=membership.person,
    )
    return ManagerResult(email=user.email, role=role.name, workspace_role=workspace_role, mail=kind)
