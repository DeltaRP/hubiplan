"""Wettbewerbe in der Verwaltung (Menü „Wettbewerbe“).

Rechte: „Wettbewerbe verwalten“ richtet ein (Grunddaten, Wertungen, Zustand, Löschen);
„Ergebnisse erfassen“ trägt Starter, Werte und Stechen ein und sieht von Startern nur
Name, Untereinheit und Startnummer. Lesen darf, wer eines der beiden Rechte hat.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import COMPETITIONS_MANAGE, COMPETITIONS_RESULTS
from audit.log import diff, record, snapshot
from core.api_base import AuditMixin, OrgScopedMixin
from members.models import Membership
from organizations.models import Department, Organization

from . import bird, report, services
from .models import (
    Competition,
    Placing,
    Presence,
    Prize,
    Score,
    Scoring,
    ShootOff,
    ShootOffEntry,
    Starter,
    Team,
)

MODULE = "competitions"


class _Mixin(OrgScopedMixin):
    """Lesen mit einem der beiden Rechte; Schreiben je Ansicht (``manage_only``)."""

    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    manage_only = True

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if MODULE not in (self.org.enabled_modules or []):
            raise NotFound("Das Modul Wettbewerbe ist nicht freigeschaltet.")
        perms = self.org_permissions
        if not ({COMPETITIONS_MANAGE, COMPETITIONS_RESULTS} & perms):
            raise PermissionDenied("Dafür fehlt dir die Berechtigung.")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if self.manage_only and COMPETITIONS_MANAGE not in perms:
                raise PermissionDenied("Dafür fehlt dir die Berechtigung.")

    @property
    def can_manage(self) -> bool:
        return COMPETITIONS_MANAGE in self.org_permissions

    def competition(self, pk) -> Competition:
        return get_object_or_404(Competition, pk=pk, organization=self.org)


def _units(org) -> list[Department]:
    return list(Department.objects.filter(organization=org).order_by("sort_order", "name"))


# --- Wettbewerbe ---


class CompetitionSerializer(serializers.ModelSerializer):
    starter_count = serializers.IntegerField(read_only=True, default=0)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    event = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Competition
        fields = [
            "id",
            "title",
            "form",
            "own",
            "organizer",
            "occasion",
            "discipline",
            "location",
            "date",
            "description",
            "details",
            "status",
            "status_label",
            "website",
            "drop_out",
            "fixed_order",
            "total_shots",
            "lots",
            "event",
            "starter_count",
        ]
        read_only_fields = ["status"]

    def validate(self, attrs):
        if self.instance is not None:
            for field in ("form", "own"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError(
                        {field: "Die Art des Wettbewerbs lässt sich nicht mehr ändern."}
                    )
        form = attrs.get("form", getattr(self.instance, "form", Competition.Form.RANKING))
        own = attrs.get("own", getattr(self.instance, "own", True))
        if form == Competition.Form.BIRD and not own:
            raise serializers.ValidationError(
                {"own": "Ein Vogelschießen lässt sich nur als eigener Wettbewerb anlegen."}
            )
        return attrs

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Bitte einen Titel angeben.")
        return value

    def validate_details(self, value):
        if not isinstance(value, list) or len(value) > 30:
            raise serializers.ValidationError("Höchstens 30 weitere Angaben.")
        out = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Ungültige Angabe.")
            label = str(item.get("label", "")).strip()[:60]
            text = str(item.get("value", "")).strip()[:200]
            if label or text:
                out.append({"label": label, "value": text})
        return out


class ScoringSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scoring
        fields = [
            "id",
            "competition",
            "name",
            "kind",
            "sort_order",
            "shots",
            "counted_shots",
            "max_per_shot",
            "unit_label",
            "decimals",
            "higher_better",
            "source",
            "team_mode",
            "team_size",
            "prize_places",
            "shootoff_shots",
            "shootoff_counted",
            "field_size",
        ]
        read_only_fields = ["competition"]

    def validate_decimals(self, value):
        if value > 3:
            raise serializers.ValidationError("Höchstens 3 Nachkommastellen.")
        return value

    def validate(self, attrs):
        comp = self.context["competition"]
        get = lambda name: attrs.get(name, getattr(self.instance, name, None))  # noqa: E731
        name = (get("name") or "").strip()
        if not name:
            raise serializers.ValidationError({"name": "Bitte eine Bezeichnung angeben."})
        if comp.form == Competition.Form.BIRD:
            raise serializers.ValidationError(
                "Beim Vogelschießen gibt es keine Wertungen, nur Pfänder."
            )
        kind = get("kind")
        if kind == Scoring.Kind.TEAM and comp.own:
            raise serializers.ValidationError(
                {"kind": "Mannschaftswertungen gibt es nur bei fremden Wettbewerben."}
            )
        if kind == Scoring.Kind.UNIT and not comp.own:
            raise serializers.ValidationError(
                {"kind": "Bei fremden Wettbewerben: Einzel- oder Mannschaftswertung."}
            )
        attrs["name"] = name if "name" in attrs or not self.instance else attrs.get("name", name)
        shots, counted = get("shots"), get("counted_shots")
        if shots and counted and counted > shots:
            raise serializers.ValidationError(
                {"counted_shots": "Es können nicht mehr Schüsse zählen als geschossen werden."}
            )
        so_shots, so_counted = get("shootoff_shots"), get("shootoff_counted")
        if so_shots and so_counted and so_counted > so_shots:
            raise serializers.ValidationError(
                {"shootoff_counted": "Es können nicht mehr Schüsse zählen als geschossen werden."}
            )
        if get("kind") == Scoring.Kind.UNIT:
            source = get("source")
            if source is None:
                source = (
                    Scoring.objects.filter(competition=comp, kind=Scoring.Kind.INDIVIDUAL)
                    .order_by("sort_order", "pk")
                    .first()
                )
                if source is None:
                    raise serializers.ValidationError(
                        {"source": "Zuerst eine Einzelwertung anlegen."}
                    )
                attrs["source"] = source
            elif source.competition_id != comp.pk or source.kind != Scoring.Kind.INDIVIDUAL:
                raise serializers.ValidationError({"source": "Bitte eine Einzelwertung wählen."})
            if get("team_mode") == Scoring.TeamMode.SUM_BEST and not get("team_size"):
                raise serializers.ValidationError(
                    {"team_size": "Bitte angeben, wie viele der besten zählen."}
                )
        else:
            attrs["source"] = None
        return attrs


class CompetitionViewSet(_Mixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = CompetitionSerializer

    def get_queryset(self):
        return Competition.objects.filter(organization=self.org).annotate(
            starter_count=Count("starters")
        )

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)
        comp = serializer.instance
        self._calendar(comp)
        template = self.request.data.get("template")
        if template == "schiessen":
            # Vorlage „Schießen mit Einzel- und Zugwertung“ (Leitszenario des Pilotvereins)
            single = Scoring.objects.create(
                organization=self.org,
                competition=comp,
                name="Einzelwertung",
                kind=Scoring.Kind.INDIVIDUAL,
                sort_order=1,
                shots=5,
                counted_shots=3,
                max_per_shot=Decimal(10),
                prize_places=10,
                shootoff_shots=3,
            )
            label = self.org.department_label or "Untereinheit"
            Scoring.objects.create(
                organization=self.org,
                competition=comp,
                name=f"{label}wertung" if " " not in label else f"Wertung {label}",
                kind=Scoring.Kind.UNIT,
                sort_order=2,
                source=single,
                team_mode=Scoring.TeamMode.SUM_BEST,
                team_size=5,
                prize_places=3,
                shootoff_shots=1,
            )
        elif template == "einfach":
            Scoring.objects.create(
                organization=self.org, competition=comp, name="Einzelwertung", sort_order=1
            )
        elif template == "vogel" or comp.form == Competition.Form.BIRD:
            if comp.form != Competition.Form.BIRD:
                comp.form = Competition.Form.BIRD
                comp.save(update_fields=["form"])
            bird.create_template(self.org, comp)
        elif template == "fremd" or not comp.own:
            # Fremder Wettbewerb: eigene Schützen und Mannschaften mit Platz des Ausrichters
            if comp.own:
                comp.own = False
                comp.save(update_fields=["own"])
            Scoring.objects.create(
                organization=self.org,
                competition=comp,
                name="Einzelwertung",
                kind=Scoring.Kind.INDIVIDUAL,
                sort_order=1,
            )
            Scoring.objects.create(
                organization=self.org,
                competition=comp,
                name="Mannschaftswertung",
                kind=Scoring.Kind.TEAM,
                sort_order=2,
            )
            Team.objects.create(organization=self.org, competition=comp, name="Mannschaft 1")

    def _calendar(self, comp: Competition) -> None:
        """Beim Anlegen: Termin zuordnen (``event``) oder neu anlegen (``create_event``)."""
        from . import event_views

        if self.request.data.get("event"):
            event = event_views.find_event(self, self.request.data["event"])
            event_views.link(self, comp, event, fill=True)
        elif self.request.data.get("create_event") is True:
            event_views.create_event(self, comp)

    def retrieve(self, request, *args, **kwargs):
        from access.catalog import EVENTS_MANAGE

        from . import event_views

        comp = self.get_object()
        data = CompetitionSerializer(comp).data
        data["scorings"] = ScoringSerializer(
            comp.scorings.all(), many=True, context={"competition": comp}
        ).data
        data["units"] = [{"id": u.pk, "name": u.name} for u in _units(self.org)]
        data["prizes"] = [
            {"id": p.pk, "name": p.name, "award": p.award, "sort_order": p.sort_order}
            for p in comp.prizes.all()
        ]
        data["can_manage"] = self.can_manage
        data["event_info"] = event_views.event_info(comp.event)
        on = event_views.calendar_on(self.org)
        data["calendar"] = {"on": on, "can_create": on and EVENTS_MANAGE in self.org_permissions}
        return Response(data)


class ScoringViewSet(_Mixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = ScoringSerializer

    def get_queryset(self):
        return Scoring.objects.filter(
            organization=self.org, competition_id=self.kwargs["competition_id"]
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "org", None) is not None:
            ctx["competition"] = self.competition(self.kwargs["competition_id"])
        return ctx

    def get_create_kwargs(self) -> dict:
        comp = self.competition(self.kwargs["competition_id"])
        last = comp.scorings.aggregate(m=Max("sort_order"))["m"] or 0
        return {"organization": self.org, "competition": comp, "sort_order": last + 1}


# --- Starter ---


def _starter_data(s: Starter, value_by_scoring: dict | None = None) -> dict:
    return {
        "id": s.pk,
        "name": s.name,
        "club": s.club,
        "guest": s.is_guest,
        "membership": s.membership_id,
        "unit": s.unit_id,
        "unit_name": s.unit.name if s.unit_id else "",
        "number": s.number,
        "out_of_competition": s.out_of_competition,
        "presence": s.presence,
        "drawn_how": s.drawn_how,
        "key": str(s.client_key) if s.client_key else None,
        "values": value_by_scoring or {},
    }


class StartersView(_Mixin, APIView):
    """GET: Starter mit Werten · POST: Mitglied (membership) oder Gast (name, club) hinzufügen."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        return Response(_starters_with_values(self.competition(competition_id)))

    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        s = create_starter(self.org, request.user, comp, request.data)
        return Response(_starter_data(s), status=status.HTTP_201_CREATED)


