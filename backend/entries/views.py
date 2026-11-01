"""Meldungen in der Verwaltung (Menü „Meldungen“).

Recht „Meldungen abgeben“ (``entries.submit``): Ausschreibungen erfassen, Meldungen
zusammenstellen und abgeben. Mitglieder auswählen darf nur, wer auch die Mitglieder
sehen darf (``members.view``); Gäste und vorhandene Einträge gehen ohne.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import (
    DEPT_ENTRIES_SUBMIT,
    DEPT_MEMBERS_VIEW,
    ENTRIES_MANAGE,
    ENTRIES_SUBMIT,
    EVENTS_MANAGE,
    MEMBERS_VIEW,
)
from audit.log import diff, record, snapshot
from core.api_base import OrgScopedMixin
from core.tenancy import scope_of, set_rls
from members.models import Membership
from organizations.models import Department, Organization

from . import documents, services
from .models import Call, CallBlock, Entry, EntryAnswer, EntryPerson, EntryTeam, EntryVersion

MODULE = "entries"


class _Mixin(OrgScopedMixin):
    """Grundlage aller Ansichten. Drei Zugänge (Schritt 3):

    - ``/orgs/<org>/entries/…``: die Einheit meldet selbst oder schreibt aus.
    - ``/orgs/<org>/entries/units/<unit>/…``: der Veranstalter bearbeitet die Meldung einer
      seiner Untereinheiten (Recht ``entries.manage``).
    - ``/depts/<dept>/entries/…``: die Untereinheit meldet in ihrem Bereich
      (Abteilungsrecht ``dept.entries.submit``). Die Daten liegen beim Veranstalter.
    """

    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    #: Untereinheit, deren Meldung bearbeitet wird (Ausschreibung von oben)
    department: Department | None = None
    #: Zugriff aus dem Bereich der Untereinheit
    unit_side = False
    _unit_id = None
    _dept_id = None

    def dispatch(self, request, *args, **kwargs):
        self._unit_id = kwargs.pop("unit_id", None)
        self._dept_id = kwargs.pop("dept_id", None)
        if self._dept_id is not None:
            kwargs["org_id"] = (
                Organization.objects.filter(pk=self._dept_id)
                .values_list("organization_id", flat=True)
                .first()
                or 0
            )
        return super().dispatch(request, *args, **kwargs)

    def initial(self, request, *args, **kwargs):
        if self._dept_id is not None:
            APIView.initial(self, request, *args, **kwargs)
            self._init_unit_side(request)
            return
        super().initial(request, *args, **kwargs)
        if MODULE not in (self.org.enabled_modules or []):
            raise NotFound(gettext("Das Modul Meldungen ist nicht freigeschaltet."))
        if not self.org_permissions & {ENTRIES_SUBMIT, ENTRIES_MANAGE}:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
        if self._unit_id is not None:
            if ENTRIES_MANAGE not in self.org_permissions:
                raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
            self.department = get_object_or_404(Department, pk=self._unit_id, organization=self.org)

    def _init_unit_side(self, request):
        from portal.services import department_contexts

        ctx = department_contexts(request.user).get(int(self._dept_id))
        if ctx is None:
            raise NotFound()
        if MODULE not in (ctx.club.enabled_modules or []):
            raise NotFound(gettext("Das Modul Meldungen ist nicht freigeschaltet."))
        if DEPT_ENTRIES_SUBMIT not in ctx.permissions:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
        self.org = ctx.club
        self.department = ctx.department
        self.unit_side = True
        # Mitglieder auswählen: nur aus der eigenen Untereinheit (Datenschutz)
        self.org_permissions = {ENTRIES_SUBMIT} | (
            {MEMBERS_VIEW} if DEPT_MEMBERS_VIEW in ctx.permissions else set()
        )
        set_rls(self.org.pk, request.user.pk, scope_id=scope_of(self.org.pk))

    @property
    def can_pick_members(self) -> bool:
        return MEMBERS_VIEW in self.org_permissions

    def require_organizer(self, call: Call | None = None, *, internal: bool | None = None) -> None:
        """Ausschreibung anlegen oder ändern: nicht aus einer Untereinheit heraus; eine
        Ausschreibung an Untereinheiten braucht ``entries.manage``."""
        if self.unit_side or self.department is not None:
            raise PermissionDenied(gettext("Die Ausschreibung ändert nur der Veranstalter."))
        if internal is None:
            internal = call.internal if call else False
        needed = ENTRIES_MANAGE if internal else ENTRIES_SUBMIT
        if needed not in self.org_permissions:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))

    def call(self, pk) -> Call:
        call = get_object_or_404(Call, pk=pk, organization=self.org)
        if self.department is not None and (
            not call.internal or self.department.pk not in services.addressed_units(call)
        ):
            raise NotFound()
        if self.department is None and call.internal and ENTRIES_MANAGE not in self.org_permissions:
            raise NotFound()
        return call

    def find_entry(self, call: Call) -> Entry | None:
        return Entry.objects.filter(
            call=call, organization=self.org, department=self.department
        ).first()

    def entry(self, call_id, *, create: bool = False) -> Entry:
        call = self.call(call_id)
        entry = self.find_entry(call)
        if entry is None:
            if not create:
                raise NotFound(gettext("Zu dieser Ausschreibung gibt es noch keine Meldung."))
            if call.internal and self.department is None:
                raise ValidationError(gettext("Zu dieser Ausschreibung melden die Untereinheiten."))
            entry = Entry.objects.create(
                organization=self.org, call=call, department=self.department
            )
            record(self.org, self.request.user, "create", entry, diff({}, snapshot(entry)))
        return entry

    def open_entry(self, call_id) -> Entry:
        """Meldung zum Bearbeiten (legt den Entwurf beim ersten Mal an)."""
        entry = self.entry(call_id, create=True)
        if entry.status == Entry.Status.WITHDRAWN:
            raise ValidationError(gettext("Die Meldung ist zurückgezogen."))
        return entry


# --- Ausschreibungen ---

CALL_FIELDS = (
    "title",
    "organizer",
    "organizer_address",
    "organizer_email",
    "salutation",
    "description",
    "location",
)
DATE_FIELDS = ("date", "deadline", "reference_date")


def _block_data(b: CallBlock) -> dict:
    return {
        "id": b.pk,
        "kind": b.kind,
        "label": b.label,
        "help_text": b.help_text,
        "required": b.required,
        "settings": b.settings,
        "sort_order": b.sort_order,
    }


def _call_data(call: Call, entry: Entry | None = None) -> dict:
    return {
        "id": call.pk,
        "title": call.title,
        "organizer": call.organizer,
        "organizer_address": call.organizer_address,
        "organizer_email": call.organizer_email,
        "salutation": call.salutation,
        "description": call.description,
        "date": call.date,
        "location": call.location,
        "deadline": call.deadline,
        "reference_date": call.reference_date,
        "person_fields": call.person_fields,
        "conditions": call.conditions,
        "fee_amount": str(call.fee_amount) if call.fee_amount is not None else None,
        "fee_per": call.fee_per,
        "changes_after_deadline": call.changes_after_deadline,
        "create_competition": call.create_competition,
        "copied_from": call.copied_from_id,
        "event_id": call.event_id,
        "internal": call.internal,
        "units": call.units,
        "strict": call.strict,
        "competition": call.competition_id,
        "entry_status": entry.status if entry else None,
        "entry_changed": entry.changed if entry else False,
        "entry_question": entry.question if entry else "",
    }


def _clean_call(org, data: dict, instance: Call | None) -> dict:
    out: dict = {}
    limits = {f.name: f.max_length for f in Call._meta.fields}
    for f in CALL_FIELDS:
        if f in data:
            value = str(data[f] or "").strip()
            if limits.get(f) and len(value) > limits[f]:
                raise ValidationError({f: gettext("Höchstens {x} Zeichen.").format(x=limits[f])})
            out[f] = value
    if instance is None or "title" in out:
        if not out.get("title", instance.title if instance else ""):
            raise ValidationError({"title": gettext("Bitte einen Titel angeben.")})
    internal = bool(data.get("internal")) if instance is None else instance.internal
    if internal and not out.get("organizer", instance.organizer if instance else ""):
        out["organizer"] = org.name[:200]
    if instance is None or "organizer" in out:
        if not out.get("organizer", instance.organizer if instance else ""):
            raise ValidationError({"organizer": gettext("Bitte den Veranstalter angeben.")})
    if out.get("organizer_email"):
        from django.core.exceptions import ValidationError as DjangoError
        from django.core.validators import validate_email

        try:
            validate_email(out["organizer_email"])
        except DjangoError:
            raise ValidationError(
                {"organizer_email": gettext("Keine gültige E-Mail-Adresse.")}
            ) from None
    for f in DATE_FIELDS:
        if f in data:
            raw = data[f]
            if raw in (None, ""):
                out[f] = None
            else:
                d = parse_date(str(raw))
                if d is None:
                    raise ValidationError({f: gettext("Bitte ein Datum angeben.")})
                out[f] = d
    if "person_fields" in data:
        out["person_fields"] = services.clean_person_fields(org, data["person_fields"])
    if "conditions" in data:
        out["conditions"] = services.clean_conditions(org, data["conditions"])
    if "fee_amount" in data:
        raw = data["fee_amount"]
        if raw in (None, ""):
            out["fee_amount"] = None
        else:
            try:
                amount = Decimal(str(raw).replace(",", "."))
            except InvalidOperation:
                raise ValidationError(
                    {"fee_amount": gettext("Bitte einen Betrag angeben.")}
                ) from None
            if amount < 0 or amount >= Decimal("10000000"):
                raise ValidationError({"fee_amount": gettext("Ungültiger Betrag.")})
            out["fee_amount"] = amount.quantize(Decimal("0.01"))
    if "fee_per" in data:
        if data["fee_per"] not in Call.FeePer.values:
            raise ValidationError({"fee_per": gettext("Ungültige Angabe.")})
        out["fee_per"] = data["fee_per"]
    if "changes_after_deadline" in data:
        if data["changes_after_deadline"] not in Call.Changes.values:
            raise ValidationError({"changes_after_deadline": gettext("Ungültige Angabe.")})
        out["changes_after_deadline"] = data["changes_after_deadline"]
    if "create_competition" in data:
        out["create_competition"] = bool(data["create_competition"])
    if "strict" in data:
        out["strict"] = bool(data["strict"])
    if "units" in data:
        out["units"] = services.clean_units(org, data["units"])
    if "competition" in data:
        raw = data["competition"]
        if raw in (None, ""):
            out["competition"] = None
        else:
            from competitions.models import Competition

            comp = Competition.objects.filter(pk=raw, organization=org, own=True).first()
            if comp is None:
                raise ValidationError({"competition": gettext("Unbekannter Wettbewerb.")})
            out["competition"] = comp
    return out


class CallsView(_Mixin, APIView):
    """GET: Ausschreibungen mit Zustand der eigenen Meldung · POST: neue Ausschreibung
    (``template`` = „mannschaften“ legt einen Baustein Mannschaften an)."""

    def get(self, request, org_id: int):
        entries = {
            e.call_id: e
            for e in Entry.objects.filter(organization=self.org, department=self.department)
        }
        calls = Call.objects.filter(organization=self.org)
        if self.department is not None:
            calls = [
                c
                for c in calls.filter(internal=True)
                if self.department.pk in services.addressed_units(c)
            ]
        elif ENTRIES_MANAGE not in self.org_permissions:
            calls = calls.filter(internal=False)
        out = []
        for c in calls:
            data = _call_data(c, entries.get(c.pk))
            if c.internal and self.department is None:
                data["unit_counts"] = services.unit_counts(c)
            out.append(data)
        return Response(out)

    @transaction.atomic
    def post(self, request, org_id: int):
        internal = bool(request.data.get("internal"))
        self.require_organizer(internal=internal)
        values = _clean_call(self.org, request.data, None)
        # Fremder Veranstalter: kein Wettbewerb im eigenen Verein, außer ausdrücklich gewählt
        # (Ralf, 01.11.); bei Ausschreibungen an die eigenen Untereinheiten sinnvoll an
        values.setdefault("create_competition", internal)
        call = Call.objects.create(organization=self.org, internal=internal, **values)
        record(self.org, request.user, "create", call, diff({}, snapshot(call)))
        if request.data.get("template") == "mannschaften":
            b = CallBlock.objects.create(
                organization=self.org,
                call=call,
                kind=CallBlock.Kind.TEAMS,
                label="Mannschaften",
                required=True,
                settings={"min_teams": 1, "positions": []},
                sort_order=1,
            )
            record(self.org, request.user, "create", b, diff({}, snapshot(b)))
        return Response(_call_detail(self, call), status=status.HTTP_201_CREATED)


def _call_detail(view: _Mixin, call: Call) -> dict:
    entry = view.find_entry(call)
    data = _call_data(call, entry)
    data["blocks"] = [_block_data(b) for b in call.blocks.all()]
    data["has_versions"] = bool(entry and entry.versions.exists())
    # Termin für die Interessenabfrage (Schritt 2)
    from competitions.event_views import event_info
    from events import services as event_services

    on = event_services.module_on(view.org)
    data["event"] = event_info(call.event) if call.event_id else None
    data["calendar"] = {"on": on, "can_create": on and EVENTS_MANAGE in view.org_permissions}
    return data


class CallView(_Mixin, APIView):
    """GET: Ausschreibung mit Bausteinen · PATCH: ändern · DELETE: löschen (nur ohne
    abgegebene Meldung)."""

    def get(self, request, org_id: int, call_id: int):
        return Response(_call_detail(self, self.call(call_id)))

    @transaction.atomic
    def patch(self, request, org_id: int, call_id: int):
        call = Call.objects.select_for_update().get(pk=self.call(call_id).pk)
        self.require_organizer(call)
        before = snapshot(call)
        for k, v in _clean_call(self.org, request.data, call).items():
            setattr(call, k, v)
        call.save()
        changes = diff(before, snapshot(call))
        if changes:
            record(self.org, request.user, "update", call, changes)
            entry = self.find_entry(call)
            if entry:
                services.mark_changed(entry)
        return Response(_call_detail(self, call))

    @transaction.atomic
    def delete(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        self.require_organizer(call)
        if EntryVersion.objects.filter(entry__call=call).exists():
            raise ValidationError(
                gettext(
                    "Zu dieser Ausschreibung gibt es eine abgegebene Meldung; sie bleibt als Beleg."
                )
            )
        record(self.org, request.user, "delete", call, diff(snapshot(call), {}))
        call.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CallCopyView(_Mixin, APIView):
    """POST {title?}: Ausschreibung für das nächste Jahr kopieren (ohne Meldung)."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        self.require_organizer(call)
        title = str(request.data.get("title", "") or "").strip()[:200]
        new = services.copy_call(call, title=title)
        record(self.org, request.user, "create", new, diff({}, snapshot(new)))
        return Response(_call_detail(self, new), status=status.HTTP_201_CREATED)


