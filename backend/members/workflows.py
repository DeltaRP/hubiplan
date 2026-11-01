"""Abläufe der Mitgliedschaft (Meilenstein 3).

Alle Abläufe führt ein Vorstand mit Bearbeitungsrecht aus; die Views schreiben
jeden Schritt ins Änderungsprotokoll.
"""

from __future__ import annotations

import datetime

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.models import AuditEntry
from core.tenancy import rls_bypass, tenant_context
from organizations.models import Organization, PlatformSettings
from organizations.terms import fill

from . import services
from .models import (
    ContactDetails,
    DepartmentMembership,
    DepartmentRoleHolder,
    ExitReason,
    Membership,
    MembershipPeriod,
    MemberType,
    MemberTypeAssignment,
    TransferRequest,
    today,
)

ONE_DAY = datetime.timedelta(days=1)


def lock(membership: Membership) -> None:
    """Person und Mitgliedschaft sperren, bevor ein Ablauf ihren Zustand prüft.

    Zwei gleichzeitige Abläufe (z. B. zweimal Austritt, Artwechsel neben einer
    Wechselanfrage) laufen so nacheinander; der zweite sieht den Stand des ersten.
    Reihenfolge immer Person vor Mitgliedschaft, damit sich nichts verklemmt."""
    services.lock_person(membership.person_id)
    Membership.objects.select_for_update().filter(pk=membership.pk).first()


def _open_period(membership: Membership, on: datetime.date) -> MembershipPeriod:
    period = membership.current_period(on)
    if period is None:
        raise ValidationError("Zu diesem Datum besteht keine Mitgliedschaft.")
    return period


# --- Mitgliedsart wechseln ---


@transaction.atomic
def change_type(membership: Membership, new_type: MemberType, on: datetime.date) -> None:
    """Die alte Art endet am Vortag, der Mitgliedszeitraum läuft weiter."""
    lock(membership)
    _open_period(membership, on)
    if new_type.organization_id != membership.organization_id or new_type.is_archived:
        raise ValidationError({"member_type": "Diese Mitgliedsart ist nicht verfügbar."})
    current = membership.current_type(on)
    if current and current.member_type_id == new_type.pk:
        raise ValidationError({"member_type": "Das ist bereits die aktuelle Art."})
    if current and current.valid_from >= on:
        raise ValidationError(
            {"valid_from": "Der Stichtag muss nach dem Beginn der jetzigen Art liegen."}
        )
    services.check_active_rule(membership.person, membership.organization, new_type, on, membership)
    if current:
        current.valid_until = on - ONE_DAY
        current.save()
    period = membership.current_period(on)
    MemberTypeAssignment.objects.create(
        organization=membership.organization,
        membership=membership,
        member_type=new_type,
        valid_from=on,
        valid_until=period.exit_date if period else None,
    )
    if new_type.reported:
        services.ensure_federation_member(membership.person, membership.organization)


# --- Austritt ---


@transaction.atomic
def exit_membership(
    membership: Membership, exit_date: datetime.date, reason: str, note: str = ""
) -> None:
    """Zeitraum schließen; Art, Abteilungen und Abteilungsrollen enden mit."""
    if reason not in ExitReason.values:
        raise ValidationError({"exit_reason": "Unbekannter Austrittsgrund."})
    lock(membership)
    period = membership.periods.filter(exit_date__isnull=True).first()
    if period is None:
        raise ValidationError("Die Mitgliedschaft ist bereits beendet.")
    if exit_date < period.entry_date:
        raise ValidationError({"exit_date": "Der Austritt liegt vor dem Eintritt."})
    period.exit_date = exit_date
    period.exit_reason = reason
    period.note = note[:200]
    period.save()
    open_until = Q(valid_until__isnull=True) | Q(valid_until__gt=exit_date)
    for qs in (
        membership.type_assignments.filter(open_until),
        membership.department_memberships.filter(open_until),
        membership.department_roles.filter(open_until),
    ):
        for item in qs:
            if item.valid_from > exit_date:
                item.delete()  # erst nach dem Austritt beginnend: entfällt
            else:
                item.valid_until = exit_date
                item.save()


# --- Wiedereintritt ---


