"""Wer darf sich bei einem Dienst anmelden, und was erfährt der Dienst über ihn?

Grundlage ist allein die Einheit, die den Dienst eingetragen hat:

- aktive Rollen der Einheit (Vorstand, Kassierer, …) am Benutzerkonto,
- Rollen von Untereinheiten (z. B. Zugführer) über die eigene Mitgliedschaft,
- je nach Einstellung auch der Mitgliederzugang mit laufender Mitgliedschaft.

Rechte höherer Einheiten (z. B. Dachverband) zählen nicht: Wer in die Nextcloud eines
Vereins darf, entscheidet nur der Verein.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

from django.db.models import Q
from django.utils.translation import gettext

from access.models import RoleAssignment
from core.tenancy import tenant_context
from members.models import DepartmentMembership, DepartmentRoleHolder, today
from portal.models import PortalAccess

from .models import Client

# Gruppennamen in der Nextcloud dürfen höchstens 64 Zeichen haben
GROUP_MAX = 64
# Feste Namen (nicht übersetzt): Die Nextcloud erkennt Gruppen am Namen
BOARD_GROUP = "Vorstand"
MEMBERS_GROUP = "Mitglieder"


class NotAllowed(Exception):
    """Der Benutzer darf sich bei diesem Dienst nicht anmelden (Text für die Oberfläche)."""


@dataclass
class Profile:
    name: str = ""
    given_name: str = ""
    family_name: str = ""
    email: str = ""
    groups: list[str] = field(default_factory=list)


def subject(client: Client, user) -> str:
    """Kennung des Benutzers für genau diesen Dienst (bleibt gleich, solange es ihn gibt)."""
    mac = hmac.new(client.subject_salt.encode(), f"user:{user.pk}".encode(), hashlib.sha256)
    return mac.hexdigest()[:32]


def _group(name: str) -> str:
    return " ".join(str(name or "").split())[:GROUP_MAX]


def profile(client: Client, user) -> Profile:
    """Angaben für den Dienst; ``NotAllowed``, wenn der Benutzer nicht hinein darf."""
    org = client.organization
    if not user.is_active or not org.is_active or not client.is_active:
        raise NotAllowed(gettext("Die Anmeldung bei diesem Dienst ist nicht möglich."))
    on = today()
    with tenant_context(org.pk, user.pk):
        roles = list(
            RoleAssignment.objects.filter(user=user, organization=org)
            .active(on)
            .select_related("role", "person")
        )
        access = (
            PortalAccess.objects.filter(user=user, organization=org)
            .select_related("membership__person")
            .first()
        )
        membership = access.membership if access else None
        if membership is not None and membership.current_period(on) is None:
            membership = None
        units: list = []
        unit_roles: list = []
        if membership is not None:
            units = [
                dm.department
                for dm in DepartmentMembership.objects.filter(
                    membership=membership, valid_from__lte=on, department__is_active=True
                )
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
                .select_related("department")
            ]
            unit_roles = list(
                DepartmentRoleHolder.objects.filter(
                    membership=membership, role__department__is_active=True
                )
                .active(on)
                .select_related("role__department")
            )

    is_member = membership is not None
    allowed = bool(roles) or bool(unit_roles)
    if client.audience == Client.Audience.MEMBERS:
        allowed = allowed or is_member
    if not allowed:
        raise NotAllowed(
            gettext("Dein Konto hat bei {org} keinen Zugang zu „{name}“.").format(
                org=org.name, name=client.name
            )
        )

    groups: list[str] = []
    if client.groups_board and any(a.role.is_board for a in roles):
        groups.append(BOARD_GROUP)
    if client.groups_roles:
        groups += [a.role.name for a in roles]
        groups += [f"{h.role.name} ({h.role.department.name})" for h in unit_roles]
    if client.groups_units:
        groups += [u.name for u in units]
    if client.groups_members and is_member:
        groups.append(MEMBERS_GROUP)
    seen: set[str] = set()
    unique = []
    for g in map(_group, groups):
        if g and g not in seen:
            seen.add(g)
            unique.append(g)

    person = membership.person if membership is not None else None
    if person is None:
        person = next((a.person for a in roles if a.person_id), None)
    given = (getattr(person, "first_name", "") or user.first_name or "").strip()
    family = (getattr(person, "last_name", "") or user.last_name or "").strip()
    name = " ".join(p for p in (given, family) if p) or user.email.split("@")[0]
    return Profile(name=name, given_name=given, family_name=family, email=user.email, groups=unique)