def _clean_block(data: dict, block: CallBlock | None) -> dict:
    out: dict = {}
    kind = data.get("kind", block.kind if block else None)
    if block is None:
        if kind not in CallBlock.Kind.values:
            raise ValidationError({"kind": gettext("Unbekannte Art des Bausteins.")})
        out["kind"] = kind
    elif "kind" in data and data["kind"] != block.kind:
        raise ValidationError({"kind": gettext("Die Art eines Bausteins lässt sich nicht ändern.")})
    if "label" in data or block is None:
        label = str(data.get("label", "") or "").strip()[:200]
        if not label:
            label = CallBlock.Kind(kind).label
        out["label"] = label
    if "help_text" in data:
        out["help_text"] = str(data["help_text"] or "").strip()[:300]
    if "required" in data:
        out["required"] = bool(data["required"])
    if "settings" in data or block is None:
        out["settings"] = services.clean_block_settings(kind, data.get("settings"))
    if "sort_order" in data:
        try:
            out["sort_order"] = max(0, min(int(data["sort_order"]), 1000))
        except (TypeError, ValueError):
            raise ValidationError({"sort_order": gettext("Ungültige Angabe.")}) from None
    return out


class BlocksView(_Mixin, APIView):
    """POST {kind, label, settings, required}: Baustein hinzufügen."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        self.require_organizer(call)
        if call.blocks.count() >= services.MAX_BLOCKS:
            raise ValidationError(
                gettext("Höchstens {MAX_BLOCKS} Bausteine.").format(MAX_BLOCKS=services.MAX_BLOCKS)
            )
        values = _clean_block(request.data, None)
        values.setdefault("sort_order", (call.blocks.aggregate(m=Max("sort_order"))["m"] or 0) + 1)
        b = CallBlock.objects.create(organization=self.org, call=call, **values)
        record(self.org, request.user, "create", b, diff({}, snapshot(b)))
        return Response(_block_data(b), status=status.HTTP_201_CREATED)


class BlockView(_Mixin, APIView):
    """PATCH: Baustein ändern · DELETE: entfernen (samt Einträgen im Entwurf; nicht, wenn
    die Meldung schon abgegeben ist und der Baustein Einträge hat)."""

    def _get(self, call_id, pk) -> CallBlock:
        call = self.call(call_id)
        self.require_organizer(call)
        return get_object_or_404(CallBlock, pk=pk, call=call)

    @transaction.atomic
    def patch(self, request, org_id: int, call_id: int, pk: int):
        b = self._get(call_id, pk)
        before = snapshot(b)
        for k, v in _clean_block(request.data, b).items():
            setattr(b, k, v)
        b.save()
        changes = diff(before, snapshot(b))
        if changes:
            record(self.org, request.user, "update", b, changes)
        return Response(_block_data(b))

    @transaction.atomic
    def delete(self, request, org_id: int, call_id: int, pk: int):
        b = self._get(call_id, pk)
        used = (
            EntryTeam.objects.filter(block=b).exists()
            or EntryPerson.objects.filter(block=b).exists()
            or EntryAnswer.objects.filter(block=b).exists()
        )
        if used and EntryVersion.objects.filter(entry__call=b.call).exists():
            raise ValidationError(
                gettext(
                    "Der Baustein enthält schon abgegebene Einträge. Bitte erst die Einträge "
                    "entfernen."
                )
            )
        record(self.org, request.user, "delete", b, diff(snapshot(b), {}))
        b.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Meldung ---


def _person_data(p: EntryPerson) -> dict:
    return {
        "id": p.pk,
        "block": p.block_id,
        "team": p.team_id,
        "membership": p.membership_id,
        "name": p.name,
        "club": p.club,
        "guest": p.membership_id is None,
        "position": p.position,
        "substitute": p.substitute,
        "sort_order": p.sort_order,
    }


def _version_data(v: EntryVersion) -> dict:
    return {
        "id": v.pk,
        "number": v.number,
        "kind": v.kind,
        "kind_label": v.get_kind_display(),
        "channel": v.channel,
        "channel_label": v.get_channel_display(),
        "sent_to": v.sent_to,
        "changes": v.changes,
        "reason": v.reason,
        "signed_by": v.signed_by,
        "signed_function": v.signed_function,
        "created_at": v.created_at,
        "shortened": v.shortened_at is not None,
    }


def _entry_detail(view: _Mixin, entry: Entry) -> dict:
    hints = services.check(entry)
    return {
        "id": entry.pk,
        "call": entry.call_id,
        "status": entry.status,
        "status_label": entry.get_status_display(),
        "changed": entry.changed,
        "note": entry.note,
        "confirmed_note": entry.confirmed_note,
        "question": entry.question,
        "unit": entry.department_id,
        "unit_name": entry.department.name if entry.department_id else "",
        "competition": entry.competition_id
        or (entry.call.competition_id if entry.call.internal else None),
        "teams": [
            {"id": t.pk, "block": t.block_id, "name": t.name, "sort_order": t.sort_order}
            for t in entry.teams.all()
        ],
        "persons": [_person_data(p) for p in entry.persons.all()],
        "answers": {str(a.block_id): a.value for a in entry.answers.all()},
        "hints": [h.as_dict() for h in hints],
        "versions": [_version_data(v) for v in entry.versions.all()],
        "after_deadline": services.after_deadline(entry.call),
        "can_pick_members": view.can_pick_members,
        "competitions_enabled": services.competitions_enabled(view.org),
    }


class EntryView(_Mixin, APIView):
    """GET: eigene Meldung (``null``, wenn es noch keine gibt) · POST: Entwurf anlegen ·
    PATCH {note}: Notiz."""

    def get(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        entry = self.find_entry(call)
        if entry is None:
            # DRF schreibt für None einen leeren Rumpf; der Browser braucht ein echtes JSON-null
            return HttpResponse(b"null", content_type="application/json")
        return Response(_entry_detail(self, entry))

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        entry = self.entry(call_id, create=True)
        return Response(_entry_detail(self, entry), status=status.HTTP_201_CREATED)

    @transaction.atomic
    def patch(self, request, org_id: int, call_id: int):
        entry = self.entry(call_id)
        before = snapshot(entry)
        if "note" in request.data:
            entry.note = str(request.data["note"] or "").strip()[:2000]
        entry.save()
        changes = diff(before, snapshot(entry))
        if changes:
            record(self.org, request.user, "update", entry, changes)
        return Response(_entry_detail(self, entry))


def _check_change_allowed(entry: Entry, *, substitute_only: bool) -> None:
    """Nach Meldeschluss: je nach Ausschreibung keine Änderungen oder nur Ersatz."""
    call = entry.call
    if entry.status == Entry.Status.DRAFT or not services.after_deadline(call):
        return
    if call.changes_after_deadline == Call.Changes.FREE:
        return
    if call.changes_after_deadline == Call.Changes.SUBSTITUTE and substitute_only:
        return
    raise ValidationError(
        "Der Meldeschluss ist vorbei. "
        + (
            "Erlaubt ist nur noch der Ersatz von Personen."
            if call.changes_after_deadline == Call.Changes.SUBSTITUTE
            else "Änderungen sind nicht mehr vorgesehen."
        )
    )


def _block_of(entry: Entry, raw, kinds) -> CallBlock:
    try:
        block = CallBlock.objects.get(pk=int(raw), call=entry.call)
    except (TypeError, ValueError, CallBlock.DoesNotExist):
        raise ValidationError({"block": gettext("Unbekannter Baustein.")}) from None
    if block.kind not in kinds:
        raise ValidationError({"block": gettext("Dieser Baustein passt nicht.")})
    return block


class TeamsView(_Mixin, APIView):
    """POST {block, name?}: Mannschaft hinzufügen (Name vorbelegt mit Kurzname und
    römischer Zahl, z. B. „Hubertus I“)."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        entry = self.open_entry(call_id)
        _check_change_allowed(entry, substitute_only=False)
        block = _block_of(entry, request.data.get("block"), [CallBlock.Kind.TEAMS])
        if entry.teams.count() >= services.MAX_TEAMS:
            raise ValidationError(
                gettext("Höchstens {MAX_TEAMS} Mannschaften.").format(MAX_TEAMS=services.MAX_TEAMS)
            )
        name = str(request.data.get("name", "") or "").strip()[:100]
        existing = entry.teams.filter(block=block).count()
        if not name:
            unit = self.department or self.org
            short = unit.short_name or unit.name
            name = f"{short} {roman(existing + 1)}"[:100]
        last = entry.teams.aggregate(m=Max("sort_order"))["m"] or 0
        t = EntryTeam.objects.create(
            organization=self.org, entry=entry, block=block, name=name, sort_order=last + 1
        )
        record(self.org, request.user, "create", t, diff({}, snapshot(t)))
        services.mark_changed(entry)
        return Response(_entry_detail(self, entry), status=status.HTTP_201_CREATED)