@transaction.atomic
def reenter(
    membership: Membership,
    entry_date: datetime.date,
    member_type: MemberType,
    contact: dict | None = None,
) -> None:
    """Neuer Zeitraum; alte Zeiträume, Verbandsnummer usw. bleiben erhalten."""
    lock(membership)
    if membership.periods.filter(exit_date__isnull=True).exists():
        raise ValidationError("Die Person ist noch Mitglied.")
    last = membership.periods.order_by("-entry_date").first()
    if last and last.exit_date and entry_date <= last.exit_date:
        raise ValidationError(
            {"entry_date": "Der Wiedereintritt muss nach dem letzten Austritt liegen."}
        )
    if member_type.organization_id != membership.organization_id or member_type.is_archived:
        raise ValidationError({"member_type": "Diese Mitgliedsart ist nicht verfügbar."})
    club = membership.organization
    services.check_active_rule(membership.person, club, member_type, entry_date, membership)
    MembershipPeriod.objects.create(organization=club, membership=membership, entry_date=entry_date)
    MemberTypeAssignment.objects.create(
        organization=club, membership=membership, member_type=member_type, valid_from=entry_date
    )
    if contact:
        services.save_contact(membership.person, club, contact)
    elif services.contact_for(membership.person, club) is None:
        raise ValidationError({"email": "Bitte die Kontaktdaten neu erfassen."})
    if member_type.reported:
        services.ensure_federation_member(membership.person, club)
    if membership.purged_at:
        membership.purged_at = None
        membership.save()
        from . import loeschliste

        loeschliste.note_readmitted(membership)


# --- Wechselanfrage ---


def active_membership_elsewhere(person, club: Organization, on) -> Membership | None:
    federation = club.federation
    if federation is None:
        return None
    with rls_bypass():
        for membership in (
            Membership.objects.filter(person=person, scope=federation)
            .exclude(organization=club)
            .select_related("organization")
        ):
            if membership.current_period(on) is None:
                continue
            member_type = services.current_type_on(membership, on)
            if member_type and member_type.active:
                return membership
    return None


@transaction.atomic
def create_transfer(club: Organization, user, data: dict) -> TransferRequest:
    person = data["person"]
    member_type: MemberType = data["member_type"]
    entry_date = data["entry_date"]
    if not member_type.active:
        raise ValidationError(
            {"member_type": "Eine Wechselanfrage braucht es nur für eine aktive Mitgliedsart."}
        )
    if person.scope_id != services.scope_for(club).pk:
        raise ValidationError({"person": "Unbekannte Person."})
    # Gegen zwei gleichzeitige Anfragen für dieselbe Person
    services.lock_person(person.pk)
    other = active_membership_elsewhere(person, club, entry_date)
    if other is None:
        raise ValidationError(
            {
                "person": fill(
                    "Die Person ist in keinem anderen {e_sg} aktiv – bitte direkt aufnehmen.", club
                )
            }
        )
    with rls_bypass():
        if TransferRequest.objects.filter(
            person=person, to_org=club, status=TransferRequest.Status.PENDING
        ).exists():
            raise ValidationError("Es gibt bereits eine offene Wechselanfrage.")
        request = TransferRequest.objects.create(
            scope=services.scope_for(club),
            person=person,
            from_org=other.organization,
            to_org=club,
            member_type=member_type,
            member_type_name=member_type.name,
            entry_date=entry_date,
            admission=data.get("admission", {}),
            message=data.get("message", ""),
            created_by=user,
        )
    if request.from_org.is_remote:
        # Alter Verein auf einer anderen Instanz (Verbund): Anfrage dorthin
        from peering import transfers

        transfers.ask_from_side(request)
    return request


@transaction.atomic
def cancel_transfer(request: TransferRequest) -> TransferRequest:
    """Der neue Verein zieht seine offene Anfrage zurück. Gleiche Sperren wie bei der
    Entscheidung: Eine gleichzeitige Zustimmung wird nicht überschrieben (Audit ID-V01)."""
    services.lock_person(request.person_id)
    with rls_bypass():
        current = TransferRequest.objects.select_for_update().get(pk=request.pk)
    if current.status != TransferRequest.Status.PENDING:
        raise ValidationError("Die Anfrage ist bereits erledigt.")
    current.status = TransferRequest.Status.CANCELLED
    current.save()
    if current.from_org.is_remote:
        from peering import transfers

        transfers.cancelled(current)
    return current


