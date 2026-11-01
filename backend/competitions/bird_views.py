"""Vogelschießen in der Verwaltung: Pfänder, Losnummern, Schüsse (Konzept Abschnitt 5b)."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import diff, record, snapshot

from . import bird
from .models import Competition, Prize, Starter
from .views import _jsonable, _Mixin


class _BirdMixin(_Mixin):
    def bird_competition(self, pk) -> Competition:
        comp = self.competition(pk)
        if comp.form != Competition.Form.BIRD:
            raise ValidationError(gettext("Das ist kein Vogelschießen."))
        return comp


def _state(comp: Competition) -> dict:
    return _jsonable(bird.state(comp))


class BirdStateView(_BirdMixin, APIView):
    """GET: Pfänder, Reihenfolge, wer dran ist, Zähler, Losnummern und Kennzahlen."""

    def get(self, request, org_id: int, competition_id: int):
        return Response(_state(self.bird_competition(competition_id)))


class PrizesView(_BirdMixin, APIView):
    """POST {name, award?}: Pfand hinzufügen (Wettbewerbe verwalten)."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.bird_competition(competition_id)
        name = str(request.data.get("name", "")).strip()[:100]
        if not name:
            raise ValidationError({"name": gettext("Bitte einen Namen angeben.")})
        last = comp.prizes.aggregate(m=Max("sort_order"))["m"] or 0
        p = Prize.objects.create(
            organization=self.org,
            competition=comp,
            name=name,
            award=str(request.data.get("award", "")).strip()[:200],
            sort_order=last + 1,
        )
        record(self.org, request.user, "create", p, diff({}, snapshot(p)))
        return Response(_state(comp), status=status.HTTP_201_CREATED)


SETUP_FIELDS = ("name", "award", "sort_order")
RESULT_FIELDS = ("winner", "shot_number", "shots_for")


class PrizeView(_BirdMixin, APIView):
    """PATCH: Name, Preis, Reihenfolge (verwalten) oder nachträglich erfasstes Ergebnis
    (winner, shot_number, shots_for; auch mit „Ergebnisse erfassen“) · DELETE: entfernen."""

    manage_only = False

    def _get(self, competition_id, pk) -> Prize:
        comp = self.bird_competition(competition_id)
        return get_object_or_404(
            Prize.objects.select_related("competition"), pk=pk, competition=comp
        )

    @transaction.atomic
    def patch(self, request, org_id: int, competition_id: int, pk: int):
        p = self._get(competition_id, pk)
        data = request.data
        if any(f in data for f in SETUP_FIELDS):
            if not self.can_manage:
                raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
            if p.competition.status == Competition.Status.FINAL:
                raise ValidationError(gettext("Der Wettbewerb ist endgültig abgeschlossen."))
            before = snapshot(p)
            if "name" in data:
                name = str(data["name"] or "").strip()[:100]
                if not name:
                    raise ValidationError({"name": gettext("Bitte einen Namen angeben.")})
                p.name = name
            if "award" in data:
                p.award = str(data["award"] or "").strip()[:200]
            if "sort_order" in data:
                try:
                    p.sort_order = max(0, min(int(data["sort_order"]), 999))
                except (TypeError, ValueError) as exc:
                    raise ValidationError({"sort_order": gettext("Ungültig.")}) from exc
            p.save()
            changes = diff(before, snapshot(p))
            if changes:
                record(self.org, request.user, "update", p, changes)
        if any(f in data for f in RESULT_FIELDS):
            bird.set_result(
                self.org, request.user, p, {f: data[f] for f in RESULT_FIELDS if f in data}
            )
        return Response(_state(p.competition))

    @transaction.atomic
    def delete(self, request, org_id: int, competition_id: int, pk: int):
        if not self.can_manage:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
        p = self._get(competition_id, pk)
        if p.fallen:
            raise ValidationError(
                gettext("Das Pfand ist schon gefallen. Erst das Ergebnis entfernen.")
            )
        record(self.org, request.user, "delete", p, diff(snapshot(p), {}))
        p.delete()
        return Response(_state(p.competition))


class ShotView(_BirdMixin, APIView):
    """POST {starter, hits?, client_key?}: einen Schuss zählen, ggf. mit gefallenen Pfändern."""

    manage_only = False

    def post(self, request, org_id: int, competition_id: int):
        comp = self.bird_competition(competition_id)
        starter = get_object_or_404(Starter, pk=request.data.get("starter") or 0, competition=comp)
        hits = request.data.get("hits") or []
        if not isinstance(hits, list):
            raise ValidationError({"hits": gettext("Ungültige Angabe.")})
        bird.fire(
            self.org,
            request.user,
            comp,
            starter,
            hits,
            client_key=bird.parse_key(request.data.get("client_key")),
        )
        return Response(_state(comp), status=status.HTTP_201_CREATED)


class UndoView(_BirdMixin, APIView):
    """POST: den letzten Schuss zurücknehmen."""

    manage_only = False

    def post(self, request, org_id: int, competition_id: int):
        comp = self.bird_competition(competition_id)
        bird.undo(self.org, request.user, comp, bird.parse_key(request.data.get("client_key")))
        return Response(_state(comp))


class DrawView(_BirdMixin, APIView):
    """POST {starter, number?}: Losnummer aus dem Hut eintragen oder (ohne) digital ziehen."""

    manage_only = False

    def post(self, request, org_id: int, competition_id: int):
        comp = self.bird_competition(competition_id)
        starter = get_object_or_404(Starter, pk=request.data.get("starter") or 0, competition=comp)
        raw = request.data.get("number")
        how = "hut" if raw not in (None, "") else "digital"
        number, note = bird.draw(self.org, request.user, comp, starter, raw, how)
        return Response({"number": number, "note": note, "state": _state(comp)})


class DrawAllView(_BirdMixin, APIView):
    """POST: alle ohne Losnummer auf einmal auslosen."""

    manage_only = False

    def post(self, request, org_id: int, competition_id: int):
        comp = self.bird_competition(competition_id)
        count = bird.draw_all(self.org, request.user, comp)
        return Response({"count": count, "state": _state(comp)})