def roman(n: int) -> str:
    out = ""
    for value, sign in (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ):
        while n >= value:
            out += sign
            n -= value
    return out


class TeamView(_Mixin, APIView):
    """PATCH {name?, sort_order?} · DELETE: Mannschaft samt Personen entfernen."""

    def _get(self, call_id, pk) -> tuple[Entry, EntryTeam]:
        entry = self.open_entry(call_id)
        return entry, get_object_or_404(EntryTeam, pk=pk, entry=entry)

    @transaction.atomic
    def patch(self, request, org_id: int, call_id: int, pk: int):
        entry, t = self._get(call_id, pk)
        _check_change_allowed(entry, substitute_only=False)
        before = snapshot(t)
        if "name" in request.data:
            name = str(request.data["name"] or "").strip()[:100]
            if not name:
                raise ValidationError({"name": gettext("Bitte einen Namen angeben.")})
            t.name = name
        if "sort_order" in request.data:
            try:
                t.sort_order = max(0, min(int(request.data["sort_order"]), 1000))
            except (TypeError, ValueError):
                raise ValidationError({"sort_order": gettext("Ungültige Angabe.")}) from None
        t.save()
        changes = diff(before, snapshot(t))
        if changes:
            record(self.org, request.user, "update", t, changes)
            services.mark_changed(entry)
        return Response(_entry_detail(self, entry))

    @transaction.atomic
    def delete(self, request, org_id: int, call_id: int, pk: int):
        entry, t = self._get(call_id, pk)
        _check_change_allowed(entry, substitute_only=False)
        record(self.org, request.user, "delete", t, diff(snapshot(t), {}))
        t.delete()
        services.mark_changed(entry)
        return Response(_entry_detail(self, entry))


