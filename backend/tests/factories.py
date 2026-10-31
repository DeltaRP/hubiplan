"""Hilfsfunktionen für Testdaten (alles erfunden)."""

from __future__ import annotations

import datetime

from access.catalog import codes_for
from access.models import Role, RoleAssignment
from accounts.models import User
from organizations.models import Organization

PASSWORD = "Sicheres-Passwort-123"


def make_org(name: str, type_: str = "club", parent: Organization | None = None, **extra):
    defaults = {
        "founding_year": 1900,
        "street": "Hauptstraße 1",
        "postal_code": "12345",
        "city": "Musterstadt",
        "enabled_modules": ["members"],
    }
    defaults.update(extra)
    return Organization.objects.create(
        name=name, type=type_, parent=parent or Organization.platform(), **defaults
    )


def make_user(email: str, **extra) -> User:
    return User.objects.create_user(email=email, password=PASSWORD, **extra)


def give_role(
    user: User,
    org: Organization,
    permissions: list[str] | None = None,
    name: str = "Vorstand",
    valid_from: datetime.date | None = None,
    valid_until: datetime.date | None = None,
) -> RoleAssignment:
    role, _ = Role.objects.get_or_create(
        organization=org,
        name=name,
        defaults={"permissions": codes_for(org.type) if permissions is None else permissions},
    )
    return RoleAssignment.objects.create(
        organization=org,
        role=role,
        user=user,
        valid_from=valid_from or datetime.date(2020, 1, 1),
        valid_until=valid_until,
    )


def make_member(
    club: Organization,
    first_name: str,
    last_name: str,
    email: str = "",
    member_type=None,
    departments=(),
    entry_date: datetime.date | None = None,
    birth_date: datetime.date | None = None,
):
    """Nimmt ein Mitglied über die Fachlogik auf (mit Kontakt und Abteilungen)."""
    from core.tenancy import tenant_context
    from members import services
    from members.models import MemberType

    with tenant_context(club.pk):
        if member_type is None:
            member_type, _ = MemberType.objects.get_or_create(
                organization=club, name="aktiv", defaults={"active": True}
            )
        return services.admit(
            club,
            {
                "member_type": member_type,
                "entry_date": entry_date or datetime.date(2015, 1, 1),
                "last_name": last_name,
                "first_name": first_name,
                "birth_date": birth_date or datetime.date(1980, 5, 17),
                "email": email or f"{first_name.lower()}@example.org",
                "street": "Lindenweg 4",
                "postal_code": "12345",
                "city": "Musterstadt",
                "departments": list(departments),
            },
        )
