"""API des Terminkalenders.

Drei Zugänge teilen dieselben Ansichten:

- Vorstand einer Organisation: ``/api/orgs/<org_id>/events/…``
- Abteilungsrolle: ``/api/depts/<dept_id>/events/…``
- Mitgliederbereich (nur lesen): ``/api/portal/<access_id>/events/…``

Dazu der öffentliche Link ohne Anmeldung: ``/api/public/calendar/<key>/``.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import DEPT_EVENTS_MANAGE, EVENTS_MANAGE
from audit.log import diff, record, snapshot
from core.api_base import OrgScopedMixin
from core.tenancy import rls_bypass, scope_of, set_rls
from members.models import DepartmentMembership, Membership, today
from organizations.models import Organization
from organizations.terms import fill
from portal.views import DepartmentScopedMixin, _portal_access

from . import ical, notify, participants, pdf, recurrence, rsvp, services
from .models import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_GUESTS,
    CalendarPublication,
    Event,
    EventAttachment,
    EventCategory,
    EventException,
    EventResponse,
    PersonalCalendar,
)
from .recurrence import Occurrence, is_rule_start, occurrences
from .serializers import (
    CategorySerializer,
    EventWriteSerializer,
    ExceptionSerializer,
    exception_data,
)

ATTACHMENT_TYPES = {
    "application/pdf": b"%PDF-",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG",
}
TRACKED = ("starts_at", "ends_at", "all_day", "location", "address")


# --- Darstellung ---


def category_data(cat: EventCategory | None) -> dict | None:
    if cat is None:
        return None
    return {"id": cat.pk, "name": cat.name, "color": cat.color}


def occurrence_data(
    occ: Occurrence, viewer: services.Viewer, mine: dict[int, str] | None = None
) -> dict:
    """``mine``: eigene Rückmeldungen (Mitgliederbereich), Termin → Zu-/Absage."""
    event = occ.event
    data = {
        "key": occ.key,
        "event_id": event.pk,
        "title": event.title,
        "starts_at": occ.starts_at,
        "ends_at": occ.ends_at,
        "original_start": occ.original_start,
        "all_day": event.all_day,
        "location": event.location,
        "address": event.address,
        "category": category_data(event.category),
        "visibility": event.visibility,
        "is_cancelled": occ.is_cancelled,
        "note": occ.note,
        "is_moved": occ.is_moved,
        "is_series": event.is_series,
        "changed_at": event.changed_at,
        "owner": services.owner_label(event, short=True),
        "level": services.level(event),
        "department_id": event.department_id,
        "own": viewer.owns(event),
        "can_edit": viewer.can_edit(event),
        "rsvp_enabled": event.rsvp_enabled,
        # App: Hinweis „Rückmeldung fehlt“ vor dem Anmeldeschluss
        "rsvp_deadline": event.rsvp_deadline if event.rsvp_enabled else None,
    }
    if viewer.kind == "member":
        data["my_response"] = (mine or {}).get(event.pk) if event.rsvp_enabled else None
    return data


def rsvp_data(event: Event, viewer: services.Viewer) -> dict:
    """Stand der Zu- und Absagen für die Detailansicht."""
    data = {
        "enabled": event.rsvp_enabled,
        "deadline": event.rsvp_deadline,
        "capacity": event.rsvp_capacity,
        "guests_allowed": event.rsvp_guests,
        "max_guests": MAX_GUESTS,
    }
    if not event.rsvp_enabled and not event.responses.exists():
        return data
    s = rsvp.summary(event)
    if event.rsvp_capacity:
        data["free"] = max(0, event.rsvp_capacity - s.persons)
    if viewer.kind == "member":
        mine = event.responses.filter(membership_id=viewer.membership_id).first()
        data["mine"] = response_data(mine) if mine else None
        allowed, reason = rsvp.member_can_respond(event)
        if allowed and not rsvp.is_invited(event, viewer.membership_id):
            allowed, reason = False, "Zu diesem Termin sind Sie nicht eingeladen."
        data["can_respond"] = allowed
        data["reason"] = reason
    scope = viewer.response_scope(event)
    if scope is not None:
        data["can_view_list"] = True
        data["can_enter"] = event.rsvp_enabled
        if scope == "all":
            data["summary"] = {"yes": s.yes, "no": s.no, "guests": s.guests, "persons": s.persons}
    return data


def response_data(r: EventResponse) -> dict:
    return {
        "status": r.status,
        "guests": r.guests,
        "note": r.note,
        "source": r.source,
        "updated_at": r.updated_at,
    }


def attachment_data(att: EventAttachment, base: str) -> dict:
    return {
        "id": att.pk,
        "name": att.name,
        "size": att.size,
        "content_type": att.content_type,
        "url": f"{base}attachments/{att.pk}/",
    }


def event_data(event: Event, viewer: services.Viewer, base: str) -> dict:
    can_edit = viewer.can_edit(event)
    data = {
        "id": event.pk,
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "address": event.address,
        "category": category_data(event.category),
        "all_day": event.all_day,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "visibility": event.visibility,
        "visibility_label": event.get_visibility_display(),
        "repeat": event.repeat,
        "repeat_label": event.get_repeat_display(),
        "repeat_interval": event.repeat_interval,
        "repeat_until": event.repeat_until,
        "is_cancelled": event.is_cancelled,
        "cancel_note": event.cancel_note,
        "changed_at": event.changed_at,
        "owner": services.owner_label(event),
        "level": services.level(event),
        "department_id": event.department_id,
        "can_edit": can_edit,
        "attachments": [attachment_data(a, f"{base}{event.pk}/") for a in event.attachments.all()],
        "exceptions": [exception_data(e) for e in event.exceptions.all()],
        "rsvp": rsvp_data(event, viewer),
    }
    if can_edit:
        # Weitergabe: Angabe am Termin (leer = Voreinstellung) und die Voreinstellung
        owner = event.department if event.department_id else event.organization
        data["share_up"] = event.share_up
        data["share_down"] = event.share_down
        data["share_defaults"] = {
            "up": owner.events_share_up,
            "down": owner.events_share_down,
        }
    if viewer.finance and viewer.kind == "org" and viewer.owns(event):
        # Veranstaltungsfinanzen (Finanzen → Veranstaltungen), zu denen der Termin gehört
        project = event.project
        data["project"] = {"id": project.pk, "name": project.name} if project else None
        data["can_link_project"] = can_edit and viewer.finance == "edit"
    if can_edit:
        data["remind_days"] = event.remind_days
        data["reminded_at"] = event.reminded_at
        data["created_by"] = (
            event.created_by.get_full_name() or event.created_by.email if event.created_by else ""
        )
        data["created_at"] = event.created_at
    return data


def mails(event: Event, kind: str) -> None:
    """E-Mails im Hintergrund verschicken, sobald der Termin gespeichert ist."""
    from .tasks import send_event_mails

    if rsvp.invited(event).exists():
        transaction.on_commit(lambda: send_event_mails.delay(event.pk, kind))


# --- Zugänge ---


class _CalendarMixin:
    """Gemeinsame Hilfen; ``viewer`` und ``base_url`` setzen die Zugänge."""

    viewer: services.Viewer
    base_url: str

    def audit(self, action: str, instance, changes: dict) -> None:
        record(self.viewer.org, self.request.user, action, instance, changes)

    def require_manage(self) -> None:
        if not self.viewer.can_manage:
            raise PermissionDenied("Dafür fehlt dir die Berechtigung.")

    def visible_event(self, pk: int) -> Event:
        event = (
            self.viewer.events().prefetch_related("attachments", "exceptions").filter(pk=pk).first()
        )
        if event is None:
            raise NotFound()
        return event

    def own_event(self, pk: int) -> Event:
        event = self.visible_event(pk)
        if not self.viewer.can_edit(event):
            raise PermissionDenied("Diesen Termin kannst du hier nicht bearbeiten.")
        return event


class OrgCalendarMixin(_CalendarMixin, OrgScopedMixin):
    read_permission = None
    write_permission = EVENTS_MANAGE
    allowed_org_types = (Organization.Type.FEDERATION, Organization.Type.CLUB)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not services.module_on(self.org):
            raise NotFound("Der Terminkalender ist für diese Organisation nicht freigeschaltet.")
        self.viewer = services.org_viewer(request.user, self.org, self.org_permissions)
        self.base_url = f"/api/orgs/{self.org.pk}/events/"


class DeptCalendarMixin(_CalendarMixin, DepartmentScopedMixin):
    read_permission = None
    write_permission = DEPT_EVENTS_MANAGE

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not services.module_on(self.org):
            raise NotFound(
                fill("Der Terminkalender ist für {e_akk} nicht freigeschaltet.", self.org)
            )
        self.viewer = services.department_viewer(self.ctx)
        self.base_url = f"/api/depts/{self.dept.pk}/events/"


class PortalCalendarMixin(_CalendarMixin):
    """Mitgliederbereich: nur lesen, im Kontext des Vereins."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        access = _portal_access(request.user, kwargs["access_id"])
        club = access.organization
        if not services.module_on(club):
            raise NotFound(fill("Der Terminkalender ist für {e_akk} nicht freigeschaltet.", club))
        # Wie im Abteilungsbereich: Kontext des Vereins (die Middleware setzt ihn zurück)
        set_rls(club.pk, request.user.pk, scope_id=scope_of(club.pk))
        on = today()
        depts = list(
            DepartmentMembership.objects.filter(
                membership_id=access.membership_id, valid_from__lte=on
            )
            .exclude(valid_until__lt=on)
            .values_list("department_id", flat=True)
        )
        self.viewer = services.member_viewer(club, depts, access.membership_id)
        self.access = access
        self.base_url = f"/api/portal/{access.pk}/events/"