def _membership(view: _Mixin, raw) -> Membership:
    if not view.can_pick_members:
        raise PermissionDenied(
            gettext("Mitglieder auswählen darf nur, wer die Mitglieder sehen darf.")
        )
    qs = Membership.objects.select_related("person").filter(
        organization=view.org, purged_at__isnull=True
    )
    if view.unit_side:
        # Aus dem Bereich der Untereinheit nur ihre eigenen Mitglieder
        qs = qs.filter(
            pk__in=services.unit_member_ids(view.org, view.department, timezone.localdate())
        )
    try:
        return qs.get(pk=int(raw))
    except (TypeError, ValueError, Membership.DoesNotExist):
        raise ValidationError({"membership": gettext("Unbekanntes Mitglied.")}) from None


def _member_name(m: Membership) -> str:
    return f"{m.person.first_name} {m.person.last_name}".strip()


class PersonsView(_Mixin, APIView):
    """POST {block, team?, membership | name+club, position?, substitute?}: Person melden."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        entry = self.open_entry(call_id)
        _check_change_allowed(entry, substitute_only=False)
        d = request.data
        block = _block_of(entry, d.get("block"), [CallBlock.Kind.TEAMS, CallBlock.Kind.PERSONS])
        team = None
        if block.kind == CallBlock.Kind.TEAMS:
            try:
                team = EntryTeam.objects.get(pk=int(d.get("team")), entry=entry, block=block)
            except (TypeError, ValueError, EntryTeam.DoesNotExist):
                raise ValidationError({"team": gettext("Bitte eine Mannschaft wählen.")}) from None
        if entry.persons.count() >= services.MAX_PERSONS:
            raise ValidationError(
                gettext("Höchstens {MAX_PERSONS} Personen.").format(
                    MAX_PERSONS=services.MAX_PERSONS
                )
            )
        values = _person_values(self, d, block, require_name=True)
        last = entry.persons.aggregate(m=Max("sort_order"))["m"] or 0
        p = EntryPerson.objects.create(
            organization=self.org,
            entry=entry,
            block=block,
            team=team,
            sort_order=last + 1,
            **values,
        )
        record(self.org, request.user, "create", p, diff({}, snapshot(p)))
        services.mark_changed(entry)
        return Response(_entry_detail(self, entry), status=status.HTTP_201_CREATED)


def _person_values(view: _Mixin, d: dict, block: CallBlock, require_name: bool) -> dict:
    out: dict = {}
    if d.get("membership"):
        m = _membership(view, d["membership"])
        out.update(membership=m, name=_member_name(m)[:200], club="")
    elif "name" in d or require_name:
        name = str(d.get("name", "") or "").strip()[:200]
        if not name:
            raise ValidationError(
                {"name": gettext("Bitte ein Mitglied wählen oder einen Namen angeben.")}
            )
        out.update(membership=None, name=name, club=str(d.get("club", "") or "").strip()[:200])
    elif "club" in d:
        out["club"] = str(d.get("club") or "").strip()[:200]
    if "position" in d:
        position = str(d["position"] or "").strip()[:100]
        allowed = (block.settings or {}).get("positions") or []
        if position and allowed and position not in allowed:
            raise ValidationError({"position": gettext("Unbekannte Aufgabe.")})
        out["position"] = position
    if "substitute" in d:
        out["substitute"] = bool(d["substitute"]) and block.kind == CallBlock.Kind.TEAMS
    return out


class PersonView(_Mixin, APIView):
    """PATCH {membership | name+club, position, substitute, sort_order, team}: ändern; ein
    anderes Mitglied auf demselben Platz ist ein Ersatz · DELETE: streichen."""

    def _get(self, call_id, pk) -> tuple[Entry, EntryPerson]:
        entry = self.open_entry(call_id)
        return entry, get_object_or_404(EntryPerson, pk=pk, entry=entry)

    @transaction.atomic
    def patch(self, request, org_id: int, call_id: int, pk: int):
        entry, p = self._get(call_id, pk)
        d = request.data
        only_person = set(d) <= {"membership", "name", "club"}
        _check_change_allowed(entry, substitute_only=only_person)
        before = snapshot(p)
        for k, v in _person_values(self, d, p.block, require_name=False).items():
            setattr(p, k, v)
        if "team" in d:
            try:
                p.team = EntryTeam.objects.get(pk=int(d["team"]), entry=entry, block=p.block)
            except (TypeError, ValueError, EntryTeam.DoesNotExist):
                raise ValidationError({"team": gettext("Unbekannte Mannschaft.")}) from None
        if "sort_order" in d:
            try:
                p.sort_order = max(0, min(int(d["sort_order"]), 10000))
            except (TypeError, ValueError):
                raise ValidationError({"sort_order": gettext("Ungültige Angabe.")}) from None
        p.save()
        changes = diff(before, snapshot(p))
        if changes:
            record(self.org, request.user, "update", p, changes)
            services.mark_changed(entry)
        return Response(_entry_detail(self, entry))

    @transaction.atomic
    def delete(self, request, org_id: int, call_id: int, pk: int):
        entry, p = self._get(call_id, pk)
        _check_change_allowed(entry, substitute_only=False)
        record(self.org, request.user, "delete", p, diff(snapshot(p), {}))
        p.delete()
        services.mark_changed(entry)
        return Response(_entry_detail(self, entry))


def _clean_answer(block: CallBlock, value):
    s = block.settings or {}
    if value in (None, "", []):
        return None
    if block.kind == CallBlock.Kind.NUMBER:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValidationError({"value": gettext("Bitte eine ganze Zahl angeben.")}) from None
        if s.get("min") is not None and n < s["min"]:
            raise ValidationError({"value": gettext("Mindestens {x}.").format(x=s["min"])})
        if s.get("max") is not None and n > s["max"]:
            raise ValidationError({"value": gettext("Höchstens {x}.").format(x=s["max"])})
        return n
    if block.kind == CallBlock.Kind.CHOICE:
        options = s.get("options") or []
        values = value if isinstance(value, list) else [value]
        values = [str(v) for v in values]
        if any(v not in options for v in values):
            raise ValidationError({"value": gettext("Unbekannte Antwort.")})
        if not s.get("multiple") and len(values) > 1:
            raise ValidationError({"value": gettext("Nur eine Antwort möglich.")})
        return values if s.get("multiple") else values[0]
    text = str(value).strip()
    if len(text) > 2000:
        raise ValidationError({"value": gettext("Höchstens 2000 Zeichen.")})
    return text


class AnswerView(_Mixin, APIView):
    """PUT {block, value}: Angabe zu einem Baustein Zahl, Auswahl oder Text."""

    @transaction.atomic
    def put(self, request, org_id: int, call_id: int):
        entry = self.open_entry(call_id)
        _check_change_allowed(entry, substitute_only=False)
        block = _block_of(
            entry,
            request.data.get("block"),
            [CallBlock.Kind.NUMBER, CallBlock.Kind.CHOICE, CallBlock.Kind.TEXT],
        )
        value = _clean_answer(block, request.data.get("value"))
        answer = EntryAnswer.objects.filter(entry=entry, block=block).first()
        old = answer.value if answer else None
        if value is None:
            if answer:
                answer.delete()
        elif answer:
            answer.value = value
            answer.save()
        else:
            answer = EntryAnswer.objects.create(
                organization=self.org, entry=entry, block=block, value=value
            )
        if old != value:
            record(
                self.org,
                request.user,
                "update",
                entry,
                {block.label: [old, value]},
            )
            services.mark_changed(entry)
        return Response(_entry_detail(self, entry))


class CandidatesView(_Mixin, APIView):
    """GET ?suche=: Mitglieder zur Auswahl, aus der kompletten Mitgliederliste (Ralf
    2026-11-01), mit Untereinheit und Geburtsjahr; ?alle=1: auch Ausgetretene."""

    def get(self, request, org_id: int, call_id: int):
        if not self.can_pick_members:
            raise PermissionDenied(
                gettext("Mitglieder auswählen darf nur, wer die Mitglieder sehen darf.")
            )
        call = self.call(call_id)
        term = request.query_params.get("suche", "").strip()
        if len(term) < 2:
            return Response([])
        on = services.reference_date(call)
        qs = Membership.objects.filter(organization=self.org, purged_at__isnull=True)
        if self.unit_side:
            qs = qs.filter(pk__in=services.unit_member_ids(self.org, self.department, on))
        if request.query_params.get("alle") != "1":
            qs = (
                qs.filter(periods__entry_date__lte=on)
                .filter(Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=on))
                .distinct()
            )
        for word in term.split()[:3]:
            cond = Q()
            for v in _umlaut_variants(word):
                cond |= Q(person__first_name__icontains=v) | Q(person__last_name__icontains=v)
            qs = qs.filter(cond)
        rows = list(
            qs.select_related("person").order_by("person__last_name", "person__first_name")[:15]
        )
        infos = services.person_infos(self.org, [m.pk for m in rows], on)
        entry = self.find_entry(call)
        taken = (
            set(entry.persons.filter(membership__in=rows).values_list("membership_id", flat=True))
            if entry
            else set()
        )
        from .event_views import response_status

        responded = response_status(call, [m.pk for m in rows])
        return Response(
            [
                {
                    "membership": m.pk,
                    "name": _member_name(m),
                    "first_name": m.person.first_name,
                    "last_name": m.person.last_name,
                    "birth_year": m.person.birth_date.year if m.person.birth_date else None,
                    "unit_name": infos[m.pk].unit_name if m.pk in infos else "",
                    "active": infos[m.pk].active_member if m.pk in infos else False,
                    "taken": m.pk in taken,
                    "response": responded.get(m.pk),
                }
                for m in rows
            ]
        )


def _umlaut_variants(word: str) -> set[str]:
    w = word.lower()
    pairs = (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("ss", "ß"))
    out = {w}
    for a, b in pairs:
        out |= {v.replace(a, b) for v in list(out)} | {v.replace(b, a) for v in list(out)}
    return out


class OptionsView(_Mixin, APIView):
    """GET: Auswahl für die Ausschreibung (Angaben je Person, Mitgliedsarten,
    Untereinheiten) und Funktionen der angemeldeten Person für den Brief."""

    def get(self, request, org_id: int):
        from customfields.models import FieldDefinition
        from members.models import MemberType

        fields = [
            {"key": k, "label": services.field_label(self.org, k)} for k in services.PERSON_FIELDS
        ]
        fields += [
            {"key": services.FIELD_PREFIX + d.key, "label": d.label}
            for d in FieldDefinition.objects.filter(
                organization=self.org, repeatable=False, is_archived=False
            ).order_by("sort_order", "label")
        ]
        name, functions = _signer(request.user, self.org)
        return Response(
            {
                "person_fields": fields,
                "member_types": [
                    {"id": t.pk, "name": t.name}
                    for t in MemberType.objects.filter(organization=self.org, is_archived=False)
                ],
                "units": [
                    {"id": d.pk, "name": d.name}
                    for d in Department.objects.filter(organization=self.org).order_by(
                        "sort_order", "name"
                    )
                ],
                "unit_label": self.org.department_label or "Untereinheit",
                "signer": name,
                "functions": functions,
                "competitions_enabled": services.competitions_enabled(self.org),
            }
        )


def _signer(user, org) -> tuple[str, list[str]]:
    """Name und Funktionen der angemeldeten Person in dieser Einheit (für den Brief)."""
    from letterhead.data import contexts_for, user_name

    for ctx in contexts_for(user):
        if ctx.org.pk == org.pk:
            return user_name(user, ctx), [f.name for f in ctx.functions]
    return (user.get_full_name() or user.email), []


class SubmitView(_Mixin, APIView):
    """POST {channel, email?, sent_to?, function?, withdraw?, reason?}: Meldung abgeben,
    Änderung melden oder zurückziehen. Hält eine Fassung fest; beim Weg E-Mail geht der
    Brief als PDF an den Veranstalter, Kopie an die eigene Adresse."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        entry = self.entry(call_id)
        if entry.status == Entry.Status.WITHDRAWN:
            raise ValidationError(gettext("Die Meldung ist zurückgezogen."))
        d = request.data
        channel = d.get("channel")
        call = entry.call
        if call.internal:
            # Von oben ausgeschrieben: die Meldung geht in HUBIplan an den Veranstalter
            channel = EntryVersion.Channel.HUBIPLAN
            withdraw = bool(d.get("withdraw", False))
            if call.strict and not withdraw:
                hints = services.check(entry)
                if hints:
                    raise ValidationError(
                        {"hints": [h.text for h in hints]}
                        | {"detail": "Die Ausschreibung lässt so keine Meldung zu."}
                    )
            if entry.status == Entry.Status.RETURNED and not entry.changed and not withdraw:
                # Rückfrage ohne Änderung beantwortet
                entry.status = Entry.Status.SUBMITTED
                entry.question = ""
                entry.save(update_fields=["status", "question", "updated_at"])
                record(
                    self.org, request.user, "update", entry, {"Zustand": ["Rückfrage", "abgegeben"]}
                )
                return Response(_entry_detail(self, entry), status=status.HTTP_201_CREATED)
        elif channel == EntryVersion.Channel.HUBIPLAN:
            raise ValidationError({"channel": gettext("Bitte einen Meldeweg wählen.")})
        if channel not in EntryVersion.Channel.values:
            raise ValidationError({"channel": gettext("Bitte einen Meldeweg wählen.")})
        withdraw = bool(d.get("withdraw", False))
        if withdraw and entry.status == Entry.Status.DRAFT:
            raise ValidationError(gettext("Ein Entwurf lässt sich löschen, nicht zurückziehen."))
        call = entry.call
        sent_to = str(d.get("sent_to", "") or "").strip()[:300]
        if channel == EntryVersion.Channel.EMAIL:
            sent_to = str(d.get("email") or call.organizer_email or "").strip()
            from django.core.exceptions import ValidationError as DjangoError
            from django.core.validators import validate_email

            try:
                validate_email(sent_to)
            except DjangoError:
                raise ValidationError(
                    {"email": gettext("Bitte eine gültige E-Mail-Adresse angeben.")}
                ) from None
        name, functions = _signer(request.user, self.org)
        function = str(d.get("function", "") or "").strip()[:200]
        if not function and functions:
            function = functions[0]
        version = services.record_version(
            entry,
            request.user,
            channel,
            sent_to=sent_to,
            signed_by=name,
            signed_function=function,
            reason=str(d.get("reason", "") or "").strip(),
            withdraw=withdraw,
        )
        entry.refresh_from_db()
        record(
            self.org,
            request.user,
            "update",
            entry,
            {
                "Fassung": [None, f"{version.number} ({version.get_kind_display()})"],
                "Meldeweg": [None, version.get_channel_display()],
            },
        )
        if entry.question:
            entry.question = ""
            entry.save(update_fields=["question", "updated_at"])
        if call.internal:
            if withdraw:
                services.sync_internal(entry)
        elif not withdraw:
            services.sync_competition(entry)
        if channel == EntryVersion.Channel.EMAIL:
            transaction.on_commit(lambda: _send_mail(version.pk, request.user.email))
        return Response(_entry_detail(self, entry), status=status.HTTP_201_CREATED)


