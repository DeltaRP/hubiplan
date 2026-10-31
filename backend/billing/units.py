"""Rechnungen im Arbeitsbereich einer Untereinheit.

Die Rechnungen liegen im eigenen Datenbereich der Untereinheit: eigener
Nummernkreis, Zahlungen gehen in ihre Kasse. Empfänger sind Mitglieder der
Untereinheit oder einer Einheit darunter. Deren Daten (Person, Kontakt) liegen
im Datenbereich der Einheit darüber und werden nur dort gelesen.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

from core.tenancy import tenant_context
from members.models import Membership
from organizations.models import Organization


def is_unit(org) -> bool:
    return org is not None and org.type == Organization.Type.UNIT


def _members(unit, params: dict):
    from members.views import filter_members, member_queryset

    area = unit.organization
    qs = member_queryset(area)
    return filter_members(qs, {**params, "abteilung": str(unit.pk)}, area)


def search_members(unit, term: str, limit: int = 8) -> list[dict]:
    """Aktive Mitglieder der Untereinheit (und der Einheiten darunter) für die Auswahl."""
    from members.services import contact_for

    area = unit.organization
    with tenant_context(area.pk):
        qs = _members(unit, {"suche": term, "status": "aktiv"}).prefetch_related("person__contacts")
        rows = []
        for m in qs.order_by("person__last_name", "person__first_name", "pk")[:limit]:
            contact = contact_for(m.person, area)
            rows.append(
                {
                    "id": m.pk,
                    "first_name": m.person.first_name,
                    "last_name": m.person.last_name,
                    "email": contact.email if contact else "",
                }
            )
        return rows


def member_of(unit, membership_id) -> Membership | None:
    """Mitgliedschaft, wenn sie zur Untereinheit gehört (Person schon geladen)."""
    if not membership_id:
        return None
    with tenant_context(unit.organization_id):
        m = (
            _members(unit, {"status": "alle"})
            .filter(pk=membership_id)
            .prefetch_related("person__contacts")
            .first()
        )
        if m is not None:
            list(m.person.contacts.all())
        return m


def member_recipient(unit, membership_id) -> dict:
    from .services import member_recipient as recipient

    area = unit.organization
    with tenant_context(area.pk):
        membership = (
            Membership.objects.filter(organization=area, pk=membership_id)
            .select_related("person")
            .first()
        )
        if membership is None:
            return {}
        return recipient(area, membership)


def visible_membership(obj) -> Membership | None:
    """Mitgliedschaft einer Rechnung oder eines Postens, falls hier lesbar.

    Im Arbeitsbereich einer Untereinheit sind die Mitgliedschaften (Datenbereich
    der Einheit darüber) nicht sichtbar.
    """
    if not obj.membership_id:
        return None
    try:
        return obj.membership
    except ObjectDoesNotExist:
        return None


def portal_issuers(club) -> list[Organization]:
    """Einheiten, deren Rechnungen ein Mitglied im Mitgliederbereich sieht."""
    units = [
        u
        for u in Organization.objects.filter(
            organization=club,
            type=Organization.Type.UNIT,
            own_workspace=True,
            is_active=True,
        ).order_by("sort_order", "name")
        if "billing" in (u.enabled_modules or [])
    ]
    issuers = [club] if "billing" in (club.enabled_modules or []) else []
    return issuers + units