# --- Weitergabe der Termine nach oben und unten ---


class SharingSerializer(serializers.Serializer):
    share_up = serializers.BooleanField(required=False)
    share_down = serializers.BooleanField(required=False)


class UnitSharingSerializer(SharingSerializer):
    id = serializers.IntegerField()


class _Sharing(APIView):
    """GET: Voreinstellung der Weitergabe · PATCH: ändern.

    Die Einheit entscheidet selbst. Untereinheiten ohne eigene Verwaltung des
    Kalenders stellt die Einheit darüber ein (``units``).
    """

    def owner(self):
        return self.viewer.department or self.viewer.org

    def owner_editable(self) -> bool:
        if not self.viewer.can_manage:
            return False
        if self.viewer.department is not None:
            return services.has_own_calendar_admin(self.viewer.department)
        return True

    def managed_units(self) -> list:
        """Untereinheiten direkt darunter, über die diese Sicht entscheidet."""
        from organizations.models import Department

        if not self.viewer.can_manage:
            return []
        org = self.viewer.org
        if self.viewer.department is None:
            if org.type != Organization.Type.CLUB:
                return []
            units = Department.objects.filter(organization=org, parent=org)
        else:
            units = Department.objects.filter(organization=org, parent=self.viewer.department)
        return [u for u in units.order_by("sort_order", "name") if u.is_active]

    def data(self) -> dict:
        owner = self.owner()
        org = self.viewer.org
        if self.viewer.department is None:
            up_possible = bool(
                org.type == Organization.Type.CLUB
                and org.parent
                and org.parent.type == Organization.Type.FEDERATION
            )
            down_possible = org.children.exists()
        else:
            up_possible = True
            down_possible = owner.children.exists()
        units = [
            {
                "id": u.pk,
                "name": u.display_name,
                "share_up": u.events_share_up,
                "share_down": u.events_share_down,
                "has_children": u.children.exists(),
                "own_admin": services.has_own_calendar_admin(u),
            }
            for u in self.managed_units()
        ]
        return {
            "share_up": owner.events_share_up,
            "share_down": owner.events_share_down,
            "up_possible": up_possible,
            "down_possible": down_possible,
            "editable": self.owner_editable(),
            "units": units,
        }

    def get(self, request, **kwargs):
        return Response(self.data())

    @transaction.atomic
    def patch(self, request, **kwargs):
        self.require_manage()
        ser = SharingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data:
            if not self.owner_editable():
                raise PermissionDenied(
                    "Das entscheidet die übergeordnete Einheit, solange es hier keine "
                    "eigene Verwaltung des Kalenders gibt."
                )
            self._apply(self.owner(), ser.validated_data)
        units = request.data.get("units") or []
        if units:
            useries = UnitSharingSerializer(data=units, many=True)
            useries.is_valid(raise_exception=True)
            managed = {u.pk: u for u in self.managed_units()}
            for item in useries.validated_data:
                unit = managed.get(item["id"])
                if unit is None:
                    raise NotFound()
                if services.has_own_calendar_admin(unit):
                    raise PermissionDenied(
                        fill("{e_Diese} entscheidet selbst über ihre Termine.", unit)
                    )
                self._apply(unit, {k: v for k, v in item.items() if k != "id"})
        return Response(self.data())

    def _apply(self, owner, values: dict) -> None:
        before = snapshot(owner)
        for key, value in values.items():
            setattr(owner, f"events_{key}", value)
        owner.save(update_fields=[f"events_{k}" for k in values])
        changes = diff(before, snapshot(owner))
        if changes:
            self.audit("update", owner, changes)