@transaction.atomic
def decide_transfer(
    request: TransferRequest,
    user,
    decision: str,
    response: str = "",
    new_type: MemberType | None = None,
) -> Membership | None:
    """Der alte Verein entscheidet. Bei Zustimmung wird die Aufnahme im neuen
    Verein aktiv gespeichert; Nummer und Dachverbandseintritt bleiben gleich."""
    # Person, dann Anfrage sperren und den Stand erneut lesen: Eine zweite,
    # gleichzeitige Entscheidung sieht dann „bereits erledigt“
    services.lock_person(request.person_id)
    with rls_bypass():
        current = TransferRequest.objects.select_for_update().get(pk=request.pk)
    request.status = current.status
    if request.status != TransferRequest.Status.PENDING:
        raise ValidationError("Die Anfrage ist bereits erledigt.")
    request.decided_by = user
    request.decided_at = timezone.now()
    request.response = response[:500]
    if decision == "reject":
        request.status = TransferRequest.Status.REJECTED
        with rls_bypass():
            request.save()
        _notify_remote_to_side(request)
        return None

    old = Membership.objects.get(organization=request.from_org, person=request.person)
    if decision == TransferRequest.Decision.EXIT:
        exit_membership(old, request.entry_date - ONE_DAY, ExitReason.TRANSFER)
    elif decision == TransferRequest.Decision.CHANGE_TYPE:
        if new_type is None or new_type.active:
            raise ValidationError({"member_type": "Bitte eine nicht aktive Art wählen."})
        change_type(old, new_type, request.entry_date)
    else:
        raise ValidationError({"decision": "Unbekannte Entscheidung."})
    request.status = TransferRequest.Status.ACCEPTED
    request.decision = decision
    return admit_after_transfer(request)


def _notify_remote_to_side(request: TransferRequest) -> bool:
    """Neuer Verein auf einer anderen Instanz (Verbund): Entscheidung dorthin melden."""
    if not request.to_org.is_remote:
        return False
    from peering import transfers

    transfers.decided(request)
    return True


@transaction.atomic
def complete_remote_transfer(request: TransferRequest, decision: str, response: str = ""):
    """Der alte Verein liegt auf einer anderen Instanz und hat dort entschieden."""
    services.lock_person(request.person_id)
    with rls_bypass():
        current = TransferRequest.objects.select_for_update().get(pk=request.pk)
    if current.status != TransferRequest.Status.PENDING:
        return None
    request.decided_at = timezone.now()
    request.response = response[:500]
    if decision not in TransferRequest.Decision.values:
        request.status = TransferRequest.Status.REJECTED
        with rls_bypass():
            request.save()
        _notify_remote_to_side(request)
        return None
    request.status = TransferRequest.Status.ACCEPTED
    request.decision = decision
    return admit_after_transfer(request)


def admit_after_transfer(request: TransferRequest) -> Membership | None:
    """Aufnahme im neuen Verein – Systemschritt im Kontext des neuen Vereins."""
    if _notify_remote_to_side(request):
        with rls_bypass():
            request.save()
        return None
    to_club = request.to_org
    admission = dict(request.admission)
    data = {
        "person": request.person,
        "entry_date": request.entry_date,
        "club_number": admission.pop("club_number", ""),
        "departments": [],
        **{k: v for k, v in admission.items() if k in services.CONTACT_FIELDS},
    }
    with tenant_context(to_club.pk):
        from organizations.models import Department

        # Die Art gehört dem neuen Verein – erst in dessen Kontext lesbar
        data["member_type"] = MemberType.objects.get(pk=request.member_type_id)
        data["departments"] = list(
            Department.objects.filter(
                organization=to_club, pk__in=admission.get("department_ids", [])
            )
        )
        existing = Membership.objects.filter(organization=to_club, person=request.person).first()
        if existing:
            reenter(existing, request.entry_date, data["member_type"], data_contact(data))
            membership = existing
        else:
            membership = services.admit(to_club, data)
    with rls_bypass():
        request.save()
    return membership


def data_contact(data: dict) -> dict | None:
    contact = {k: data[k] for k in services.CONTACT_FIELDS if data.get(k)}
    return contact or None


# --- Löschfrist ---


def purge_due_date(membership: Membership) -> datetime.date | None:
    """Ab wann die Daten eines ehemaligen Mitglieds gelöscht werden."""
    if membership.purged_at or membership.periods.filter(exit_date__isnull=True).exists():
        return None
    last = membership.periods.order_by("-exit_date").first()
    if last is None or last.exit_date is None:
        return None
    months = PlatformSettings.load().deletion_period_months
    return last.exit_date + relativedelta(months=months)


@transaction.atomic
def purge_membership(
    membership: Membership, *, after_deadline: bool = False, listed: bool = False
) -> None:
    """Löscht alles außer dem Minimum: Name, Vorname, Geburtsjahr und die Zeiträume
    (mit Mitgliedsart, für die Dauer). Geburtsdatum und Verbandsnummer werden gekürzt bzw.
    gelöscht, sobald die Person nirgends mehr Mitglied ist.

    Wird nicht für „Rückgängig“ mitgeschrieben; ältere Änderungspakete mit
    Daten der Person werden gelöscht."""
    from changes.purge import forget_person
    from changes.tracking import suppress

    with suppress():
        _purge_membership(membership, after_deadline)
        forget_person(membership.organization_id, membership.person_id)
    if not listed:
        # Fachfrage 7 (31.10.b): gilt auch nach dem Einspielen eines älteren Backups
        from . import loeschliste

        loeschliste.note(membership, after_deadline=after_deadline)


