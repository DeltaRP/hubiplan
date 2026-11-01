"""Wettbewerb und Termin im Kalender (Ralf 2026-11-01): einen bestehenden Termin wählen
und dessen Angaben übernehmen, oder aus dem Wettbewerb einen Termin anlegen. Die Zusagen
des Termins lassen sich als Starter übernehmen (Konzept Abschnitt 7)."""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import EVENTS_MANAGE
from audit.log import diff, record, snapshot
from events import services as event_services
from events.models import Event, EventResponse

from .models import Competition
from .views import _Mixin, create_starter


def calendar_on(org) -> bool:
    return event_services.module_on(org)


def event_info(event: Event | None) -> dict | None:
    if event is None:
        return None
    start = timezone.localtime(event.starts_at)
    return {
        "id": event.pk,
        "title": event.title,
        "date": start.date().isoformat(),
        "time": None if event.all_day else start.strftime("%H:%M"),
        "location": event.location,
        "unit_name": event.department.name if event.department_id else "",
        "is_cancelled": event.is_cancelled,
        "rsvp_enabled": event.rsvp_enabled,
        "yes_count": event.responses.filter(status=EventResponse.Status.YES).count(),
    }


def _visible_events(view: _Mixin):
    """Einmalige Termine der eigenen Organisation (auch der Untereinheiten), die der
    Benutzer im Kalender sieht."""
    viewer = event_services.org_viewer(view.request.user, view.org, view.org_permissions)
    return Event.objects.filter(viewer.visible_q()).filter(
        organization=view.org, repeat=Event.Repeat.NONE, remote_uid=""
    )


def find_event(view: _Mixin, raw) -> Event:
    try:
        pk = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"event": gettext("Unbekannter Termin.")}) from exc
    event = _visible_events(view).select_related("department").filter(pk=pk).first()
    if event is None:
        raise ValidationError({"event": gettext("Unbekannter Termin.")})
    return event


def link(view: _Mixin, comp: Competition, event: Event | None, *, fill: bool = False) -> None:
    """Termin zuordnen (``None`` löst). ``fill``: leere Angaben aus dem Termin übernehmen."""
    before = snapshot(comp)
    comp.event = event
    fields = ["event"]
    if event is not None and fill:
        if not comp.location and event.location:
            comp.location = event.location[:200]
            fields.append("location")
        if not comp.description and event.description:
            comp.description = event.description[:5000]
            fields.append("description")
    comp.save(update_fields=[*fields, "updated_at"])
    changes = diff(before, snapshot(comp))
    if changes:
        record(view.org, view.request.user, "update", comp, changes)


def create_event(view: _Mixin, comp: Competition) -> Event:
    """Ganztägigen Termin mit Titel, Datum und Ort des Wettbewerbs anlegen (nur Mitglieder)."""
    if not calendar_on(view.org):
        raise ValidationError(gettext("Der Terminkalender ist nicht freigeschaltet."))
    if EVENTS_MANAGE not in view.org_permissions:
        raise PermissionDenied(gettext("Termine anlegen darf, wer Termine verwalten darf."))
    day = _midnight(comp.date)
    event = Event(
        organization=view.org,
        title=comp.title[:200],
        location=comp.location[:200],
        description=comp.description[:5000],
        all_day=True,
        starts_at=day,
        ends_at=day,  # ganztägig: Ende = letzter Tag 0:00
        visibility=Event.Visibility.MEMBERS,
        created_by=view.request.user,
    )
    event.full_clean()
    event.save()
    record(view.org, view.request.user, "create", event, diff({}, snapshot(event)))
    link(view, comp, event)
    return event


class EventCandidatesView(_Mixin, APIView):
    """GET ?suche=&datum=JJJJ-MM-TT: Termine zur Auswahl. Ohne Suche: rund um das Datum
    oder, ohne Datum, die der letzten zwei Monate und des kommenden Jahres."""

    def get(self, request, org_id: int):
        on = calendar_on(self.org)
        out = {"on": on, "can_create": on and EVENTS_MANAGE in self.org_permissions, "events": []}
        if not on:
            return Response(out)
        qs = _visible_events(self).select_related("department")
        if term := request.query_params.get("suche", "").strip():
            qs = qs.filter(title__icontains=term[:100])
        else:
            try:
                day = datetime.date.fromisoformat(request.query_params.get("datum", ""))
                start, end = day - datetime.timedelta(days=60), day + datetime.timedelta(days=61)
            except ValueError:
                today = timezone.localdate()
                start, end = (
                    today - datetime.timedelta(days=60),
                    today + datetime.timedelta(days=400),
                )
            qs = qs.filter(starts_at__gte=_midnight(start), starts_at__lt=_midnight(end))
        linked = dict(
            Competition.objects.filter(organization=self.org, event__isnull=False).values_list(
                "event_id", "title"
            )
        )
        for e in qs.order_by("starts_at", "pk")[:150]:
            info = event_info(e)
            info["competition"] = linked.get(e.pk)
            out["events"].append(info)
        return Response(out)


def _midnight(day: datetime.date) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time()))


class EventLinkView(_Mixin, APIView):
    """POST {"event": id} zuordnen (leere Angaben übernehmen), {"event": null} lösen,
    {"create": true} neuen Termin aus dem Wettbewerb anlegen."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        if request.data.get("create"):
            if comp.event_id:
                raise ValidationError(gettext("Der Wettbewerb hat schon einen Termin."))
            create_event(self, comp)
        elif request.data.get("event") is None:
            link(self, comp, None)
        else:
            link(self, comp, find_event(self, request.data["event"]), fill=True)
        comp.refresh_from_db()
        return Response(
            {
                "event": event_info(comp.event),
                "location": comp.location,
                "description": comp.description,
            }
        )


class StartersFromEventView(_Mixin, APIView):
    """POST: Zusagen des zugeordneten Termins als Starter übernehmen (ohne Begleitpersonen)."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        if comp.event_id is None:
            raise ValidationError(gettext("Dem Wettbewerb ist kein Termin zugeordnet."))
        yes = (
            EventResponse.objects.filter(
                event_id=comp.event_id,
                status=EventResponse.Status.YES,
                membership__organization=self.org,
                membership__purged_at__isnull=True,
            )
            .exclude(
                membership__in=comp.starters.filter(membership__isnull=False).values("membership")
            )
            .order_by("membership__person__last_name", "membership__person__first_name")
            .values_list("membership_id", flat=True)
        )
        added = 0
        for membership in yes:
            create_starter(self.org, request.user, comp, {"membership": membership})
            added += 1
        total = EventResponse.objects.filter(
            event_id=comp.event_id, status=EventResponse.Status.YES
        ).count()
        return Response({"added": added, "already": total - added})