# --- Ansichten (für alle Zugänge gleich) ---


class _EventList(APIView):
    """GET: Einzeltermine im Zeitraum (``from``/``to``) · POST: Termin anlegen."""

    def get(self, request, **kwargs):
        start, end = services.parse_range(request.query_params)
        items = occurrences(self.viewer.events(), start, end)
        if request.query_params.get("upcoming") == "1":
            now = timezone.now()
            items = [o for o in items if o.ends_at >= now or o.event.all_day][:8]
        mine = None
        if self.viewer.kind == "member":
            mine = dict(
                EventResponse.objects.filter(
                    membership_id=self.viewer.membership_id,
                    event_id__in={o.event.pk for o in items if o.event.rsvp_enabled},
                ).values_list("event_id", "status")
            )
        return Response(
            {
                "from": start,
                "to": end,
                "items": [occurrence_data(o, self.viewer, mine) for o in items],
                "can_manage": self.viewer.can_manage,
                # Zu- und Absagen und E-Mails bei Terminen eines Vereins oder Zugs
                "rsvp_allowed": self.viewer.can_manage
                and self.viewer.org.type == Organization.Type.CLUB,
                # Wählbar sind nur die Kategorien des eigenen Kalenders (Abteilung: Verein)
                "categories": [
                    {**category_data(c), "is_active": c.is_active}
                    for c in EventCategory.objects.filter(organization=self.viewer.org)
                ],
            }
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        self.require_manage()
        data = EventWriteSerializer(
            data=request.data,
            context={"org": self.viewer.org, "department": self.viewer.department},
        )
        data.is_valid(raise_exception=True)
        event = data.save(
            organization=self.viewer.org,
            department=self.viewer.department,
            created_by=request.user,
        )
        self.audit("create", event, diff({}, snapshot(event)))
        if data.notify:
            mails(event, notify.INVITE)
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url), status=201)