def _send_mail(version_id: int, copy_to: str) -> None:
    from outbox import mail

    v = EntryVersion.objects.select_related("entry__call", "entry__organization").get(pk=version_id)
    org = v.entry.organization
    pdf = documents.letter_pdf(v)
    subject = f"{documents.subject(v)} – {org.name}"
    body = (
        f"{v.entry.call.salutation or 'Guten Tag,'}\n\n"
        f"{documents.intro(v)}\n\n"
        "Die Einzelheiten stehen im angehängten Schreiben.\n\n"
        f"Mit freundlichen Grüßen\n{v.signed_by}\n{v.signed_function}\n{org.name}\n"
    )
    attachment = [(documents.filename(v, "pdf"), pdf, "application/pdf")]
    reply_to = [copy_to] if copy_to else None
    mail.send(
        v.sent_to,
        subject,
        body,
        organization=org,
        kind="meldung",
        attachments=attachment,
        reply_to=reply_to,
        fail_silently=True,
        from_name=org.name,
    )
    if copy_to and copy_to.lower() != v.sent_to.lower():
        mail.send(
            copy_to,
            f"Kopie: {subject}",
            f"Diese Meldung ging an {v.sent_to}.\n\n{body}",
            organization=org,
            kind="meldung",
            attachments=attachment,
            fail_silently=True,
            from_name=org.name,
        )


