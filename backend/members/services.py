"""Regeln der Mitgliederverwaltung (Aufnahme, Aktiv-Prüfung, Verbandsnummer)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max, Q
from rest_framework.exceptions import ValidationError

from audit.log import diff, record, snapshot
from core.tenancy import rls_bypass
from organizations.models import Organization, PlatformSettings
from organizations.terms import fill

from .models import (
    ContactDetails,
    DepartmentMembership,
    FederationMember,
    Membership,
    MembershipPeriod,
    MemberType,
    MemberTypeAssignment,
    Person,
    overlaps,
    today,
)

CONTACT_FIELDS = ("email", "phone", "street", "postal_code", "city", "country")


def federation_of(club: Organization) -> Organization | None:
    """Dachverband einer Einheit mit Mitgliedschaften (bei eigenen Mitgliedern
    des Dachverbands er selbst)."""
    if club.type == Organization.Type.FEDERATION:
        return club
    return club.federation


def scope_for(club: Organization) -> Organization:
    return club.federation or club


# --- Kontaktdaten ---


def shared_contacts() -> bool:
    return PlatformSettings.load().person_data_mode == PlatformSettings.PersonData.SHARED


def contact_for(
    person: Person, club: Organization, shared: bool | None = None
) -> ContactDetails | None:
    """Kontaktdaten, wie der Verein sie sieht.

    Gemeinsam gepflegt: der gemeinsame Datensatz. Je Verein: der eigene
    Datensatz, sonst (noch nicht angelegt) der gemeinsame als Vorlage.
    """
    contacts = list(person.contacts.all())
    own = next((c for c in contacts if c.organization_id == club.pk), None)
    common = next((c for c in contacts if c.organization_id is None), None)
    if shared_contacts() if shared is None else shared:
        return common or own
    return own or common


def save_contact(person: Person, club: Organization, data: dict) -> ContactDetails:
    organization = None if shared_contacts() else club
    contact = (
        ContactDetails.objects.select_for_update()
        .filter(person=person, organization=organization)
        .first()
    )
    if contact is None:
        template = contact_for(person, club)
        contact = ContactDetails(person=person, organization=organization, scope=person.scope)
        if template:
            for field in CONTACT_FIELDS:
                setattr(contact, field, getattr(template, field))
    for field in CONTACT_FIELDS:
        if field in data:
            setattr(contact, field, data[field])
    contact.save()
    return contact


# --- Aktiv-Prüfung und Dachverband ---


def current_type_on(membership: Membership, on: datetime.date) -> MemberType | None:
    assignment = membership.current_type(on)
    return assignment.member_type if assignment else None


def active_elsewhere(person: Person, club: Organization, on: datetime.date) -> str | None:
    """Name des Vereins, in dem die Person am Stichtag schon aktiv ist (oder None).

    Liest bewusst organisationsübergreifend (Systemprüfung); gibt nur den
    Vereinsnamen zurück, keine weiteren Daten.
    """
    federation = federation_of(club)
    if federation is None:
        return None
    with rls_bypass():
        others = (
            Membership.objects.filter(person=person, scope=federation)
            .exclude(organization=club)
            .select_related("organization")
        )
        for membership in others:
            if membership.current_period(on) is None:
                continue
            member_type = current_type_on(membership, on)
            if member_type and member_type.active:
                return membership.organization.name
    return None


def active_elsewhere_between(
    person: Person, club: Organization, start: datetime.date, end: datetime.date | None
) -> str | None:
    """Wie ``active_elsewhere``, aber für einen ganzen Zeitraum (nachgetragene Zeiten,
    Audit 31.10. M31-04): Name des Vereins, in dem die Person irgendwann darin aktiv war."""
    federation = federation_of(club)
    if federation is None:
        return None
    with rls_bypass():
        others = (
            Membership.objects.filter(person=person, scope=federation)
            .exclude(organization=club)
            .select_related("organization")
            .prefetch_related("periods", "type_assignments__member_type")
        )
        for membership in others:
            for period in membership.periods.all():
                if not overlaps(start, end, period.entry_date, period.exit_date):
                    continue
                for ta in membership.type_assignments.all():
                    if not ta.member_type.active:
                        continue
                    if overlaps(ta.valid_from, ta.valid_until, period.entry_date, period.exit_date):
                        a = max(ta.valid_from, period.entry_date)
                        ends = [d for d in (ta.valid_until, period.exit_date) if d]
                        if overlaps(start, end, a, min(ends) if ends else None):
                            return membership.organization.name
    return None


def check_active_rule(
    person: Person, club: Organization, member_type: MemberType, on, membership=None
) -> None:
    if not member_type.active:
        return
    other = active_elsewhere(person, club, on)
    if not other and federation_of(club) is None:
        # Dachverband auf einer anderen Instanz (Verbund): dort nachfragen
        from peering.register import ask_active_elsewhere

        other = ask_active_elsewhere(club, person, on, membership)
    if other:
        raise ValidationError(
            {
                "member_type": (
                    f"Die Person ist bereits aktives Mitglied in „{other}“. "
                    + fill("{dv_Im}", club)
                    + " ist nur eine aktive Mitgliedschaft erlaubt. Bitte eine nicht aktive "
                    + fill("Art wählen oder eine Wechselanfrage an {e_den_anderen} stellen.", club)
                )
            }
        )


def ensure_federation_member(person: Person, club: Organization) -> FederationMember | None:
    """Vergibt bei der ersten gemeldeten Aufnahme die Verbandsmitgliedsnummer."""
    federation = federation_of(club)
    if federation is None:
        return None
    existing = FederationMember.objects.filter(person=person).first()
    if existing:
        return existing
    # Sperre auf den Dachverband, damit zwei Aufnahmen nicht dieselbe Nummer ziehen
    Organization.objects.select_for_update().filter(pk=federation.pk).first()
    last = FederationMember.objects.filter(scope=federation).aggregate(m=Max("member_number"))["m"]
    return FederationMember.objects.create(
        scope=federation, person=person, member_number=(last or 0) + 1
    )


@dataclass
class FederationStatus:
    is_member: bool
    member_number: int | None
    entry_date: datetime.date | None
    entry_date_manual: bool


def reported_ranges(person: Person, federation: Organization) -> list[tuple]:
    """Zeiträume, in denen eine gemeldete Mitgliedsart galt (über alle Vereine)."""
    ranges = []
    with rls_bypass():
        memberships = Membership.objects.filter(person=person, scope=federation).prefetch_related(
            "periods", "type_assignments__member_type"
        )
        for membership in memberships:
            for period in membership.periods.all():
                for ta in membership.type_assignments.all():
                    if not ta.member_type.reported:
                        continue
                    if overlaps(period.entry_date, period.exit_date, ta.valid_from, ta.valid_until):
                        start = max(period.entry_date, ta.valid_from)
                        ends = [d for d in (period.exit_date, ta.valid_until) if d]
                        ranges.append((start, min(ends) if ends else None))
    return sorted(ranges, key=lambda r: r[0])


def federation_status(person: Person, club: Organization) -> FederationStatus | None:
    federation = federation_of(club)
    if federation is None:
        return None
    fm = FederationMember.objects.filter(person=person).first()
    ranges = reported_ranges(person, federation)
    on = today()
    is_member = any(start <= on and (end is None or end >= on) for start, end in ranges)
    computed = ranges[0][0] if ranges else None
    return FederationStatus(
        is_member=is_member,
        member_number=fm.member_number if fm else None,
        entry_date=(fm.manual_entry_date if fm and fm.manual_entry_date else computed),
        entry_date_manual=bool(fm and fm.manual_entry_date),
    )


# --- Dublettenprüfung ---


def find_duplicates(club: Organization, last_name: str, first_name: str, birth_date):
    """Mögliche Dubletten im Verbandsbereich: gleiches Geburtsdatum und Name.

    Die Personentabelle ist per RLS auf den Verbandsbereich beschränkt.
    """
    scope = scope_for(club)
    same_birth = Q(birth_date=birth_date) | Q(
        birth_year_only=True, birth_date__year=birth_date.year
    )
    qs = Person.objects.filter(same_birth, scope=scope).filter(
        Q(last_name__iexact=last_name.strip()) | Q(first_name__iexact=first_name.strip())
    )
    return list(qs.select_related("federation")[:10])


def lock_person(person_id: int) -> None:
    """Person sperren (vereinsübergreifend, daher ohne RLS), damit Prüfungen wie
    „nur eine aktive Mitgliedschaft“ nicht von einer gleichzeitigen Aufnahme oder
    einem Artwechsel in einem anderen Verein überholt werden."""
    with rls_bypass():
        Person.objects.select_for_update().filter(pk=person_id).first()


# --- Aufnahme ---


@transaction.atomic
def admit(club: Organization, data: dict) -> Membership:
    """Nimmt eine Person auf: neue Person oder Verknüpfung mit vorhandener."""
    scope = scope_for(club)
    member_type: MemberType = data["member_type"]
    entry_date: datetime.date = data["entry_date"]
    person: Person | None = data.get("person")

    if person is not None:
        if person.scope_id != scope.pk:
            raise ValidationError({"person": "Unbekannte Person."})
        lock_person(person.pk)
        if Membership.objects.filter(organization=club, person=person).exists():
            raise ValidationError(
                {
                    "person": (
                        fill("Die Person ist oder war bereits Mitglied {e_im}. ", club)
                        + "Bitte den Wiedereintritt in der Mitgliedsakte nutzen."
                    )
                }
            )
        if data.get("gender") and not person.gender:
            person.gender = data["gender"]
            person.save(update_fields=["gender"])
    else:
        person = Person.objects.create(
            scope=scope,
            last_name=data["last_name"].strip(),
            first_name=data["first_name"].strip(),
            birth_date=data["birth_date"],
            gender=data.get("gender", ""),
        )

    check_active_rule(person, club, member_type, entry_date)

    membership = Membership.objects.create(
        organization=club, scope=scope, person=person, club_number=data.get("club_number", "")
    )
    MembershipPeriod.objects.create(organization=club, membership=membership, entry_date=entry_date)
    MemberTypeAssignment.objects.create(
        organization=club, membership=membership, member_type=member_type, valid_from=entry_date
    )
    contact = {k: data[k] for k in CONTACT_FIELDS if k in data}
    if contact:
        save_contact(person, club, contact)
    for department in data.get("departments", []):
        DepartmentMembership.objects.create(
            organization=club, membership=membership, department=department, valid_from=entry_date
        )
    if member_type.reported:
        ensure_federation_member(person, club)
    return membership


def remove_role_holders(org, user, role) -> None:
    """Entfernt alle Inhaber-Einträge einer Rolle (mit Protokoll), z. B. vor dem Löschen."""
    for holder in role.holders.select_related("membership__person"):
        record(
            org,
            user,
            "delete",
            holder,
            diff(snapshot(holder), {}),
            person=holder.membership.person,
        )
        holder.delete()
