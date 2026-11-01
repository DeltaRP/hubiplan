"""Fremde Wettbewerbe (Konzept Abschnitte 4 und 7): Ein anderer richtet aus, die Einheit
trägt ihre eigenen Starter und Mannschaften mit dem Platz und Wert des Ausrichters ein.
Die Verbindung zu den Meldungen folgt, sobald es die Meldungen gibt."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import diff, record, snapshot

from .models import Competition, Placing, Scoring, Starter, Team
from .views import _check_decimals, _decimal, _Mixin


def _team_data(t: Team) -> dict:
    return {
        "id": t.pk,
        "name": t.name,
        "sort_order": t.sort_order,
        "members": [m.pk for m in t.members.all()],
    }


class _ForeignMixin(_Mixin):
    def foreign_competition(self, pk) -> Competition:
        comp = self.competition(pk)
        if comp.own:
            raise ValidationError(gettext("Das ist kein fremder Wettbewerb."))
        return comp


def _open(comp: Competition) -> None:
    if comp.status == Competition.Status.FINAL:
        raise ValidationError(gettext("Der Wettbewerb ist endgültig abgeschlossen."))


class TeamsView(_ForeignMixin, APIView):
    """GET: eigene Mannschaften · POST {name}: Mannschaft hinzufügen."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        comp = self.foreign_competition(competition_id)
        return Response([_team_data(t) for t in comp.teams.prefetch_related("members")])

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.foreign_competition(competition_id)
        _open(comp)
        name = str(request.data.get("name", "")).strip()[:100]
        if not name:
            name = f"Mannschaft {comp.teams.count() + 1}"
        last = comp.teams.aggregate(m=Max("sort_order"))["m"] or 0
        t = Team.objects.create(
            organization=self.org, competition=comp, name=name, sort_order=last + 1
        )
        record(self.org, request.user, "create", t, diff({}, snapshot(t)))
        return Response(_team_data(t), status=status.HTTP_201_CREATED)


class TeamView(_ForeignMixin, APIView):
    """PATCH {name?, members?}: umbenennen, Schützen zuordnen · DELETE: entfernen."""

    manage_only = False

    def _get(self, competition_id, pk) -> Team:
        comp = self.foreign_competition(competition_id)
        _open(comp)
        return get_object_or_404(Team, pk=pk, competition=comp)

    @transaction.atomic
    def patch(self, request, org_id: int, competition_id: int, pk: int):
        t = self._get(competition_id, pk)
        before = snapshot(t)
        if "name" in request.data:
            name = str(request.data["name"] or "").strip()[:100]
            if not name:
                raise ValidationError({"name": gettext("Bitte einen Namen angeben.")})
            t.name = name
            t.save()
        if "members" in request.data:
            ids = request.data["members"] or []
            if not isinstance(ids, list):
                raise ValidationError({"members": gettext("Ungültige Angabe.")})
            members = list(Starter.objects.filter(competition=t.competition, pk__in=ids))
            if len(members) != len({int(i) for i in ids}):
                raise ValidationError({"members": gettext("Unbekannter Schütze.")})
            old = sorted(m.name for m in t.members.all())
            t.members.set(members, through_defaults={"organization": self.org})
            new = sorted(m.name for m in members)
            if old != new:
                record(
                    self.org,
                    request.user,
                    "update",
                    t,
                    {"Schützen": [", ".join(old), ", ".join(new)]},
                )
        changes = diff(before, snapshot(t))
        if changes:
            record(self.org, request.user, "update", t, changes)
        return Response(_team_data(t))

    @transaction.atomic
    def delete(self, request, org_id: int, competition_id: int, pk: int):
        t = self._get(competition_id, pk)
        record(self.org, request.user, "delete", t, diff(snapshot(t), {}))
        t.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlacingView(_ForeignMixin, APIView):
    """PUT {scoring, starter|team, place?, value?, note?}: Platz und Wert vom Ausrichter
    eintragen (alles leer: entfernen)."""

    manage_only = False

    @transaction.atomic
    def put(self, request, org_id: int, competition_id: int):
        comp = self.foreign_competition(competition_id)
        _open(comp)
        data = request.data
        scoring = get_object_or_404(Scoring, pk=data.get("scoring") or 0, competition=comp)
        target: dict = {}
        if scoring.kind == Scoring.Kind.TEAM:
            target["team"] = get_object_or_404(Team, pk=data.get("team") or 0, competition=comp)
        else:
            target["starter"] = get_object_or_404(
                Starter, pk=data.get("starter") or 0, competition=comp
            )
        place = data.get("place")
        if place in (None, ""):
            place = None
        else:
            try:
                place = int(str(place).strip())
            except ValueError as exc:
                raise ValidationError(
                    {"place": gettext("Bitte eine ganze Zahl eingeben.")}
                ) from exc
            if place < 1 or place > 100000:
                raise ValidationError({"place": gettext("Bitte einen Platz ab 1 eingeben.")})
            if scoring.field_size and place > scoring.field_size:
                raise ValidationError(
                    {
                        "place": gettext("Es gab nur {field_size} Teilnehmer.").format(
                            field_size=scoring.field_size
                        )
                    }
                )
        value = _decimal(data.get("value"), "value")
        if value is not None:
            _check_decimals(value, scoring.decimals, "value")
        note = str(data.get("note") or "").strip()[:200]
        existing = Placing.objects.filter(scoring=scoring, **target).first()
        if place is None and value is None and not note:
            if existing:
                record(self.org, request.user, "delete", existing, diff(snapshot(existing), {}))
                existing.delete()
            return Response({"place": None, "value": None, "note": ""})
        before = snapshot(existing) if existing else {}
        if existing is None:
            existing = Placing(organization=self.org, scoring=scoring, **target)
        existing.place = place
        existing.value = value
        existing.note = note
        existing.save()
        changes = diff(before, snapshot(existing))
        if changes:
            record(self.org, request.user, "update" if before else "create", existing, changes)
        if comp.status == Competition.Status.PREPARATION:
            comp.status = Competition.Status.RUNNING
            comp.save(update_fields=["status", "updated_at"])
        return Response(
            {
                "place": existing.place,
                "value": None if value is None else str(value),
                "note": existing.note,
            }
        )
