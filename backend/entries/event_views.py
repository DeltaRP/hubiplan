"""Meldungen Schritt 2: Interessenabfrage über einen Termin im Kalender.

Die Ausschreibung wird mit einem Termin verknüpft; „Ich bin dabei“ ist die Zusage zum
Termin. Die Zusagen sind nur eine Vorauswahl: Personen lassen sich immer auch aus der
kompletten Mitgliederliste wählen (Ralf 2026-11-01). Eine eigene Tabelle für das Interesse
gibt es nicht (Konzept Abschnitt 15, Punkt 2).
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import EVENTS_MANAGE
from audit.log import diff, record, snapshot
from competitions.event_views import _visible_events as visible_events
from competitions.event_views import event_info, find_event
from events import services as event_services
from events.models import Event, EventResponse

from . import services
from .models import Call, Entry
from .views import _call_detail, _member_name, _Mixin


def calendar(view: _Mixin) -> dict:
    on = event_services.module_on(view.org)
    return {"on": on, "can_create": on and EVENTS_MANAGE in view.org_permissions}


def _midnight(day: datetime.date) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time()))


def link(view: _Mixin, call: Call, event: Event | None) -> None:
    before = snapshot(call)
    call.event = event
    fields = ["event"]
    if event is not None and not call.location and event.location:
        call.location = event.location[:200]
        fields.append("location")
    call.save(update_fields=[*fields, "updated_at"])
    changes = diff(before, snapshot(call))
    if changes:
        record(view.org, view.request.user, "update", call, changes)


def create_event(view: _Mixin, call: Call) -> Event:
    """Ganztägiger Termin am Tag des Anlasses, mit Zu- und Absagen bis zum Meldeschluss."""
    if not event_services.module_on(view.org):
        raise ValidationError("Der Terminkalender ist nicht freigeschaltet.")
    if EVENTS_MANAGE not in view.org_permissions:
        raise PermissionDenied("Termine anlegen darf, wer Termine verwalten darf.")
    if call.date is None:
        raise ValidationError("Bitte zuerst das Datum des Anlasses angeben.")
    if view.org.type != view.org.Type.CLUB:
        raise ValidationError("Zu- und Absagen gibt es nur bei Terminen eines Vereins.")
    day = _midnight(call.date)
    deadline = None
    if call.deadline and call.deadline < call.date:
        # Interesse bis zum Abend vor dem Meldeschluss, dann bleibt Zeit zum Aufstellen
        deadline = _midnight(call.deadline) - datetime.timedelta(minutes=1)
    event = Event(
        organization=view.org,
        title=call.title[:200],
        location=call.location[:200],
        description=(
            f"Meldung an {call.organizer}. Wer dabei sein möchte, sagt zu; "
            "die Mannschaften stellt der Vorstand auf."
        )[:5000],
        all_day=True,
        starts_at=day,
        ends_at=day,  # ganztägig: Ende = letzter Tag 0:00
        visibility=Event.Visibility.MEMBERS,
        rsvp_enabled=True,
        rsvp_deadline=deadline,
        created_by=view.request.user,
    )
    event.full_clean()
    event.save()
    record(view.org, view.request.user, "create", event, diff({}, snapshot(event)))
    link(view, call, event)
    return event


class CallEventCandidatesView(_Mixin, APIView):
    """GET ?suche=: Termine zur Auswahl (ohne Suche rund um das Datum des Anlasses)."""

    def get(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        out = {**calendar(self), "events": []}
        if not out["on"]:
            return Response(out)
        qs = visible_events(self).select_related("department")
        if term := request.query_params.get("suche", "").strip():
            qs = qs.filter(title__icontains=term[:100])
        else:
            today = timezone.localdate()
            day = call.date or today
            start = min(day, today) - datetime.timedelta(days=60)
            end = max(day, today) + datetime.timedelta(days=61)
            qs = qs.filter(starts_at__gte=_midnight(start), starts_at__lt=_midnight(end))
        linked = dict(
            Call.objects.filter(organization=self.org, event__isnull=False)
            .exclude(pk=call.pk)
            .values_list("event_id", "title")
        )
        for e in qs.order_by("starts_at", "pk")[:150]:
            info = event_info(e)
            info["call"] = linked.get(e.pk)
            out["events"].append(info)
        return Response(out)


class CallEventView(_Mixin, APIView):
    """POST {"event": id} zuordnen, {"event": null} lösen, {"create": true} neuen Termin
    mit Zu- und Absagen anlegen."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        call = Call.objects.select_for_update().get(pk=self.call(call_id).pk)
        if request.data.get("create"):
            if call.event_id:
                raise ValidationError("Die Ausschreibung hat schon einen Termin.")
            create_event(self, call)
        elif request.data.get("event") is None:
            link(self, call, None)
        else:
            link(self, call, find_event(self, request.data["event"]))
        call.refresh_from_db()
        return Response(_call_detail(self, call))


def response_status(call: Call, memberships) -> dict[int, str]:
    """Rückmeldung je Mitgliedschaft zum Termin der Ausschreibung („yes“/„no“)."""
    if call.event_id is None:
        return {}
    return dict(
        EventResponse.objects.filter(
            event_id=call.event_id, membership__in=memberships
        ).values_list("membership_id", "status")
    )


class ResponsesView(_Mixin, APIView):
    """GET: Zusagen und Absagen zum Termin als Vorauswahl für die Meldung."""

    def get(self, request, org_id: int, call_id: int):
        if not self.can_pick_members:
            raise PermissionDenied("Die Zusagen sieht nur, wer die Mitglieder sehen darf.")
        call = self.call(call_id)
        if call.event_id is None:
            return Response({"yes": [], "no_count": 0})
        rows = list(
            EventResponse.objects.filter(
                event_id=call.event_id,
                membership__organization=self.org,
                membership__purged_at__isnull=True,
            )
            .select_related("membership__person")
            .order_by("membership__person__last_name", "membership__person__first_name")
        )
        yes = [r for r in rows if r.status == EventResponse.Status.YES]
        infos = services.person_infos(
            self.org, [r.membership_id for r in yes], services.reference_date(call)
        )
        entry = Entry.objects.filter(call=call, organization=self.org).first()
        taken = (
            set(
                entry.persons.filter(membership__isnull=False).values_list(
                    "membership_id", flat=True
                )
            )
            if entry
            else set()
        )
        return Response(
            {
                "yes": [
                    {
                        "membership": r.membership_id,
                        "name": _member_name(r.membership),
                        "unit_name": infos[r.membership_id].unit_name
                        if r.membership_id in infos
                        else "",
                        "birth_year": r.membership.person.birth_date.year
                        if r.membership.person.birth_date
                        else None,
                        "note": r.note,
                        "taken": r.membership_id in taken,
                    }
                    for r in yes
                ],
                "no_count": len(rows) - len(yes),
            }
        )