class ConfirmView(_Mixin, APIView):
    """POST {note?}: Bestätigung des Veranstalters vermerken (z. B. „per Mail am …“) ·
    DELETE: Vermerk zurücknehmen. Bei Ausschreibungen an Untereinheiten bestätigt der
    Veranstalter; die Personen werden dann Starter im eigenen Wettbewerb."""

    def _entry(self, call_id) -> Entry:
        entry = self.entry(call_id)
        if entry.call.internal and self.unit_side:
            raise PermissionDenied(gettext("Bestätigen kann nur der Veranstalter."))
        return entry

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        entry = self._entry(call_id)
        if entry.status != Entry.Status.SUBMITTED:
            raise ValidationError(gettext("Bestätigen lässt sich nur eine abgegebene Meldung."))
        entry.status = Entry.Status.CONFIRMED
        entry.confirmed_note = str(request.data.get("note", "") or "").strip()[:300]
        entry.save(update_fields=["status", "confirmed_note", "updated_at"])
        record(self.org, request.user, "update", entry, {"Zustand": ["abgegeben", "bestätigt"]})
        if entry.call.internal:
            services.sync_internal(entry)
        return Response(_entry_detail(self, entry))

    @transaction.atomic
    def delete(self, request, org_id: int, call_id: int):
        entry = self._entry(call_id)
        if entry.status != Entry.Status.CONFIRMED:
            raise ValidationError(gettext("Die Meldung ist nicht als bestätigt vermerkt."))
        entry.status = Entry.Status.SUBMITTED
        entry.confirmed_note = ""
        entry.save(update_fields=["status", "confirmed_note", "updated_at"])
        record(self.org, request.user, "update", entry, {"Zustand": ["bestätigt", "abgegeben"]})
        return Response(_entry_detail(self, entry))


