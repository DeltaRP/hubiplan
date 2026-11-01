"""Wer hat welchen Zugang? Anmeldelinks und Einladungen."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.exceptions import APIException, ValidationError

from access.catalog import DEPARTMENT_CODES
from access.models import RoleAssignment
from accounts.models import User
from core.tenancy import tenant_context, user_view
from members.models import DepartmentRoleHolder, Membership, today
from members.services import contact_for
from organizations.models import Department, Organization
from organizations.tree import UnitTree
from outbox import mail

from .models import LoginLink, PortalAccess, hash_token

LINK_DAYS = 7

# Felder, die ein Mitglied als Änderung melden darf
# Kontaktdaten ändern Mitglieder direkt (außer der Verein verlangt Bestätigung);
# Name, Geburtsdatum und Geschlecht bestätigt immer der Verein.
DIRECT_FIELDS = ("email", "phone", "street", "postal_code", "city", "country")

CHANGEABLE_FIELDS = (
    "last_name",
    "first_name",
    "birth_date",
    "gender",
    "email",
    "phone",
    "street",
    "postal_code",
    "city",
    "country",
)


@dataclass
class DepartmentContext:
    department: Department
    club: Organization
    membership_id: int
    permissions: set[str] = field(default_factory=set)


def accesses_of(user) -> list[PortalAccess]:
    if not user.is_authenticated:
        return []
    return list(
        PortalAccess.objects.filter(user=user, organization__is_active=True).select_related(
            "organization", "organization__parent"
        )
    )


def _is_current(membership: Membership, on: datetime.date) -> bool:
    return membership.current_period(on) is not None


def department_contexts(user) -> dict[int, DepartmentContext]:
    """Abteilungen, in denen der Benutzer über eine Abteilungsrolle Rechte hat."""
    result: dict[int, DepartmentContext] = {}
    on = today()
    for access in accesses_of(user):
        club = access.organization
        if club.type != Organization.Type.CLUB or not club.department_access_enabled:
            continue
        with tenant_context(club.pk, user.pk):
            membership = Membership.objects.filter(pk=access.membership_id).first()
            if membership is None or not _is_current(membership, on):
                continue
            holders = (
                DepartmentRoleHolder.objects.filter(
                    membership=membership,
                    valid_from__lte=on,
                    role__department__is_active=True,
                    # Von oben verwaltete Untereinheiten: ihre Rollen sind reine Ämter
                    role__department__self_managed=True,
                )
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
                .select_related("role__department")
            )
            for holder in holders:
                perms = set(holder.role.permissions or []) & DEPARTMENT_CODES
                if not perms:
                    continue
                dept = holder.role.department
                ctx = result.setdefault(
                    dept.pk, DepartmentContext(dept, club, membership.pk, set())
                )
                ctx.permissions |= perms
            # Eine Rolle gilt auch für alle Untereinheiten darunter
            tree = UnitTree.of(club.pk)
            for dept_id, ctx in list(result.items()):
                if ctx.club.pk != club.pk:
                    continue
                for sub_id in tree.subtree(dept_id)[1:]:
                    if not tree.nodes[sub_id].is_active:
                        continue
                    sub = result.get(sub_id)
                    if sub is None:
                        sub = result[sub_id] = DepartmentContext(
                            Department.objects.get(pk=sub_id), club, membership.pk, set()
                        )
                    sub.permissions |= ctx.permissions
    # Pflicht-2FA: Rollenverwaltung ruht nach der Übergangsfrist ohne zweiten Faktor
    from accounts.mfa_policy import gate

    for ctx in result.values():
        ctx.permissions = gate(user, ctx.permissions)
    return result


def portal_accesses(user) -> list[PortalAccess]:
    """Mitgliedschaften, die der Benutzer im Mitgliederbereich sehen darf."""
    return [
        a
        for a in accesses_of(user)
        if a.organization.type == Organization.Type.CLUB and a.organization.member_portal_enabled
    ]


def has_admin_access(user) -> bool:
    """Vorstand, Plattform oder Abteilungsrolle: Anmeldung nur mit Passwort (und 2FA)."""
    if user.is_superuser or user.is_staff:
        return True
    # Immer mit Blick auf genau dieses Konto: Bei der Anmeldung (Anmeldelink, Verbund) ist
    # noch niemand angemeldet, und unter RLS wären die Rollen sonst unsichtbar (AT-S01).
    with user_view(user.pk):
        if RoleAssignment.objects.active().filter(user=user).exists():
            return True
        return bool(department_contexts(user))


def uses_mfa(user) -> bool:
    from allauth.mfa.models import Authenticator

    return Authenticator.objects.filter(user=user).exists()


def link_login_allowed(user) -> bool:
    return user.is_active and not uses_mfa(user) and not has_admin_access(user)


# --- Zugang einrichten ---


def member_email(club: Organization, membership: Membership) -> str:
    contact = contact_for(membership.person, club)
    if not contact or not contact.email:
        raise ValidationError(gettext("Für dieses Mitglied ist keine E-Mail-Adresse hinterlegt."))
    return contact.email.lower()


class TransferNeeded(APIException):
    """Zugang hängt an einer anderen Adresse (409): nur ausdrücklich übertragen."""

    status_code = 409
    default_code = "transfer_needed"


TRANSFER_NEEDED = (
    "Das Mitglied hat schon einen Zugang mit {old}. Eine neue E-Mail-Adresse überträgt ihn "
    "nicht von selbst: Bitte „Zugang auf neue Adresse übertragen“ wählen."
)


def ensure_access(
    club: Organization, membership: Membership, created_by, transfer: bool = False
) -> PortalAccess:
    """Legt den Zugang an.

    Gibt es schon einen Zugang mit einer anderen Adresse, wird er nur mit ``transfer``
    auf die neue Adresse übertragen (FQ-15): die alte Adresse bekommt eine Mitteilung.
    """
    email = member_email(club, membership)
    access = PortalAccess.objects.filter(membership=membership).select_related("user").first()
    if access is not None and access.user.email.lower() != email and not transfer:
        raise TransferNeeded(TRANSFER_NEEDED.format(old=access.user.email))
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(email=email, password=None)
        user.first_name = membership.person.first_name
        user.last_name = membership.person.last_name
        user.save(update_fields=["first_name", "last_name"])
    if access is None:
        access = PortalAccess.objects.create(
            organization=club, membership=membership, user=user, created_by=created_by
        )
    elif access.user_id != user.pk:
        old_email = access.user.email
        access.user = user
        access.save(update_fields=["user"])
        _notify_transfer(club, membership, old_email, email)
    return access


def _notify_transfer(club: Organization, membership: Membership, old: str, new: str) -> None:
    """Mitteilung an die bisherige Adresse: ohne Link und ohne die neue Adresse ganz."""
    local, _, domain = new.partition("@")
    hint = f"{local[:1]}…@{domain}"
    mail.send(
        old,
        f"Ihr Zugang zu HUBIplan – {club.name} wurde übertragen",
        (
            f"Hallo {membership.person.first_name},\n\n"
            f"{club.name} hat Ihren Zugang zum Mitgliederbereich auf eine neue E-Mail-Adresse "
            f"({hint}) übertragen. Mit dieser Adresse ({old}) ist der Zugang zu Ihrer "
            f"Mitgliedschaft nicht mehr möglich.\n\n"
            f"Wenn Sie das nicht veranlasst haben, wenden Sie sich bitte an {club.name}.\n"
        ),
        organization=club,
        kind="zugang",
    )


def create_login_link(user, organization=None, created_by=None) -> str:
    token = LoginLink.new_token()
    LoginLink.objects.create(
        user=user,
        organization=organization,
        token_hash=hash_token(token),
        created_by=created_by,
        expires_at=timezone.now() + datetime.timedelta(days=LINK_DAYS),
    )
    return f"{settings.FRONTEND_URL}/anmelden/link/{token}"


def send_access_mail(club: Organization, access: PortalAccess, created_by) -> str:
    """Schickt einen Anmeldelink – oder, wenn das Konto mehr darf, nur einen Hinweis.

    Gibt die Art zurück: "link" oder "password" (Anmeldung mit dem bestehenden Konto).
    """
    user = access.user
    first_name = access.membership.person.first_name
    if link_login_allowed(user):
        url = create_login_link(user, club, created_by)
        body = (
            f"Hallo {first_name},\n\n"
            f"{club.name} lädt Sie in den Mitgliederbereich von HUBIplan ein. Dort sehen "
            f"Sie Ihre Daten und können Änderungen melden.\n\n"
            f"Mit diesem persönlichen Link melden Sie sich ohne Passwort an "
            f"(gültig {LINK_DAYS} Tage, einmal nutzbar):\n\n{url}\n\n"
            f"Einen neuen Link können Sie jederzeit auf der Anmeldeseite anfordern. "
            f"Wenn Sie lieber ein Passwort nutzen, wählen Sie dort „Passwort vergessen“.\n"
        )
        kind = "link"
    else:
        # Konten mit Verwaltungsrechten oder 2FA: kein Anmelde- oder Passwortlink aus dem
        # Mitgliederbereich heraus (die Mail läge im Postausgang der Einheit).
        body = (
            f"Hallo {first_name},\n\n"
            f"{club.name} hat Ihnen den Mitgliederbereich von HUBIplan freigeschaltet.\n\n"
            f"Melden Sie sich wie gewohnt mit Ihrem bestehenden Konto ({user.email}) an: "
            f"{settings.FRONTEND_URL}/anmelden\n\n"
            f"Falls Sie Ihr Passwort nicht kennen, wählen Sie dort „Passwort vergessen“.\n"
        )
        kind = "password"
    mail.send(
        user.email,
        f"Ihr Zugang zu HUBIplan – {club.name}",
        body,
        organization=club,
        kind="zugang",
    )
    return kind


def access_info(access: PortalAccess | None) -> dict | None:
    if access is None:
        return None
    return {
        "email": access.user.email,
        "created_at": access.created_at,
        "last_login": access.user.last_login,
        "login": "link" if link_login_allowed(access.user) else "password",
    }