class _EventDetail(APIView):
    def get(self, request, pk: int, **kwargs):
        event = self.visible_event(pk)
        return Response(event_data(event, self.viewer, self.base_url))

    @transaction.atomic
    def patch(self, request, pk: int, **kwargs):
        event = self.own_event(pk)
        before = snapshot(event)
        tracked = {f: getattr(event, f) for f in TRACKED}
        was_cancelled, old_start = event.is_cancelled, event.starts_at
        data = EventWriteSerializer(
            event,
            data=request.data,
            partial=True,
            context={"org": self.viewer.org, "department": self.viewer.department},
        )
        data.is_valid(raise_exception=True)
        event = data.save()
        moved = any(getattr(event, f) != v for f, v in tracked.items())
        if moved:
            event.changed_at = timezone.now()
            event.save(update_fields=["changed_at"])
        if event.starts_at != old_start and event.reminded_at:
            # Neuer Zeitpunkt: Erinnerung noch einmal
            event.reminded_at = None
            event.save(update_fields=["reminded_at"])
        if data.notify:
            if event.is_cancelled and not was_cancelled:
                mails(event, notify.CANCEL)
            elif moved and not event.is_cancelled:
                mails(event, notify.CHANGE)
        removed = 0
        if not event.is_series:
            event.exceptions.all().delete()
        else:
            removed = recurrence.shift_exceptions(event, old_start)
        changes = diff(before, snapshot(event))
        changes.pop("changed_at", None)
        if removed:
            changes["Abweichungen"] = [
                None,
                f"{removed} passen nicht mehr zur Regel und wurden entfernt",
            ]
        if changes:
            self.audit("update", event, changes)
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url))

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        event = self.own_event(pk)
        self.audit("delete", event, diff(snapshot(event), {}))
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _EventNotify(APIView):
    """Eingeladene per E-Mail über eine Änderung oder Absage informieren.

    Beim Autospeichern geht jede Änderung einzeln an den Server; die Mail
    verschickt der Vorstand deshalb ausdrücklich, wenn er fertig ist.
    """

    @transaction.atomic
    def post(self, request, pk: int, **kwargs):
        event = self.own_event(pk)
        kind = request.data.get("kind")
        if kind == notify.CANCEL and event.is_cancelled:
            mails(event, notify.CANCEL)
        elif kind == notify.CHANGE and not event.is_cancelled:
            mails(event, notify.CHANGE)
        else:
            raise serializers.ValidationError({"kind": "Passt nicht zum Termin."})
        return Response(status=status.HTTP_204_NO_CONTENT)


class _EventOccurrence(APIView):
    """PUT: einzelnen Serientermin verschieben oder absagen · DELETE: zurücksetzen."""

    def _target(self, request, pk: int):
        event = self.own_event(pk)
        if not event.is_series:
            raise serializers.ValidationError("Das ist kein Serientermin.")
        data = ExceptionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        original = data.validated_data["original_start"]
        if not is_rule_start(event, original):
            raise serializers.ValidationError(
                {"original_start": "Zu diesem Zeitpunkt gibt es keinen Termin der Serie."}
            )
        return event, data.validated_data, original

    @transaction.atomic
    def put(self, request, pk: int, **kwargs):
        event, values, original = self._target(request, pk)
        exc, _ = EventException.objects.update_or_create(
            event=event,
            original_start=original,
            defaults={
                "is_cancelled": values.get("is_cancelled", False),
                "starts_at": values.get("starts_at"),
                "ends_at": values.get("ends_at"),
                "note": values.get("note", ""),
            },
        )
        label = f"{event.title} am {timezone.localtime(original):%d.%m.%Y}"
        state = "abgesagt" if exc.is_cancelled else "verschoben" if exc.starts_at else "Hinweis"
        self.audit("update", event, {"Serientermin": [label, state]})
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url))

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        event, _, original = self._target(request, pk)
        deleted, _ = EventException.objects.filter(event=event, original_start=original).delete()
        if deleted:
            label = f"{event.title} am {timezone.localtime(original):%d.%m.%Y}"
            self.audit("update", event, {"Serientermin": [label, "wie in der Serie"]})
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url))


def _sniff(upload) -> str:
    head = upload.read(8)
    upload.seek(0)
    for ctype, magic in ATTACHMENT_TYPES.items():
        if head.startswith(magic):
            return ctype
    raise serializers.ValidationError({"file": "Bitte eine PDF-, JPEG- oder PNG-Datei hochladen."})


def _safe_name(name: str) -> str:
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)
    return keep[-80:] or "anhang"


class _AttachmentList(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, pk: int, **kwargs):
        event = self.own_event(pk)
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Bitte eine Datei wählen."})
        if upload.size > MAX_ATTACHMENT_BYTES:
            raise serializers.ValidationError({"file": "Die Datei ist größer als 15 MB."})
        if event.attachments.count() >= MAX_ATTACHMENTS:
            raise serializers.ValidationError(
                {"file": f"Höchstens {MAX_ATTACHMENTS} Anhänge je Termin."}
            )
        ctype = _sniff(upload)
        att = EventAttachment(
            event=event,
            organization=event.organization,
            name=upload.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200],
            content_type=ctype,
            size=upload.size,
            uploaded_by=request.user,
        )
        att.file.save(_safe_name(upload.name), upload, save=False)
        att.save()
        self.audit("create", event, {"Anhang": [None, att.name]})
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url), status=201)


class _Attachment(APIView):
    def get(self, request, pk: int, att_id: int, **kwargs):
        event = self.visible_event(pk)
        att = get_object_or_404(EventAttachment, event=event, pk=att_id)
        response = FileResponse(
            att.file.open("rb"),
            content_type=att.content_type,
            as_attachment=request.query_params.get("download") == "1",
            filename=att.name,
        )
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @transaction.atomic
    def delete(self, request, pk: int, att_id: int, **kwargs):
        event = self.own_event(pk)
        att = get_object_or_404(EventAttachment, event=event, pk=att_id)
        self.audit("update", event, {"Anhang": [att.name, None]})
        att.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _Program(APIView):
    """Jahresprogramm als PDF: Mitglieder- und öffentliche Termine des Jahres."""

    def get(self, request, **kwargs):
        try:
            year = int(request.query_params.get("year") or timezone.localdate().year)
        except ValueError:
            year = timezone.localdate().year
        year = max(2000, min(year, 2100))
        viewer = self.viewer
        start, end = pdf.year_bounds(year)
        events = viewer.events().filter(visibility__in=services.SHARED)
        if viewer.kind == "org" and request.query_params.get("departments") != "1":
            events = events.filter(department__isnull=True)
        items = [o for o in occurrences(events, start, end) if not o.is_cancelled]
        owner = viewer.department or viewer.org
        chain = (
            [viewer.department, *viewer.org.ancestors()]
            if viewer.department
            else list(viewer.org.ancestors())
        )
        content = pdf.render(owner.name, viewer.org, chain, year, items, viewer.owns)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Jahresprogramm-{year}.pdf"'
        return response