def _open_for_entries(comp: Competition) -> None:
    if comp.status == Competition.Status.FINAL:
        raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")


@transaction.atomic
def create_starter(org, user, comp: Competition, data, merged: list | None = None) -> Starter:
    """Mitglied (``membership``) oder Gast (``name``, ``club``) als Starter anlegen.
    ``client_key``: Kennung vom Gerät (Offline-Betrieb); ein zweites Senden liefert
    denselben Starter zurück. Mit ``merged`` (Abgleich mehrerer Tablets): hat ein anderes
    Gerät das Mitglied schon angelegt, gilt die Kennung als zweiter Name dieses Starters,
    und die folgenden Eingaben des Geräts landen dort (Ralf 2026-11-01)."""
    _open_for_entries(comp)
    key = _uuid(data.get("client_key"))
    if key:
        same = Starter.objects.filter(competition=comp, client_key=key).select_related("unit")
        if same.exists():
            return same.get()
        alias = comp.starters.filter(aliases__contains=[str(key)]).first()
        if alias:
            return alias
    unit = _unit_or_none(org, data.get("unit"))
    if data.get("membership"):
        m = (
            Membership.objects.filter(
                organization=org, pk=data["membership"], purged_at__isnull=True
            )
            .select_related("person")
            .first()
        )
        if m is None:
            raise ValidationError({"membership": "Unbekanntes Mitglied."})
        existing = comp.starters.filter(membership=m).first()
        if existing and key and merged is not None:
            existing.aliases = [*existing.aliases, str(key)]
            existing.save(update_fields=["aliases", "updated_at"])
            merged.append(existing)
            return existing
        if existing:
            raise ValidationError({"membership": f"{_person_name(m)} ist schon eingetragen."})
        s = Starter(
            organization=org,
            competition=comp,
            membership=m,
            name=_person_name(m),
            unit_id=unit.pk if unit else services.default_unit(org, m, comp.date),
        )
    else:
        name = str(data.get("name", "")).strip()[:200]
        if not name:
            raise ValidationError({"name": "Bitte einen Namen angeben."})
        s = Starter(
            organization=org,
            competition=comp,
            name=name,
            club=str(data.get("club", "")).strip()[:200],
            unit_id=unit.pk if unit else None,
        )
    s.number = str(data.get("number", "") or "").strip()[:20]
    s.client_key = key
    try:
        with transaction.atomic():
            s.save()
            record(org, user, "create", s, diff({}, snapshot(s)))
    except IntegrityError as exc:
        raise ValidationError({"membership": "Schon eingetragen."}) from exc
    return Starter.objects.select_related("unit").get(pk=s.pk)


