"""Hilfen zum Anlegen von Organisationen (von Hand oder beim Import)."""

from __future__ import annotations

from access.catalog import DEFAULT_MODULES, codes_for
from access.models import Role, RoleAssignment
from accounts.models import User
from core.tenancy import tenant_context
from organizations.models import Organization

DEFAULT_BOARD_ROLE = "Vorstand"


def add_board(org: Organization, email: str, invitations: list) -> RoleAssignment:
    """Benutzer mit dieser E-Mail bekommt die Rolle „Vorstand“ (neu: Einladung)."""
    email = email.strip().lower()
    user = User.objects.filter(email=email).first()
    with tenant_context(org.pk):
        role, _ = Role.objects.get_or_create(
            organization=org,
            name=DEFAULT_BOARD_ROLE,
            defaults={
                "description": "Vollzugriff auf die Organisation",
                "permissions": codes_for(org.type),
            },
        )
        if user is None:
            user = User.objects.create_user(email=email)
            user.set_unusable_password()
            user.save(update_fields=["password"])
            invitations.append((user, org, role.name))
        return RoleAssignment.objects.create(organization=org, role=role, user=user)


def create_club(federation: Organization, data: dict) -> Organization:
    """Dachverband legt einen Verein von Hand an (mit Vorstandsrolle)."""
    club = Organization(
        type=Organization.Type.CLUB,
        parent=federation,
        enabled_modules=list(DEFAULT_MODULES),
        **data,
    )
    club.full_clean(exclude=["logo", "parent", "contact_role"])
    club.save()
    with tenant_context(club.pk):
        Role.objects.create(
            organization=club,
            name=DEFAULT_BOARD_ROLE,
            description="Vollzugriff auf die Organisation",
            permissions=codes_for(club.type),
        )
    return club