class _Categories(APIView):
    """Kategorien des eigenen Kalenders (Abteilungen nutzen die des Vereins)."""

    def get(self, request, **kwargs):
        cats = EventCategory.objects.filter(organization=self.viewer.org)
        return Response(CategorySerializer(cats, many=True).data)

    @transaction.atomic
    def post(self, request, **kwargs):
        self._only_org()
        data = CategorySerializer(data=request.data, context={"org": self.viewer.org})
        data.is_valid(raise_exception=True)
        cat = data.save(organization=self.viewer.org)
        record(self.viewer.org, request.user, "create", cat, diff({}, snapshot(cat)))
        return Response(CategorySerializer(cat).data, status=201)

    def _only_org(self) -> None:
        if self.viewer.kind != "org" or not self.viewer.can_manage:
            raise PermissionDenied(fill("Kategorien legt {e_nom} an.", self.viewer.org))


class _CategoryDetail(_Categories):
    @transaction.atomic
    def patch(self, request, pk: int, **kwargs):
        self._only_org()
        cat = get_object_or_404(EventCategory, organization=self.viewer.org, pk=pk)
        before = snapshot(cat)
        data = CategorySerializer(
            cat, data=request.data, partial=True, context={"org": self.viewer.org}
        )
        data.is_valid(raise_exception=True)
        cat = data.save()
        changes = diff(before, snapshot(cat))
        if changes:
            record(self.viewer.org, request.user, "update", cat, changes)
        return Response(CategorySerializer(cat).data)

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        self._only_org()
        cat = get_object_or_404(EventCategory, organization=self.viewer.org, pk=pk)
        record(self.viewer.org, request.user, "delete", cat, diff(snapshot(cat), {}))
        cat.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def publication_data(request, pub: CalendarPublication | None) -> dict:
    if pub is None or not pub.is_public:
        return {"is_public": False, "ics_url": None, "json_url": None}
    key = pub.public_key
    return {
        "is_public": True,
        "ics_url": request.build_absolute_uri(reverse("public-calendar-ics", args=[key])),
        "json_url": request.build_absolute_uri(reverse("public-calendar", args=[key])),
    }


class PublicationSerializer(serializers.Serializer):
    is_public = serializers.BooleanField()
    renew = serializers.BooleanField(default=False)


class _Publication(APIView):
    """Öffentlichen Link ein- oder ausschalten oder erneuern."""

    def get(self, request, **kwargs):
        pub = services.publication(self.viewer.org, self.viewer.department)
        return Response(publication_data(request, pub))

    @transaction.atomic
    def put(self, request, **kwargs):
        self.require_manage()
        data = PublicationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        pub = services.publication(self.viewer.org, self.viewer.department, create=True)
        new = data.validated_data["is_public"]
        label = f" ({self.viewer.department.name})" if self.viewer.department else ""
        if data.validated_data["renew"]:
            pub.public_key = CalendarPublication.new_key()
            self.audit("update", pub, {f"Kalender-Link{label}": ["alt", "erneuert"]})
        if pub.is_public != new:
            self.audit("update", pub, {f"Kalender öffentlich{label}": [pub.is_public, new]})
            pub.is_public = new
        pub.save()
        return Response(publication_data(request, pub))


# --- Zu- und Absagen ---


class ResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=EventResponse.Status.choices)
    guests = serializers.IntegerField(min_value=0, max_value=MAX_GUESTS, default=0)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class BoardResponseSerializer(ResponseSerializer):
    membership_id = serializers.IntegerField()


def _response_label(status_: str | None, guests: int = 0) -> str:
    if status_ is None:
        return "keine"
    text = dict(EventResponse.Status.choices)[status_]
    return f"{text} + {guests}" if guests else text


class _ResponsesMixin:
    def scoped_event(self, pk: int) -> tuple[Event, str | int]:
        event = self.visible_event(pk)
        scope = self.viewer.response_scope(event)
        if scope is None:
            raise PermissionDenied("Die Rückmeldungen sieht der Vorstand, der den Termin anlegt.")
        return event, scope

    def lists(self, event: Event, scope):
        return participants.rows(event, None if scope == "all" else scope)

    def membership_in_scope(self, event: Event, scope, membership_id: int) -> Membership:
        members = rsvp.invited(event)
        if scope != "all":
            members = members.filter(
                pk__in=rsvp.current_members(event.organization, [scope]).values("pk")
            )
        membership = members.filter(pk=membership_id).first()
        if membership is None:
            raise serializers.ValidationError(
                {"membership_id": "Dieses Mitglied ist zu dem Termin nicht eingeladen."}
            )
        return membership