class ReturnView(_Mixin, APIView):
    """POST {question}: Veranstalter gibt die Meldung einer Untereinheit mit einer Rückfrage
    zurück (z. B. „bitte Geburtsdatum nachtragen“). Die Untereinheit gibt danach erneut ab."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        if self.unit_side or self.department is None:
            raise PermissionDenied(gettext("Zurückgeben kann nur der Veranstalter."))
        entry = self.entry(call_id)
        if entry.status not in (Entry.Status.SUBMITTED, Entry.Status.CONFIRMED):
            raise ValidationError(gettext("Zurückgeben lässt sich nur eine abgegebene Meldung."))
        question = str(request.data.get("question", "") or "").strip()[:500]
        if not question:
            raise ValidationError({"question": gettext("Bitte die Rückfrage angeben.")})
        before = entry.get_status_display()
        entry.status = Entry.Status.RETURNED
        entry.question = question
        entry.save(update_fields=["status", "question", "updated_at"])
        record(
            self.org,
            request.user,
            "update",
            entry,
            {"Zustand": [before, "Rückfrage"], "Rückfrage": [None, question]},
        )
        to = services.unit_contacts(self.org, self.department)
        call = entry.call
        if to:
            transaction.on_commit(
                lambda: _notify(
                    self.org,
                    to,
                    f"Rückfrage zur Meldung: {call.title}",
                    f"zu eurer Meldung für „{call.title}“ gibt es eine Rückfrage:\n\n"
                    f"{question}\n\nBitte die Meldung in HUBIplan prüfen und erneut abgeben.",
                )
            )
        return Response(_entry_detail(self, entry))


def _notify(org, to: list[str], subject: str, text: str) -> None:
    from outbox import mail

    for address in to:
        mail.send(
            address,
            subject,
            f"Guten Tag,\n\n{text}\n\nMit freundlichen Grüßen\n{org.name}\n",
            organization=org,
            kind="meldung",
            fail_silently=True,
            from_name=org.name,
        )


def _unit_row(call: Call, dept: Department, entry: Entry | None) -> dict:
    last = entry.versions.order_by("-number").first() if entry else None
    return {
        "unit": dept.pk,
        "name": dept.name,
        "status": entry.status if entry else None,
        "status_label": entry.get_status_display() if entry else "nichts angelegt",
        "changed": entry.changed if entry else False,
        "question": entry.question if entry else "",
        "teams": entry.teams.count() if entry else 0,
        "persons": entry.persons.count() if entry else 0,
        "hints": len(services.check(entry)) if entry else 0,
        "submitted_at": last.created_at if last else None,
        "contacts": len(services.unit_contacts(call.organization, dept)),
    }


class UnitsOverviewView(_Mixin, APIView):
    """GET: Übersicht des Veranstalters je angeschriebener Untereinheit."""

    def get(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        self.require_organizer(call)
        if not call.internal:
            raise ValidationError(gettext("Die Ausschreibung geht nicht an Untereinheiten."))
        ids = services.addressed_units(call)
        depts = {d.pk: d for d in Department.objects.filter(pk__in=ids)}
        entries = {
            e.department_id: e for e in Entry.objects.filter(call=call, department_id__in=ids)
        }
        return Response([_unit_row(call, depts[pk], entries.get(pk)) for pk in ids if pk in depts])


class RemindView(_Mixin, APIView):
    """POST {units?}: Erinnerung per Mail an die Untereinheiten, die noch nicht abgegeben
    haben (oder an die genannten)."""

    def post(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        self.require_organizer(call)
        if not call.internal:
            raise ValidationError(gettext("Die Ausschreibung geht nicht an Untereinheiten."))
        ids = services.addressed_units(call)
        wanted = request.data.get("units")
        if wanted:
            ids = [pk for pk in services.clean_units(self.org, wanted) if pk in ids]
        else:
            done = set(
                Entry.objects.filter(
                    call=call,
                    department_id__in=ids,
                    status__in=(Entry.Status.SUBMITTED, Entry.Status.CONFIRMED),
                ).values_list("department_id", flat=True)
            )
            ids = [pk for pk in ids if pk not in done]
        deadline = f" Meldeschluss ist am {call.deadline:%d.%m.%Y}." if call.deadline else ""
        reminded, without = [], []
        for dept in Department.objects.filter(pk__in=ids).order_by("sort_order", "name"):
            to = services.unit_contacts(self.org, dept)
            if not to:
                without.append(dept.name)
                continue
            reminded.append(dept.name)
            transaction.on_commit(
                lambda to=to, dept=dept: _notify(
                    self.org,
                    to,
                    f"Erinnerung: Meldung zu {call.title}",
                    f"für „{call.title}“ fehlt noch die Meldung von {dept.name}.{deadline}\n\n"
                    "Die Ausschreibung steht in HUBIplan unter Meldungen.",
                )
            )
        if reminded:
            record(
                self.org, request.user, "update", call, {"Erinnerung": [None, ", ".join(reminded)]}
            )
        return Response({"reminded": reminded, "without_contact": without})


class UnitsListDownloadView(_Mixin, APIView):
    """GET ?als=xlsx|csv: Meldeliste aller abgegebenen Meldungen der Untereinheiten (letzte
    Fassung je Untereinheit)."""

    def get(self, request, org_id: int, call_id: int):
        call = self.call(call_id)
        self.require_organizer(call)
        fmt = request.query_params.get("als", "xlsx")
        if fmt not in ("xlsx", "csv"):
            raise ValidationError({"als": gettext("Unbekanntes Format.")})
        entries = (
            Entry.objects.filter(
                call=call,
                department__isnull=False,
                status__in=(Entry.Status.SUBMITTED, Entry.Status.CONFIRMED, Entry.Status.RETURNED),
            )
            .select_related("department")
            .order_by("department__sort_order", "department__name")
        )
        rows: list[list] = []
        for e in entries:
            last = e.versions.order_by("-number").first()
            if last is None or last.kind == EntryVersion.Kind.WITHDRAWAL:
                continue
            table = documents.table_rows(last)
            if not rows:
                rows.append(["Untereinheit", *table[0]])
            rows += [[e.department.name, *r] for r in table[1:]]
        if not rows:
            rows = [["Untereinheit"]]
        data = documents.rows_xlsx(rows) if fmt == "xlsx" else documents.rows_csv(rows)
        name = f"Meldeliste-{documents.safe_name(call.title)}.{fmt}"
        return _download(data, name, fmt)


def _withdrawn_last(entry: Entry) -> bool:
    last = entry.versions.order_by("-number").first()
    return last is not None and last.kind == EntryVersion.Kind.WITHDRAWAL


class EntryDeleteView(_Mixin, APIView):
    """DELETE: Meldung löschen, solange nichts abgegeben ist oder nachdem sie zurückgezogen
    wurde; dann samt Fassungen. Die Ausschreibung bleibt."""

    @transaction.atomic
    def delete(self, request, org_id: int, call_id: int):
        entry = self.entry(call_id)
        withdrawn = _withdrawn_last(entry)
        if entry.versions.exists() and not withdrawn:
            raise ValidationError(
                gettext("Die Meldung ist schon abgegeben; ziehe sie zuerst zurück.")
            )
        data = snapshot(entry)
        if withdrawn:
            data["Fassungen"] = entry.versions.count()
        record(self.org, request.user, "delete", entry, diff(data, {}))
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EntryReopenView(_Mixin, APIView):
    """POST: zurückgezogene Meldung wieder öffnen. Sie wird wieder zum Entwurf mit den
    bisherigen Mannschaften und Personen; die Fassungen bleiben, die nächste Abgabe ist
    wieder eine Meldung."""

    @transaction.atomic
    def post(self, request, org_id: int, call_id: int):
        entry = self.entry(call_id)
        if entry.status != Entry.Status.WITHDRAWN:
            raise ValidationError(
                gettext("Nur eine zurückgezogene Meldung lässt sich wieder öffnen.")
            )
        entry.status = Entry.Status.DRAFT
        entry.changed = False
        entry.confirmed_note = ""
        entry.question = ""
        entry.save(update_fields=["status", "changed", "confirmed_note", "question", "updated_at"])
        record(self.org, request.user, "update", entry, {"Zustand": ["zurückgezogen", "Entwurf"]})
        return Response(_entry_detail(self, entry))


FORMATS = {
    "pdf": ("application/pdf", documents.letter_pdf),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        documents.table_xlsx,
    ),
    "csv": ("text/csv; charset=utf-8", documents.table_csv),
}


def _download(data: bytes, name: str, fmt: str) -> HttpResponse:
    resp = HttpResponse(data, content_type=FORMATS[fmt][0])
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


class VersionDownloadView(_Mixin, APIView):
    """GET ?als=pdf|xlsx|csv: Fassung als Brief (PDF) oder Tabelle."""

    def get(self, request, org_id: int, call_id: int, number: int):
        entry = self.entry(call_id)
        version = get_object_or_404(EntryVersion, entry=entry, number=number)
        fmt = request.query_params.get("als", "pdf")
        if fmt not in FORMATS:
            raise ValidationError({"als": gettext("Unbekanntes Format.")})
        content_type, render = FORMATS[fmt]
        resp = HttpResponse(render(version), content_type=content_type)
        disposition = "inline" if fmt == "pdf" else "attachment"
        resp["Content-Disposition"] = (
            f'{disposition}; filename="{documents.filename(version, fmt)}"'
        )
        return resp


class PreviewDownloadView(_Mixin, APIView):
    """GET ?als=pdf|xlsx|csv: Vorschau des aktuellen Stands (noch nicht abgegeben)."""

    def get(self, request, org_id: int, call_id: int):
        entry = self.entry(call_id)
        fmt = request.query_params.get("als", "pdf")
        if fmt not in FORMATS:
            raise ValidationError({"als": gettext("Unbekanntes Format.")})
        last = entry.versions.order_by("-number").first()
        name, functions = _signer(request.user, self.org)
        preview = EntryVersion(
            organization=self.org,
            entry=entry,
            number=(last.number + 1) if last else 1,
            kind=EntryVersion.Kind.CHANGE if last else EntryVersion.Kind.ENTRY,
            channel=EntryVersion.Channel.LETTER,
            data=services.snapshot(entry),
            signed_by=name,
            signed_function=functions[0] if functions else "",
        )
        preview.created_at = timezone.now()
        if last:
            preview.changes = services.describe_changes(last.data or {}, preview.data)
        content_type, render = FORMATS[fmt]
        resp = HttpResponse(render(preview), content_type=content_type)
        disposition = "inline" if fmt == "pdf" else "attachment"
        resp["Content-Disposition"] = (
            f'{disposition}; filename="Vorschau-{documents.filename(preview, fmt)}"'
        )
        return resp
