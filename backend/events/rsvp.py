"""Zu- und Absagen (Meilenstein 13).

Eingeladen sind bei einem Vereinstermin alle aktuellen Mitglieder des Vereins,
bei einem Zugtermin die aktuellen Mitglieder des Zugs. Mitglieder melden sich im
Mitgliederbereich zurück; für Mitglieder ohne Zugang trägt der Vorstand ein.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from members.models import DepartmentMembership, Membership, MembershipPeriod, today
from members.services import contact_for
from organizations.tree import with_descendants

from .models import Event, EventResponse


def _current_period(on: datetime.date):
    return MembershipPeriod.objects.filter(
        Q(exit_date__isnull=True) | Q(exit_date__gte=on),
        membership=OuterRef("pk"),
        entry_date__lte=on,
    )


def _in_department(department_ids, on: datetime.date):
    return DepartmentMembership.objects.filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=on),
        membership=OuterRef("pk"),
        department_id__in=department_ids,
        valid_from__lte=on,
    )


def current_members(club, department_ids=None, on: datetime.date | None = None):
    """Aktuelle Mitglieder des Vereins, auf Wunsch nur der genannten Abteilungen."""
    on = on or today()
    qs = Membership.objects.filter(organization=club, purged_at__isnull=True).filter(
        Exists(_current_period(on))
    )
    if department_ids is not None:
        # Mitglieder der Einheiten und aller Einheiten darunter
        ids = list(department_ids)
        ids = list(with_descendants(club.pk, ids) or ids)
        qs = qs.filter(Exists(_in_department(ids, on)))
    return qs.select_related("person", "organization").order_by(
        "person__last_name", "person__first_name"
    )


def invited(event: Event, on: datetime.date | None = None):
    """Wer zu diesem Termin eingeladen ist (Zielgruppe für Rückmeldungen und Mails)."""
    if event.visibility == Event.Visibility.BOARD or event.organization.type != "club":
        return Membership.objects.none()
    depts = [event.department_id] if event.department_id else None
    return current_members(event.organization, depts, on)


def is_invited(event: Event, membership_id: int) -> bool:
    return invited(event).filter(pk=membership_id).exists()


@dataclass
class Summary:
    yes: int = 0
    no: int = 0
    guests: int = 0

    @property
    def persons(self) -> int:
        return self.yes + self.guests


def summary(event: Event, responses=None) -> Summary:
    qs = responses if responses is not None else event.responses.all()
    result = Summary()
    for row in qs.values("status").annotate(n=Count("pk"), g=Sum("guests")):
        if row["status"] == EventResponse.Status.YES:
            result.yes, result.guests = row["n"], row["g"] or 0
        else:
            result.no = row["n"]
    return result


def deadline_passed(event: Event, now: datetime.datetime | None = None) -> bool:
    now = now or timezone.now()
    end = event.rsvp_deadline or event.starts_at
    return now >= end


def member_can_respond(event: Event) -> tuple[bool, str]:
    """Darf ein Mitglied (noch) selbst zu- oder absagen?"""
    if not event.rsvp_enabled:
        return False, ""
    if event.is_cancelled:
        return False, "Der Termin ist abgesagt."
    if deadline_passed(event):
        return False, "Der Anmeldeschluss ist vorbei."
    return True, ""


def check_capacity(event: Event, response: EventResponse | None, status: str, guests: int):
    """Höchstzahl prüfen (eigene bisherige Zusage zählt nicht doppelt)."""
    if not event.rsvp_capacity or status != EventResponse.Status.YES:
        return
    taken = summary(event).persons - (response.persons if response else 0)
    free = event.rsvp_capacity - taken
    if 1 + guests > free:
        if free <= 0:
            raise ValidationError({"status": ["Leider sind alle Plätze vergeben."]})
        raise ValidationError(
            {"guests": [f"Es sind nur noch {free} Plätze frei (mit Ihnen selbst)."]}
        )


def save_response(
    event: Event,
    membership: Membership,
    *,
    status: str,
    guests: int,
    note: str,
    source: str,
    user,
    enforce_capacity: bool = True,
) -> tuple[EventResponse, dict | None]:
    """Legt die Rückmeldung an oder ändert sie. Gibt sie und den Vorher-Stand zurück."""
    if not event.rsvp_guests or status != EventResponse.Status.YES:
        guests = 0
    response = EventResponse.objects.filter(event=event, membership=membership).first()
    before = (
        {"status": response.status, "guests": response.guests, "note": response.note}
        if response
        else None
    )
    if enforce_capacity:
        check_capacity(event, response, status, guests)
    if response is None:
        response = EventResponse(event=event, membership=membership)
    response.status = status
    response.guests = guests
    response.note = note.strip()
    response.source = source
    response.updated_by = user
    response.save()
    return response, before


def email_of(membership: Membership) -> str:
    contact = contact_for(membership.person, membership.organization)
    return contact.email.lower() if contact and contact.email else ""


def response_label(response: EventResponse) -> str:
    text = response.get_status_display()
    if response.guests:
        text += f" + {response.guests}"
    return text