class _Responses(_ResponsesMixin, APIView):
    """GET: Teilnehmerliste · PUT: Rückmeldung für ein Mitglied eintragen (Vorstand)."""

    def get(self, request, pk: int, **kwargs):
        event, scope = self.scoped_event(pk)
        answered, open_ = self.lists(event, scope)
        yes = [r for r in answered if r.response.status == EventResponse.Status.YES]
        return Response(
            {
                "event_id": event.pk,
                "scope": "all" if scope == "all" else "department",
                "summary": {
                    "yes": len(yes),
                    "no": len(answered) - len(yes),
                    "guests": sum(r.response.guests for r in yes),
                    "persons": len(yes) + sum(r.response.guests for r in yes),
                    "open": len(open_),
                },
                "capacity": event.rsvp_capacity,
                "items": [r.data() for r in answered],
                "open": [
                    {"membership_id": r.membership_id, "name": r.name, "departments": r.departments}
                    for r in open_
                ],
            }
        )

    @transaction.atomic
    def put(self, request, pk: int, **kwargs):
        _lock_event(pk)
        event, scope = self.scoped_event(pk)
        if not event.rsvp_enabled:
            raise serializers.ValidationError("Für diesen Termin sind Zu- und Absagen aus.")
        data = BoardResponseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        membership = self.membership_in_scope(event, scope, v["membership_id"])
        # Der Vorstand darf nach Anmeldeschluss und über die Höchstzahl hinaus eintragen
        response, before = rsvp.save_response(
            event,
            membership,
            status=v["status"],
            guests=v["guests"],
            note=v["note"],
            source=EventResponse.Source.BOARD,
            user=request.user,
            enforce_capacity=False,
        )
        self.audit(
            "update",
            event,
            {
                f"Rückmeldung {membership.person}": [
                    _response_label(before["status"], before["guests"]) if before else None,
                    _response_label(response.status, response.guests),
                ]
            },
        )
        return Response(response_data(response))


def _lock_event(pk: int) -> None:
    """Termin bis zum Ende der Transaktion sperren: Alle Rückmeldungen (Mitglied und
    Vorstand) zu einem Termin laufen nacheinander und sehen den aktuellen Stand."""
    Event.objects.select_for_update().filter(pk=pk).values_list("pk").first()


class _ResponseDetail(_ResponsesMixin, APIView):
    @transaction.atomic
    def delete(self, request, pk: int, membership_id: int, **kwargs):
        _lock_event(pk)
        event, scope = self.scoped_event(pk)
        # Rückmeldungen inzwischen nicht mehr Eingeladener (z. B. ausgetreten) stehen in
        # der Gesamtliste und zählen mit: Sie müssen sich auch entfernen lassen.
        stale = (
            EventResponse.objects.filter(event=event, membership_id=membership_id)
            .select_related("membership__person")
            .first()
            if scope == "all"
            else None
        )
        if stale is not None and not rsvp.invited(event).filter(pk=membership_id).exists():
            membership = stale.membership
        else:
            membership = self.membership_in_scope(event, scope, membership_id)
        response = EventResponse.objects.filter(event=event, membership=membership).first()
        if response is not None:
            self.audit(
                "update",
                event,
                {
                    f"Rückmeldung {membership.person}": [
                        _response_label(response.status, response.guests),
                        None,
                    ]
                },
            )
            response.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _ResponseExport(_ResponsesMixin, APIView):
    """Teilnehmerliste als Excel (``type=xlsx``) oder PDF (``type=pdf``)."""

    def get(self, request, pk: int, **kwargs):
        event, scope = self.scoped_event(pk)
        answered, open_ = self.lists(event, scope)
        name = "".join(c if c.isalnum() else "-" for c in event.title)[:40].strip("-")
        if request.query_params.get("type") == "xlsx":
            content = participants.xlsx(event, answered, open_)
            response = HttpResponse(
                content,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="Teilnehmer-{name}.xlsx"'
            return response
        org = self.viewer.org
        chain = (
            [self.viewer.department, *org.ancestors()]
            if self.viewer.department
            else list(org.ancestors())
        )
        content = participants.pdf(event, chain, answered, open_)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Teilnehmer-{name}.pdf"'
        return response


class _MyResponse(APIView):
    """Mitgliederbereich: PUT zu- oder absagen · DELETE Rückmeldung zurücknehmen."""

    def _event(self, pk: int) -> Event:
        event = self.visible_event(pk)
        allowed, reason = rsvp.member_can_respond(event)
        if not allowed:
            raise serializers.ValidationError(
                reason or "Für diesen Termin gibt es keine Rückmeldung."
            )
        if not rsvp.is_invited(event, self.viewer.membership_id):
            raise PermissionDenied("Zu diesem Termin sind Sie nicht eingeladen.")
        return event

    @transaction.atomic
    def put(self, request, pk: int, **kwargs):
        # Erst sperren, dann prüfen: Gleichzeitige Zusagen dürfen die Höchstzahl nicht
        # überschreiten, und eine gerade gespeicherte Absage oder Frist gilt schon
        _lock_event(pk)
        event = self._event(pk)
        data = ResponseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        membership = Membership.objects.select_related("person").get(pk=self.viewer.membership_id)
        response, before = rsvp.save_response(
            event,
            membership,
            status=v["status"],
            guests=v["guests"],
            note=v["note"],
            source=EventResponse.Source.MEMBER,
            user=request.user,
        )
        self.audit(
            "update",
            event,
            {
                f"Rückmeldung {membership.person}": [
                    _response_label(before["status"], before["guests"]) if before else None,
                    _response_label(response.status, response.guests),
                ]
            },
        )
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url))

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        _lock_event(pk)
        event = self._event(pk)
        response = EventResponse.objects.filter(
            event=event, membership_id=self.viewer.membership_id
        ).first()
        if response is not None:
            self.audit(
                "update",
                event,
                {
                    f"Rückmeldung {response.membership.person}": [
                        _response_label(response.status, response.guests),
                        None,
                    ]
                },
            )
            response.delete()
        event = self.visible_event(event.pk)
        return Response(event_data(event, self.viewer, self.base_url))