def _uuid(raw):
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise ValidationError({"client_key": "Ungültige Kennung."}) from exc


def _person_name(m: Membership) -> str:
    return f"{m.person.first_name} {m.person.last_name}".strip()


def _unit_or_none(org, raw):
    if raw in (None, "", 0, "0"):
        return None
    unit = Department.objects.filter(organization=org, pk=raw).first()
    if unit is None:
        raise ValidationError({"unit": "Unbekannte Untereinheit."})
    return unit


class StarterView(_Mixin, APIView):
    """PATCH: Untereinheit, Startnummer, außer Konkurrenz, Gastname · DELETE: entfernen."""

    manage_only = False

    def _get(self, competition_id, pk) -> Starter:
        comp = self.competition(competition_id)
        if comp.status == Competition.Status.FINAL:
            raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")
        return get_object_or_404(Starter, pk=pk, competition=comp, organization=self.org)

    def patch(self, request, org_id: int, competition_id: int, pk: int):
        s = self._get(competition_id, pk)
        update_starter(self.org, request.user, s, request.data)
        s = Starter.objects.select_related("unit").get(pk=s.pk)
        return Response(_starter_data(s))

    def delete(self, request, org_id: int, competition_id: int, pk: int):
        delete_starter(self.org, request.user, self._get(competition_id, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


@transaction.atomic
def delete_starter(org, user, s: Starter) -> None:
    """Starter mit seinen Werten entfernen. Schüsse und Pfänder beim Vogelschießen behalten
    den Namen."""
    _open_for_entries(s.competition)
    record(org, user, "delete", s, diff(snapshot(s), {}))
    s.delete()


@transaction.atomic
def update_starter(org, user, s: Starter, data) -> None:
    _open_for_entries(s.competition)
    before = snapshot(s)
    if "unit" in data:
        unit = _unit_or_none(org, data["unit"])
        s.unit_id = unit.pk if unit else None
    if "number" in data:
        s.number = str(data["number"] or "").strip()[:20]
        if s.competition.form == Competition.Form.BIRD and s.number:
            n = bird.lot(s.number)
            if n is None:
                raise ValidationError({"number": "Losnummer: bitte eine ganze Zahl ab 1."})
            other = s.competition.starters.exclude(pk=s.pk).filter(number=str(n)).first()
            if other:
                raise ValidationError({"number": f"Nummer {n} hat schon {other.name}."})
            s.number = str(n)
            s.drawn_how = s.drawn_how or "hut"
    if "presence" in data:
        if data["presence"] not in Presence.values:
            raise ValidationError({"presence": "Unbekannte Angabe."})
        s.presence = data["presence"]
    if "out_of_competition" in data:
        s.out_of_competition = bool(data["out_of_competition"])
    if s.is_guest:
        if "name" in data:
            name = str(data["name"] or "").strip()[:200]
            if not name:
                raise ValidationError({"name": "Bitte einen Namen angeben."})
            s.name = name
        if "club" in data:
            s.club = str(data["club"] or "").strip()[:200]
    s.save()
    changes = diff(before, snapshot(s))
    if changes:
        record(org, user, "update", s, changes)


def _decimal(raw, field: str) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", ".").strip())
    except InvalidOperation as exc:
        raise ValidationError({field: "Bitte eine Zahl eingeben."}) from exc
    if not value.is_finite() or value < 0 or value >= Decimal("10000000"):
        raise ValidationError({field: "Bitte eine gültige Zahl eingeben."})
    return value


def _check_decimals(value: Decimal, decimals: int, field: str):
    if value != value.quantize(Decimal(1).scaleb(-decimals)):
        raise ValidationError(
            {field: f"Höchstens {decimals} Nachkommastellen."}
            if decimals
            else {field: "Bitte eine ganze Zahl eingeben."}
        )


class ScoreView(_Mixin, APIView):
    """PUT {starter, scoring, value}: Wert setzen (leer: löschen)."""

    manage_only = False

    def put(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        starter = get_object_or_404(Starter, pk=request.data.get("starter"), competition=comp)
        scoring = get_object_or_404(
            Scoring, pk=request.data.get("scoring"), competition=comp, kind=Scoring.Kind.INDIVIDUAL
        )
        value, _ = set_score(
            self.org, request.user, comp, scoring, starter, request.data.get("value")
        )
        return Response(
            {
                "starter": starter.pk,
                "scoring": scoring.pk,
                "value": None if value is None else str(value),
            }
        )


@transaction.atomic
def set_score(org, user, comp, scoring, starter, raw, at=None):
    """Wert setzen (leer: löschen). ``at``: Zeitpunkt der Eingabe auf dem Gerät. Wurde der
    Wert auf dem Server danach geändert, gilt die spätere Eingabe; zurück kommt dann der
    gültige Wert und ``True`` (Konflikt)."""
    _open_for_entries(comp)
    value = _decimal(raw, "value")
    existing = Score.objects.select_for_update().filter(scoring=scoring, starter=starter).first()
    if at is not None and existing and existing.updated_at > at and existing.value != value:
        return existing.value, True
    if value is None:
        if existing:
            record(org, user, "delete", existing, diff(snapshot(existing), {}))
            existing.delete()
        return None, False
    _check_decimals(value, scoring.decimals, "value")
    if scoring.max_value is not None and value > scoring.max_value:
        raise ValidationError({"value": f"Höchstens {services.fmt(scoring.max_value, 0)}."})
    if existing:
        before = snapshot(existing)
        existing.value = value
        existing.save()
        changes = diff(before, snapshot(existing))
        if changes:
            record(org, user, "update", existing, changes)
    else:
        existing = Score.objects.create(
            organization=org, scoring=scoring, starter=starter, value=value
        )
        record(org, user, "create", existing, diff({}, snapshot(existing)))
    if comp.status == Competition.Status.PREPARATION:
        comp.status = Competition.Status.RUNNING
        comp.save(update_fields=["status", "updated_at"])
    return value, False


class SyncView(_Mixin, APIView):
    """POST {ops: [...]}: Eingaben aus dem Offline-Betrieb des Standmodus nachreichen.

    Arten: ``starter`` (wie POST starters, mit ``client_key``), ``starter_update``
    (``starter`` = Nummer oder Gerätekennung, dazu unit/number/out_of_competition) und
    ``score`` (``starter``, ``scoring``, ``value``, ``at``). Jede Eingabe für sich: Was
    scheitert, steht mit Grund in ``results``, der Rest wird übernommen. Zurück kommen
    alle Starter mit Werten und die Zuordnung Gerätekennung → Nummer.
    """

    manage_only = False

    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        data = request.data
        return Response(sync(self.org, request.user, comp, data.get("ops"), data.get("generation")))


RESET_NOTE = "Der Wettbewerb wurde zurückgesetzt, die Eingabe ist verworfen."


def sync(org, user, comp: Competition, ops, generation=None) -> dict:
    """Eingaben aus dem Standmodus nachreichen (auch für den Standzugang). ``generation``:
    der Stand des Zurücksetzens, den das Gerät kennt; passt er nicht, stammen die Eingaben
    von vor dem Zurücksetzen und werden verworfen."""
    ops = ops or []
    if not isinstance(ops, list) or len(ops) > 2000:
        raise ValidationError("Höchstens 2000 Eingaben auf einmal.")
    results, conflicts = [], []
    stale = generation is not None and str(generation) != str(comp.generation)
    for op in ops:
        if stale:
            results.append({"ok": False, "error": RESET_NOTE})
            continue
        try:
            if not isinstance(op, dict):
                raise TypeError
            with transaction.atomic():
                results.append(_apply_op(org, user, comp, op, conflicts))
        except (ValidationError, NotFound) as exc:
            results.append({"ok": False, "error": _message(exc)})
        except (
            Starter.DoesNotExist,
            Scoring.DoesNotExist,
            Prize.DoesNotExist,
            ValueError,
            TypeError,
        ):
            results.append({"ok": False, "error": "Ungültige Eingabe."})
    comp.refresh_from_db()
    keys = {
        str(k): pk
        for pk, k in comp.starters.filter(client_key__isnull=False).values_list("pk", "client_key")
    }
    for pk, aliases in comp.starters.exclude(aliases=[]).values_list("pk", "aliases"):
        keys.update({str(a): pk for a in aliases})
    out = {
        "results": results,
        "conflicts": conflicts,
        "keys": keys,
        "starters": _starters_with_values(comp),
        "status": comp.status,
        "generation": comp.generation,
    }
    if comp.form == Competition.Form.BIRD:
        out["bird"] = _jsonable(bird.state(comp))
    return out


def _starter_ref(comp, ref) -> Starter:
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return Starter.objects.get(pk=int(ref), competition=comp)
    key = _uuid(ref)
    if key is None:  # sonst träfe client_key=None jeden Starter ohne Gerätekennung
        raise Starter.DoesNotExist
    found = Starter.objects.filter(client_key=key, competition=comp).first()
    return found or Starter.objects.get(competition=comp, aliases__contains=[str(key)])


def _apply_op(org, user, comp, op, conflicts) -> dict:
    kind = op.get("op")
    if kind == "starter":
        merged: list = []
        s = create_starter(org, user, comp, op, merged)
        if merged:
            conflicts.append(
                {
                    "starter": s.pk,
                    "name": s.name,
                    "note": "war schon von einem anderen Gerät eingetragen, zusammengeführt",
                }
            )
        return {"ok": True, "starter": s.pk}
    if kind == "starter_update":
        s = _starter_ref(comp, op.get("starter"))
        update_starter(org, user, s, op)
        return {"ok": True}
    if kind == "starter_delete":
        try:
            s = _starter_ref(comp, op.get("starter"))
        except Starter.DoesNotExist:
            return {"ok": True}  # schon entfernt (zweites Senden vom Gerät)
        delete_starter(org, user, s)
        return {"ok": True}
    if kind == "score":
        s = _starter_ref(comp, op.get("starter"))
        scoring = Scoring.objects.get(
            pk=op.get("scoring"), competition=comp, kind=Scoring.Kind.INDIVIDUAL
        )
        at = parse_datetime(str(op.get("at") or "")) if op.get("at") else None
        value, conflict = set_score(org, user, comp, scoring, s, op.get("value"), at)
        if conflict:
            conflicts.append(
                {"starter": s.pk, "name": s.name, "scoring": scoring.pk, "value": str(value)}
            )
        return {"ok": True}
    if kind == "shot":
        s = _starter_ref(comp, op.get("starter"))
        hits = op.get("hits") or []
        if not isinstance(hits, list):
            raise TypeError
        shot = bird.fire(
            org,
            user,
            comp,
            s,
            hits,
            at=bird.parse_at(op.get("at")),
            client_key=bird.parse_key(op.get("client_key")),
        )
        return {"ok": True, "shot": shot.number}
    if kind == "undo":
        bird.undo(org, user, comp, client_key=bird.parse_key(op.get("client_key")))
        return {"ok": True}
    if kind == "draw":
        s = _starter_ref(comp, op.get("starter"))
        how = op.get("how") if op.get("how") in ("hut", "digital") else "hut"
        number, note = bird.draw(org, user, comp, s, op.get("number"), how)
        if note:
            conflicts.append({"starter": s.pk, "name": s.name, "number": number, "note": note})
        return {"ok": True, "number": number}
    raise ValidationError("Unbekannte Eingabe.")


def _message(exc) -> str:
    detail = getattr(exc, "detail", str(exc))
    if isinstance(detail, dict):
        detail = next(iter(detail.values()), "")
    if isinstance(detail, list):
        detail = detail[0] if detail else ""
    return str(detail)


def _starters_with_values(comp) -> list[dict]:
    values: dict[int, dict] = {}
    latest: dict[int, datetime.datetime] = {}
    for sc in Score.objects.filter(scoring__competition=comp):
        values.setdefault(sc.starter_id, {})[str(sc.scoring_id)] = str(sc.value)
        if sc.starter_id not in latest or sc.updated_at > latest[sc.starter_id]:
            latest[sc.starter_id] = sc.updated_at
    out = []
    for s in comp.starters.select_related("unit").order_by("name", "pk"):
        data = _starter_data(s, values.get(s.pk))
        # Zuletzt erfasst über alle Geräte (Standmodus, Standzugang, Verwaltung)
        data["scored_at"] = latest[s.pk].isoformat() if s.pk in latest else None
        out.append(data)
    return out


class MemberListView(_Mixin, APIView):
    """GET: alle Mitglieder am Wettbewerbstag mit Untereinheit, für die Suche ohne Netz
    (nur Name, Zug, Geburtsjahr)."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        on = comp.date
        rows = (
            Membership.objects.filter(organization=self.org, purged_at__isnull=True)
            .filter(periods__entry_date__lte=on)
            .filter(Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=on))
            .distinct()
            .select_related("person")
        )
        units = services.units_on(self.org, on)
        names = dict(Department.objects.filter(organization=self.org).values_list("pk", "name"))
        return Response(
            [
                {
                    "membership": m.pk,
                    "name": _person_name(m),
                    "birth_year": m.person.birth_date.year if m.person.birth_date else None,
                    "unit": units.get(m.pk),
                    "unit_name": names.get(units.get(m.pk), ""),
                }
                for m in sorted(rows, key=lambda m: (m.person.last_name, m.person.first_name))
            ]
        )


class CandidatesView(_Mixin, APIView):
    """GET ?suche=: Mitglieder zur Auswahl als Starter, mit Untereinheit und Geburtsjahr."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        term = request.query_params.get("suche", "").strip()
        if len(term) < 2:
            return Response([])
        qs = Membership.objects.filter(organization=self.org, purged_at__isnull=True)
        on = comp.date
        # Mitglied am Wettbewerbstag (ein Zeitraum umfasst den Tag)
        qs = (
            qs.filter(periods__entry_date__lte=on)
            .filter(Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=on))
            .distinct()
        )
        for word in term.split()[:3]:
            variants = _umlaut_variants(word)
            cond = Q()
            for v in variants:
                cond |= Q(person__first_name__icontains=v) | Q(person__last_name__icontains=v)
            qs = qs.filter(cond)
        rows = list(
            qs.select_related("person").order_by("person__last_name", "person__first_name")[:12]
        )
        taken = dict(comp.starters.filter(membership__in=rows).values_list("membership_id", "pk"))
        units = dict(Department.objects.filter(organization=self.org).values_list("pk", "name"))
        out = []
        for m in rows:
            unit_id = services.default_unit(self.org, m, on)
            out.append(
                {
                    "membership": m.pk,
                    "name": _person_name(m),
                    "birth_year": m.person.birth_date.year if m.person.birth_date else None,
                    "unit": unit_id,
                    "unit_name": units.get(unit_id, ""),
                    "starter": taken.get(m.pk),
                }
            )
        return Response(out)


def _umlaut_variants(word: str) -> set[str]:
    """„muel“ findet „Müller“, „Müller“ auch „Mueller“."""
    w = word.lower()
    pairs = (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("ss", "ß"))
    out = {w}
    for a, b in pairs:
        out |= {v.replace(a, b) for v in list(out)} | {v.replace(b, a) for v in list(out)}
    return out


class StandingsView(_Mixin, APIView):
    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        data = services.standings(comp)
        data["status"] = comp.status
        return Response(_jsonable(data))


class VersionView(_Mixin, APIView):
    """GET: kleiner Stand des Wettbewerbs; die Ansichten laden nur bei einer Änderung neu."""

    def get(self, request, org_id: int, competition_id: int):
        return Response({"version": services.version(self.competition(competition_id))})


def _jsonable(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


class StatusView(_Mixin, APIView):
    """POST {status}: Zustand setzen. „endgültig“ nur ohne offene Stechen."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        new = request.data.get("status")
        if new not in Competition.Status.values:
            raise ValidationError({"status": "Unbekannter Zustand."})
        if new == Competition.Status.FINAL:
            data = services.standings(comp)
            if data["open_shootoffs"]:
                raise ValidationError(
                    {"status": "Erst die offenen Stechen entscheiden, dann endgültig setzen."}
                )
        before = snapshot(comp)
        comp.status = new
        comp.save(update_fields=["status", "updated_at"])
        record(self.org, request.user, "update", comp, diff(before, snapshot(comp)))
        return Response({"status": comp.status, "status_label": comp.get_status_display()})


class ResetView(_Mixin, APIView):
    """POST {keep_starters}: Ergebnisse löschen (Werte, Stechen, Plätze, Schüsse, gefallene
    Pfänder), ohne ``keep_starters`` auch alle Starter (Ralf 2026-11-01). Regeln, Pfänder,
    Mannschaften, Standzugang und Termin bleiben; der Zustand geht auf „Vorbereitung“."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        Competition.objects.select_for_update().filter(pk=comp.pk).first()
        if comp.status == Competition.Status.FINAL:
            raise ValidationError("Ein endgültiger Wettbewerb lässt sich nicht zurücksetzen.")
        keep = bool(request.data.get("keep_starters"))
        before = snapshot(comp)
        counts = {
            "Werte": Score.objects.filter(scoring__competition=comp).count(),
            "Schüsse": comp.shots.count(),
            "Starter": 0 if keep else comp.starters.count(),
        }
        Score.objects.filter(scoring__competition=comp).delete()
        ShootOff.objects.filter(scoring__competition=comp).delete()
        Placing.objects.filter(scoring__competition=comp).delete()
        comp.prizes.update(
            winner=None,
            winner_name="",
            shot_number=None,
            shots_for=None,
            shot=None,
            fallen_at=None,
        )
        comp.shots.all().delete()
        if keep:
            comp.starters.exclude(presence="").update(presence="")
        else:
            comp.starters.all().delete()
        comp.status = Competition.Status.PREPARATION
        comp.total_shots = None
        comp.generation += 1
        comp.save(update_fields=["status", "total_shots", "generation", "updated_at"])
        changes = diff(before, snapshot(comp))
        changes["zurückgesetzt"] = [
            ", ".join(f"{n} {k}" for k, n in counts.items() if n) or "nichts",
            "Starter behalten" if keep else "Starter gelöscht",
        ]
        record(self.org, request.user, "update", comp, changes)
        return Response({"deleted": counts, "status": comp.status, "generation": comp.generation})


class CopyView(_Mixin, APIView):
    """POST {date?, title?}: Wettbewerb mit Wertungen kopieren (z. B. aus dem Vorjahr)."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        src = self.competition(competition_id)
        try:
            date = datetime.date.fromisoformat(str(request.data.get("date") or ""))
        except ValueError:
            date = (
                src.date.replace(year=src.date.year + 1)
                if not (src.date.month == 2 and src.date.day == 29)
                else src.date.replace(year=src.date.year + 1, day=28)
            )
        title = str(request.data.get("title") or "").strip()[:200]
        if not title:
            title = src.title.replace(str(src.date.year), str(date.year))
        comp = Competition.objects.create(
            organization=self.org,
            title=title,
            form=src.form,
            own=src.own,
            organizer=src.organizer,
            drop_out=src.drop_out,
            fixed_order=src.fixed_order,
            lots=src.lots,
            occasion=src.occasion,
            discipline=src.discipline,
            location=src.location,
            date=date,
            description=src.description,
            details=src.details,
        )
        mapping = {}
        for sc in src.scorings.order_by("sort_order", "pk"):
            old_pk, source_id = sc.pk, sc.source_id
            sc.pk = None
            sc.id = None
            sc._state.adding = True
            sc.competition = comp
            sc.source_id = mapping.get(source_id)
            sc.save()
            mapping[old_pk] = sc.pk
        for p in src.prizes.all():
            Prize.objects.create(
                organization=self.org,
                competition=comp,
                name=p.name,
                sort_order=p.sort_order,
                award=p.award,
            )
        for t in src.teams.all():
            Team.objects.create(
                organization=self.org, competition=comp, name=t.name, sort_order=t.sort_order
            )
        record(self.org, request.user, "create", comp, diff({}, snapshot(comp)))
        return Response({"id": comp.pk}, status=status.HTTP_201_CREATED)


# --- Stechen ---


def _shootoff_data(so: ShootOff) -> dict:
    return {
        "id": so.pk,
        "scoring": so.scoring_id,
        "number": so.number,
        "shots": so.shots,
        "counted_shots": so.counted_shots,
        "entries": [
            {
                "id": e.pk,
                "key": e.key,
                "starter": e.starter_id,
                "unit": e.unit_id,
                "membership": e.membership_id,
                "name": e.name,
                "value": None if e.value is None else str(e.value),
            }
            for e in so.entries.all()
        ],
    }


def _shootoff_rules(data, defaults: tuple) -> tuple:
    """Schüsse und davon gewertet fürs Stechen; vor Ort festgelegt (Ralf 2026-11-01), sonst
    wie im vorigen Stechen oder wie unter „Einrichten“ vorgeschlagen."""
    shots = bird._positive(data["shots"], "shots") if "shots" in data else defaults[0]  # noqa: SLF001
    counted = (
        bird._positive(data["counted_shots"], "counted_shots")  # noqa: SLF001
        if "counted_shots" in data
        else defaults[1]
    )
    if shots and counted and counted > shots:
        raise ValidationError({"counted_shots": "Höchstens so viele wie Schüsse."})
    return shots, counted


class ShootOffsView(_Mixin, APIView):
    """GET: alle Stechen · POST {scoring, keys, shots?, counted_shots?}: Stechen für eine
    Gleichstandsgruppe anlegen."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        qs = ShootOff.objects.filter(scoring__competition=comp).prefetch_related("entries")
        return Response([_shootoff_data(so) for so in qs.order_by("scoring_id", "number")])

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        if comp.status == Competition.Status.FINAL:
            raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")
        scoring = get_object_or_404(Scoring, pk=request.data.get("scoring"), competition=comp)
        keys = request.data.get("keys") or []
        data = services.standings(comp)
        block = next(s for s in data["scorings"] if s["scoring"] == scoring.pk)
        group = next(
            (
                t
                for t in block["open"]
                if sorted(t["keys"]) == sorted(keys) and t["shootoff"] is None
            ),
            None,
        )
        if group is None:
            raise ValidationError("Für diese Gruppe ist kein Stechen nötig.")
        number = (scoring.shootoffs.aggregate(m=Max("number"))["m"] or 0) + 1
        previous = scoring.shootoffs.order_by("-number").first()
        defaults = (
            (previous.shots, previous.counted_shots)
            if previous
            else (scoring.shootoff_shots, scoring.shootoff_counted)
        )
        shots, counted = _shootoff_rules(request.data, defaults)
        so = ShootOff.objects.create(
            organization=self.org,
            scoring=scoring,
            number=number,
            shots=shots,
            counted_shots=counted,
        )
        rows = {r["key"]: r for r in block["rows"]}
        for key in group["keys"]:
            if key.startswith("u"):
                row = rows[key]
                best = Starter.objects.filter(pk=row.get("best_starter")).first()
                ShootOffEntry.objects.create(
                    organization=self.org,
                    shootoff=so,
                    unit_id=int(key[1:]),
                    membership=best.membership if best else None,
                    name=best.name if best else "",
                )
            else:
                starter = Starter.objects.get(pk=int(key[1:]), competition=comp)
                ShootOffEntry.objects.create(
                    organization=self.org, shootoff=so, starter=starter, name=starter.name
                )
        record(self.org, request.user, "create", so, diff({}, snapshot(so)))
        so = ShootOff.objects.prefetch_related("entries").get(pk=so.pk)
        return Response(_shootoff_data(so), status=status.HTTP_201_CREATED)


class ShootOffView(_Mixin, APIView):
    """PATCH {shots?, counted_shots?}: Regeln ändern, solange kein Wert eingetragen ist ·
    DELETE: Stechen entfernen (nur das letzte einer Wertung)."""

    manage_only = False

    @transaction.atomic
    def patch(self, request, org_id: int, competition_id: int, pk: int):
        comp = self.competition(competition_id)
        if comp.status == Competition.Status.FINAL:
            raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")
        so = get_object_or_404(ShootOff, pk=pk, scoring__competition=comp)
        if so.entries.filter(value__isnull=False).exists():
            raise ValidationError("Es sind schon Werte eingetragen; erst die Werte löschen.")
        before = snapshot(so)
        so.shots, so.counted_shots = _shootoff_rules(request.data, (so.shots, so.counted_shots))
        so.save(update_fields=["shots", "counted_shots"])
        record(self.org, request.user, "update", so, diff(before, snapshot(so)))
        so = ShootOff.objects.prefetch_related("entries").get(pk=so.pk)
        return Response(_shootoff_data(so))

    @transaction.atomic
    def delete(self, request, org_id: int, competition_id: int, pk: int):
        comp = self.competition(competition_id)
        if comp.status == Competition.Status.FINAL:
            raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")
        so = get_object_or_404(ShootOff, pk=pk, scoring__competition=comp)
        if so.scoring.shootoffs.filter(number__gt=so.number).exists():
            raise ValidationError("Erst das spätere Stechen entfernen.")
        record(self.org, request.user, "delete", so, diff(snapshot(so), {}))
        so.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShootOffEntryView(_Mixin, APIView):
    """PATCH {value?, membership?, name?}: Wert im Stechen, bei Untereinheiten den Schützen."""

    manage_only = False

    @transaction.atomic
    def patch(self, request, org_id: int, competition_id: int, pk: int):
        comp = self.competition(competition_id)
        if comp.status == Competition.Status.FINAL:
            raise ValidationError("Der Wettbewerb ist endgültig abgeschlossen.")
        entry = get_object_or_404(
            ShootOffEntry.objects.select_related("shootoff__scoring__source"),
            pk=pk,
            shootoff__scoring__competition=comp,
        )
        before = snapshot(entry)
        data = request.data
        scoring = entry.shootoff.scoring
        if "value" in data:
            value = _decimal(data["value"], "value")
            if value is not None:
                metric = scoring.source if scoring.kind == Scoring.Kind.UNIT else scoring
                _check_decimals(value, metric.decimals, "value")
                per_shot = scoring.max_per_shot or metric.max_per_shot
                count = entry.shootoff.counted_shots or entry.shootoff.shots
                if per_shot is not None and count and value > per_shot * count:
                    raise ValidationError(
                        {"value": f"Höchstens {services.fmt(per_shot * count, 0)}."}
                    )
            entry.value = value
        if entry.unit_id and "membership" in data:
            if data["membership"]:
                m = (
                    Membership.objects.filter(
                        organization=self.org, pk=data["membership"], purged_at__isnull=True
                    )
                    .select_related("person")
                    .first()
                )
                if m is None:
                    raise ValidationError({"membership": "Unbekanntes Mitglied."})
                entry.membership = m
                entry.name = _person_name(m)
            else:
                entry.membership = None
                entry.name = str(data.get("name") or "").strip()[:200]
        entry.save()
        changes = diff(before, snapshot(entry))
        if changes:
            record(self.org, request.user, "update", entry, changes)
        return Response(
            _shootoff_data(ShootOff.objects.prefetch_related("entries").get(pk=entry.shootoff_id))
        )


class UnitMembersView(_Mixin, APIView):
    """GET ?unit=: Mitglieder einer Untereinheit am Wettbewerbstag (Schütze im Stechen)."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        from members.models import DepartmentMembership

        comp = self.competition(competition_id)
        unit = _unit_or_none(self.org, request.query_params.get("unit"))
        if unit is None:
            return Response([])
        on = comp.date
        ids = (
            DepartmentMembership.objects.filter(
                organization=self.org, department=unit, valid_from__lte=on
            )
            .exclude(valid_until__lt=on)
            .values_list("membership_id", flat=True)
        )
        rows = Membership.objects.filter(pk__in=ids, purged_at__isnull=True).select_related(
            "person"
        )
        return Response(
            sorted(
                ({"membership": m.pk, "name": _person_name(m)} for m in rows),
                key=lambda r: r["name"],
            )
        )


class ExportView(_Mixin, APIView):
    """GET ?als=pdf|xlsx: Auswertung als PDF oder Excel."""

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        kind = request.query_params.get("als", "pdf")
        name = report.filename(comp)
        if kind == "schiessliste":
            try:
                blank = max(0, min(int(request.query_params.get("leerzeilen", 10)), 60))
            except ValueError:
                blank = 10
            body = report.shooting_list(
                comp,
                order=request.query_params.get("sortierung", "name"),
                blank_rows=blank,
                empty=request.query_params.get("leer") == "1",
            )
            resp = HttpResponse(body, content_type="application/pdf")
            resp["Content-Disposition"] = (
                f'inline; filename="{name.replace("Auswertung", "Schiessliste")}.pdf"'
            )
            return resp
        if kind in ("losliste", "pfaenderliste"):
            if comp.form != Competition.Form.BIRD:
                raise ValidationError("Das ist kein Vogelschießen.")
            if kind == "losliste":
                try:
                    blank = max(0, min(int(request.query_params.get("leerzeilen", 10)), 60))
                except ValueError:
                    blank = 10
                body, label = report.lot_list(comp, blank), "Losliste"
            else:
                body, label = report.prize_sheet(comp), "Pfaenderliste"
            resp = HttpResponse(body, content_type="application/pdf")
            resp["Content-Disposition"] = (
                f'inline; filename="{name.replace("Auswertung", label)}.pdf"'
            )
            return resp
        if kind == "stechliste":
            so = get_object_or_404(
                ShootOff, pk=request.query_params.get("stechen") or 0, scoring__competition=comp
            )
            resp = HttpResponse(report.shootoff_list(comp, so), content_type="application/pdf")
            resp["Content-Disposition"] = f'inline; filename="Stechliste-{so.number}.pdf"'
            return resp
        if kind == "xlsx":
            body = report.xlsx(comp)
            resp = HttpResponse(
                body,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
            return resp
        resp = HttpResponse(report.pdf(comp), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{name}.pdf"'
        return resp