def _purge_membership(membership: Membership, after_deadline: bool = False) -> None:
    person = membership.person
    club = membership.organization
    DepartmentMembership.objects.filter(membership=membership).delete()
    DepartmentRoleHolder.objects.filter(membership=membership).delete()
    from .photos import remove_all

    remove_all(membership)
    membership.photo_consent_at = None
    membership.photo_consent_source = ""
    ContactDetails.objects.filter(person=person, organization=club).delete()
    membership.club_number = ""
    membership.purged_at = timezone.now()
    membership.save()
    # Gemeinsame Kontaktdaten nur löschen, wenn die Person sonst nirgends mehr Mitglied ist
    still_member = (
        Membership.objects.filter(person=person, purged_at__isnull=True)
        .exclude(pk=membership.pk)
        .exists()
    )
    if not still_member:
        ContactDetails.objects.filter(person=person).delete()
        if after_deadline:
            # Nur nach Ablauf der Löschfrist; ein Verbund-Widerruf kürzt nur die Kopie hier
            _reduce_identity(person)
    # Personenbezogene Inhalte aus dem Protokoll dieses Vereins entfernen
    AuditEntry.objects.filter(organization=club, person_id=person.pk).update(
        changes={}, cleared=True
    )
    MembershipPeriod.objects.filter(membership=membership).update(note="")
    _purge_related(membership, person, club)


def _reduce_identity(person) -> None:
    """Gesamtaudit 31.10.b, Frage 6: nach der Löschfrist nur noch das Geburtsjahr und
    keine Verbandsnummer mehr. Name und Zeiträume bleiben für Chronik und Ehrungen."""
    from .models import FederationMember, Person

    with rls_bypass():
        field = Person._meta.get_field("birth_date")
        Person.objects.filter(pk=person.pk).update(
            birth_date=field.stored_value(person, person.birth_date.replace(month=1, day=1)),
            birth_year_only=True,
        )
        FederationMember.objects.filter(person_id=person.pk).delete()


def _purge_related(membership: Membership, person, club) -> None:
    """Zusatzfelder, Änderungsmeldungen und Zugang dieser Mitgliedschaft (Gesamtaudit A-S03).

    Rechnungen und Buchungen bleiben wegen der Aufbewahrungspflicht unverändert."""
    from customfields.models import FieldValue
    from portal.models import ChangeRequest, LoginLink, PortalAccess

    # Zusatzfeldwerte des Vereins und seiner Untereinheiten; Felder übergeordneter
    # Ebenen (z. B. Dachverband) gehören nicht dem Verein und bleiben
    values = FieldValue.objects.filter(person=person).select_related("organization")
    own = [v.pk for v in values if club in v.organization.ancestors()]
    FieldValue.objects.filter(pk__in=own).delete()
    # Meldungen: Inhalte leeren; offene gelten als erledigt, damit nichts später
    # gelöschte Daten zurückschreibt
    ChangeRequest.objects.filter(membership=membership).update(
        data={}, previous={}, message="", response=""
    )
    ChangeRequest.objects.filter(membership=membership, status=ChangeRequest.Status.PENDING).update(
        status=ChangeRequest.Status.REJECTED, decided_at=timezone.now()
    )
    # Zugang sperren: Mitgliederzugang und offene Anmeldelinks dieses Vereins
    access = PortalAccess.objects.filter(membership=membership).first()
    if access is not None:
        LoginLink.objects.filter(
            user_id=access.user_id, organization=club, used_at__isnull=True
        ).update(used_at=timezone.now())
        access.delete()


def purge_expired(on: datetime.date | None = None) -> int:
    """Hintergrund-Job: alle Mitgliedschaften nach Ablauf der Löschfrist bereinigen."""
    on = on or today()
    months = PlatformSettings.load().deletion_period_months
    cutoff = on - relativedelta(months=months)
    count = 0
    with rls_bypass():
        candidates = Membership.objects.filter(purged_at__isnull=True).exclude(
            periods__exit_date__isnull=True
        )
        for membership in candidates.select_related("person", "organization"):
            last = membership.periods.order_by("-exit_date").first()
            if last and last.exit_date and last.exit_date < cutoff:
                purge_membership(membership, after_deadline=True)
                count += 1
    return count