# --- Kalenderdateien ---

FEED_DAYS_BACK = 30
FEED_DAYS_AHEAD = 400


def _ics_response(body: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class _EventIcs(APIView):
    """Einzelnen Termin (bzw. die kommenden Termine einer Serie) als Kalenderdatei."""

    def get(self, request, pk: int, **kwargs):
        event = self.visible_event(pk)
        now = timezone.now()
        items = occurrences(
            Event.objects.filter(pk=event.pk).select_related(
                "organization", "department", "category"
            ),
            min(event.starts_at, now - datetime.timedelta(days=FEED_DAYS_BACK)),
            now + datetime.timedelta(days=FEED_DAYS_AHEAD),
        )
        body = ical.calendar(event.title, items, request.get_host().split(":")[0])
        return _ics_response(body, "termin.ics")


def feed_data(request, feed: PersonalCalendar | None) -> dict:
    if feed is None:
        return {"ics_url": None}
    return {
        "ics_url": request.build_absolute_uri(reverse("personal-calendar-ics", args=[feed.key]))
    }


class PortalFeedView(PortalCalendarMixin, APIView):
    """Persönliches Kalender-Abo: GET Link · PUT anlegen oder erneuern · DELETE abschalten."""

    def get(self, request, **kwargs):
        feed = PersonalCalendar.objects.filter(access=self.access).first()
        return Response(feed_data(request, feed))

    @transaction.atomic
    def put(self, request, **kwargs):
        feed, created = PersonalCalendar.objects.get_or_create(
            access=self.access,
            defaults={"organization": self.viewer.org, "key": PersonalCalendar.new_key()},
        )
        if not created:
            feed.key = PersonalCalendar.new_key()
            feed.save(update_fields=["key"])
        return Response(feed_data(request, feed))

    @transaction.atomic
    def delete(self, request, **kwargs):
        PersonalCalendar.objects.filter(access=self.access).delete()
        return Response(feed_data(request, None))


class PersonalCalendarIcsView(APIView):
    """Persönliches Kalender-Abo ohne Anmeldung (Link mit geheimem Schlüssel)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str):
        from portal.services import portal_accesses

        with rls_bypass():
            feed = (
                PersonalCalendar.objects.select_related(
                    "access__organization", "access__organization__parent", "access__user"
                )
                .filter(key=key)
                .first()
            )
            if feed is None:
                raise Http404
            access = feed.access
            club = access.organization
            # Zugang weg, Mitgliederbereich aus oder Konto gesperrt: keine Termine mehr
            if (
                not access.user.is_active
                or not club.is_active
                or access.pk not in {a.pk for a in portal_accesses(access.user)}
                or not services.module_on(club)
            ):
                raise Http404
            membership = Membership.objects.filter(pk=access.membership_id).first()
            on = today()
            if membership is None or membership.current_period(on) is None:
                raise Http404
            depts = list(
                DepartmentMembership.objects.filter(
                    membership_id=access.membership_id, valid_from__lte=on
                )
                .exclude(valid_until__lt=on)
                .values_list("department_id", flat=True)
            )
            viewer = services.member_viewer(club, depts, access.membership_id)
            now = timezone.now()
            items = occurrences(
                viewer.events(),
                now - datetime.timedelta(days=FEED_DAYS_BACK),
                now + datetime.timedelta(days=FEED_DAYS_AHEAD),
            )
        body = ical.calendar(
            club.name, items, request.get_host().split(":")[0], description=_imprint_note(club)
        )
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="termine.ics"'
        response["Cache-Control"] = "private, max-age=300"
        return response


# Vorstand
class OrgSharingView(OrgCalendarMixin, _Sharing):
    pass


class DeptSharingView(DeptCalendarMixin, _Sharing):
    pass


class OrgEventListView(OrgCalendarMixin, _EventList):
    pass


class OrgEventDetailView(OrgCalendarMixin, _EventDetail):
    pass


class OrgEventNotifyView(OrgCalendarMixin, _EventNotify):
    pass


class OrgEventProjectView(OrgCalendarMixin, APIView):
    """Termin einer Veranstaltung (Finanzen) zuordnen, eine neue dafür anlegen oder lösen.

    ``{"project": id}`` zuordnen, ``{"project": null}`` lösen, ``{"create": true}``
    neue Veranstaltung mit Titel und Datum des Termins anlegen und zuordnen.
    """

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        from finance.models import Project

        event = self.own_event(pk)
        if self.viewer.finance != "edit":
            raise PermissionDenied("Dafür fehlt dir das Recht, die Kasse zu bearbeiten.")
        before = event.project.name if event.project else None
        if request.data.get("create"):
            start = timezone.localtime(event.starts_at).date()
            end = timezone.localtime(event.ends_at).date() if event.ends_at else start
            if event.all_day and end > start:
                end -= datetime.timedelta(days=1)  # Ende ganztägig = Folgetag 0:00
            project = Project.objects.create(
                organization=self.org,
                name=event.title[:200],
                starts_on=start,
                ends_on=end if end > start else None,
                created_by=request.user,
            )
            record(self.org, request.user, "create", project, {"Name": [None, project.name]})
        elif request.data.get("project") is None:
            project = None
        else:
            try:
                wanted = int(request.data["project"])
                project = Project.objects.get(organization=self.org, pk=wanted)
            except (Project.DoesNotExist, TypeError, ValueError) as exc:
                raise serializers.ValidationError({"project": "Unbekannte Veranstaltung."}) from exc
        event.project = project
        event.save(update_fields=["project"])
        after = project.name if project else None
        if before != after:
            self.audit("update", event, {"Veranstaltung": [before, after]})
        event = self.visible_event(pk)
        return Response(event_data(event, self.viewer, self.base_url))


class OrgEventOccurrenceView(OrgCalendarMixin, _EventOccurrence):
    pass


class OrgAttachmentListView(OrgCalendarMixin, _AttachmentList):
    pass


class OrgAttachmentView(OrgCalendarMixin, _Attachment):
    pass


class OrgProgramView(OrgCalendarMixin, _Program):
    pass


class OrgCategoriesView(OrgCalendarMixin, _Categories):
    pass


class OrgCategoryDetailView(OrgCalendarMixin, _CategoryDetail):
    pass


class OrgPublicationView(OrgCalendarMixin, _Publication):
    pass


class OrgResponsesView(OrgCalendarMixin, _Responses):
    pass


class OrgResponseDetailView(OrgCalendarMixin, _ResponseDetail):
    pass


class OrgResponseExportView(OrgCalendarMixin, _ResponseExport):
    pass


class OrgEventIcsView(OrgCalendarMixin, _EventIcs):
    pass


# Abteilung
class DeptEventListView(DeptCalendarMixin, _EventList):
    pass


class DeptEventDetailView(DeptCalendarMixin, _EventDetail):
    pass


class DeptEventNotifyView(DeptCalendarMixin, _EventNotify):
    pass


class DeptEventOccurrenceView(DeptCalendarMixin, _EventOccurrence):
    pass


class DeptAttachmentListView(DeptCalendarMixin, _AttachmentList):
    pass


class DeptAttachmentView(DeptCalendarMixin, _Attachment):
    pass


class DeptProgramView(DeptCalendarMixin, _Program):
    pass


class DeptPublicationView(DeptCalendarMixin, _Publication):
    pass


class DeptResponsesView(DeptCalendarMixin, _Responses):
    pass


class DeptResponseDetailView(DeptCalendarMixin, _ResponseDetail):
    pass


class DeptResponseExportView(DeptCalendarMixin, _ResponseExport):
    pass


class DeptEventIcsView(DeptCalendarMixin, _EventIcs):
    pass


# Mitgliederbereich (nur lesen)
class PortalEventListView(PortalCalendarMixin, _EventList):
    http_method_names = ["get", "head", "options"]


class PortalEventDetailView(PortalCalendarMixin, _EventDetail):
    http_method_names = ["get", "head", "options"]


class PortalAttachmentView(PortalCalendarMixin, _Attachment):
    http_method_names = ["get", "head", "options"]


class PortalProgramView(PortalCalendarMixin, _Program):
    pass


class PortalMyResponseView(PortalCalendarMixin, _MyResponse):
    pass


class PortalEventIcsView(PortalCalendarMixin, _EventIcs):
    pass


# --- öffentlicher Link ohne Anmeldung ---

PUBLIC_DAYS_BACK = 30
PUBLIC_DAYS_AHEAD = 400


def _public(key: str) -> tuple[CalendarPublication, list[Occurrence]]:
    with rls_bypass():
        pub = (
            CalendarPublication.objects.select_related(
                "organization", "organization__parent", "department"
            )
            .filter(public_key=key, is_public=True)
            .first()
        )
        # Deaktivierte Organisation oder Untereinheit: Abo gesperrt (Audit B-V05)
        if (
            pub is None
            or not pub.organization.is_active
            or (pub.department is not None and not pub.department.is_active)
            or not services.module_on(pub.organization)
        ):
            raise Http404
        viewer = services.Viewer(pub.organization, pub.department, kind="public")
        now = timezone.now()
        items = occurrences(
            viewer.events(),
            now - datetime.timedelta(days=PUBLIC_DAYS_BACK),
            now + datetime.timedelta(days=PUBLIC_DAYS_AHEAD),
        )
    return pub, items


def _cors(response):
    response["Access-Control-Allow-Origin"] = "*"
    response["Cache-Control"] = "public, max-age=300"
    return response


class PublicCalendarView(APIView):
    """Öffentliche Termine als JSON, z. B. für die Vereinswebseite."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str):
        pub, items = _public(key)
        owner = pub.department or pub.organization
        data = {
            "name": owner.name,
            "organization": pub.organization.name,
            "department": pub.department.name if pub.department else None,
            "ics_url": request.build_absolute_uri(reverse("public-calendar-ics", args=[key])),
            "events": [
                {
                    "id": o.key,
                    "title": o.event.title,
                    "starts_at": o.starts_at,
                    "ends_at": o.ends_at,
                    "all_day": o.event.all_day,
                    "location": o.event.location,
                    "address": o.event.address,
                    "description": o.event.description,
                    "category": o.event.category.name if o.event.category_id else None,
                    "color": o.event.category.color if o.event.category_id else None,
                    "is_cancelled": o.is_cancelled,
                    "note": o.note,
                }
                for o in items
            ],
        }
        return _cors(Response(data))


def _imprint_note(org) -> str:
    from organizations.imprint import page_urls

    return f"Impressum: {page_urls(org)['imprint']}"


class PublicCalendarIcsView(APIView):
    """Öffentliche Termine als Kalender-Abo (iCal)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str):
        pub, items = _public(key)
        owner = pub.department or pub.organization
        body = ical.calendar(
            owner.name, items, request.get_host().split(":")[0], description=_imprint_note(owner)
        )
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="termine.ics"'
        return _cors(response)
