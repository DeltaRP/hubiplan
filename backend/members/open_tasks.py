"""Offene Aufgaben für die Startseite: Vorgänge, die eine Entscheidung brauchen.

Die Liste ist nur ein Einstieg; entschieden wird weiter in der jeweiligen
Fachansicht (Anfragen, Mitgliedsakte, Termin). Jede Art erscheint nur mit dem
Recht, das die Entscheidung erfordert.
"""

from __future__ import annotations

import datetime

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import EVENTS_MANAGE, MEMBERS_EDIT, PHOTOS_MANAGE
from core.api_base import OrgScopedMixin
from organizations.models import Organization

LIMIT = 20
# Termine mit Zu-/Absagen, die bald stattfinden
EVENT_DAYS = 14


def _person(membership) -> str:
    p = membership.person
    return f"{p.first_name} {p.last_name}"


def member_tasks(org: Organization, perms: set[str]) -> list[dict]:
    from portal.models import ChangeRequest

    from .models import TransferRequest
    from .photo_models import MemberPhoto

    items: list[dict] = []
    if MEMBERS_EDIT in perms:
        for cr in ChangeRequest.objects.filter(
            organization=org, status=ChangeRequest.Status.PENDING
        ).select_related("membership__person")[:LIMIT]:
            items.append(
                {
                    "kind": "change_request",
                    "kind_label": "Änderungsmeldung",
                    "title": _person(cr.membership),
                    "detail": "möchte eigene Daten ändern",
                    "created_at": cr.created_at,
                    "link": "/mitglieder/anfragen/aenderungen",
                    "ref": cr.pk,
                    "membership": cr.membership_id,
                }
            )
        for tr in TransferRequest.objects.filter(
            from_org=org, status=TransferRequest.Status.PENDING
        ).select_related("person", "to_org")[:LIMIT]:
            items.append(
                {
                    "kind": "transfer",
                    "kind_label": "Wechselanfrage",
                    "title": f"{tr.person.first_name} {tr.person.last_name}",
                    "detail": f"{tr.to_org.display_name} möchte aufnehmen",
                    "created_at": tr.created_at,
                    "link": "/mitglieder/anfragen",
                }
            )
    if PHOTOS_MANAGE in perms:
        for photo in MemberPhoto.objects.filter(
            organization=org, status=MemberPhoto.Status.PENDING
        ).select_related("membership__person")[:LIMIT]:
            items.append(
                {
                    "kind": "photo",
                    "kind_label": "Foto freigeben",
                    "title": _person(photo.membership),
                    "detail": "hat ein Foto hochgeladen",
                    "created_at": photo.created_at,
                    "link": f"/mitglieder/{photo.membership_id}",
                    "ref": photo.pk,
                    "membership": photo.membership_id,
                }
            )
    return items


def event_tasks(org: Organization, perms: set[str]) -> list[dict]:
    from django.db.models import Count, Q

    from events.models import Event, EventResponse

    if EVENTS_MANAGE not in perms or "events" not in (org.enabled_modules or []):
        return []
    now = timezone.now()
    events = (
        Event.objects.filter(
            organization=org,
            department__isnull=True,
            rsvp_enabled=True,
            is_cancelled=False,
            starts_at__gte=now,
            starts_at__lte=now + datetime.timedelta(days=EVENT_DAYS),
        )
        .annotate(
            yes=Count("responses", filter=Q(responses__status=EventResponse.Status.YES)),
            no=Count("responses", filter=Q(responses__status=EventResponse.Status.NO)),
        )
        .order_by("starts_at")[:LIMIT]
    )
    local = timezone.localtime
    return [
        {
            "kind": "event",
            "kind_label": "Rückmeldungen",
            "title": e.title,
            "detail": f"am {local(e.starts_at):%d.%m.%Y}: {e.yes} Zusagen, {e.no} Absagen",
            "created_at": e.starts_at,
            "link": f"/termine?termin={e.pk}&datum={local(e.starts_at):%Y-%m-%d}",
            "ref": e.pk,
        }
        for e in events
    ]


@extend_schema(responses=dict)
class OpenTasksView(OrgScopedMixin, APIView):
    """Offene Aufgaben der Organisation, nach den Rechten des Benutzers."""

    def get(self, request, org_id: int):
        org, perms = self.org, self.org_permissions
        items: list[dict] = []
        if org.keeps_members and "members" in (org.enabled_modules or []):
            items += member_tasks(org, perms)
        items += event_tasks(org, perms)
        return Response({"items": items})
