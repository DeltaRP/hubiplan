"""Standzugang (Konzept Abschnitt 5c): ein Link bzw. QR-Code für ein geliehenes Tablet ohne
eigenes Konto. Er öffnet nur diesen Wettbewerb im Standmodus, erlaubt nur das Erfassen,
zeigt von Mitgliedern nur Name und Untereinheit und läuft am Ende des Tages ab oder wird
beendet."""

from __future__ import annotations

import datetime

from django.core.cache import cache
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import current_via, record
from core.tenancy import rls_bypass, unit_context

from . import services
from .models import Competition, StandAccess, hash_token
from .target_views import detect_photo, photo_rate
from .views import (
    MODULE,
    CompetitionSerializer,
    ScoringSerializer,
    _jsonable,
    _Mixin,
    _starters_with_values,
    _units,
    create_shootoff,
    list_shootoffs,
    sync,
    unit_members,
    update_shootoff,
    update_shootoff_entry,
)


def _access_data(a: StandAccess) -> dict:
    return {
        "id": a.pk,
        "label": a.label,
        "expires_at": a.expires_at.isoformat(),
        "active": a.is_active,
        "created_at": a.created_at.isoformat(),
    }


def _end_of_day(day: datetime.date) -> datetime.datetime:
    tz = timezone.get_current_timezone()
    return datetime.datetime.combine(day, datetime.time(23, 59, 59), tzinfo=tz)


class StandAccessListView(_Mixin, APIView):
    """GET: Standzugänge · POST {label?}: neuen Standzugang erzeugen (der Schlüssel erscheint
    nur einmal). Gültig bis zum Ende des Wettbewerbstags (oder heute, wenn der schon war)."""

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        return Response([_access_data(a) for a in comp.stand_accesses.all()])

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        if comp.status == Competition.Status.FINAL:
            raise ValidationError(gettext("Der Wettbewerb ist endgültig abgeschlossen."))
        label = str(request.data.get("label", "")).strip()[:100]
        day = max(comp.date, timezone.localdate())
        access, token = StandAccess.create(comp, label, request.user, _end_of_day(day))
        record(
            self.org,
            request.user,
            "create",
            access,
            {
                "Standzugang": [
                    None,
                    f"gültig bis {timezone.localtime(access.expires_at):%d.%m.%Y %H:%M}",
                ]
            },
        )
        return Response({**_access_data(access), "token": token}, status=status.HTTP_201_CREATED)


class StandAccessView(_Mixin, APIView):
    """DELETE: Standzugang beenden."""

    @transaction.atomic
    def delete(self, request, org_id: int, competition_id: int, pk: int):
        comp = self.competition(competition_id)
        access = get_object_or_404(StandAccess, pk=pk, competition=comp)
        if access.revoked_at is None:
            access.revoked_at = timezone.now()
            access.save(update_fields=["revoked_at"])
            record(self.org, request.user, "update", access, {"Standzugang": ["aktiv", "beendet"]})
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Öffentlich mit Schlüssel (ohne Anmeldung) ---

RATE = (1500, 600)  # 1500 Aufrufe je 10 Minuten und Zugang (Stand alle 3 s, Abgleich, Laden)


class _StandPublic(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def resolve(self, token: str) -> StandAccess:
        key = f"stand:{hash_token(token)[:32]}"
        count = cache.get(key, 0)
        if count >= RATE[0]:
            raise ValidationError(gettext("Zu viele Aufrufe. Bitte kurz warten."))
        cache.set(key, count + 1, RATE[1])
        with rls_bypass():
            access = (
                StandAccess.objects.select_related("competition", "organization")
                .filter(token_hash=hash_token(token))
                .first()
            )
        if (
            access is None
            or not access.is_active
            or MODULE not in (access.organization.enabled_modules or [])
        ):
            raise Http404
        return access

    def finish(self, data) -> Response:
        resp = Response(_jsonable(data))
        resp["Cache-Control"] = "no-store"
        resp["X-Robots-Tag"] = "noindex, nofollow"
        return resp


class StandDetailView(_StandPublic):
    """GET: Einrichtung des Wettbewerbs für den Standmodus."""

    def get(self, request, token: str):
        access = self.resolve(token)
        with unit_context(access.organization_id):
            comp = Competition.objects.get(pk=access.competition_id)
            data = dict(CompetitionSerializer(comp).data)
            data["description"] = ""
            data["details"] = []
            data["scorings"] = ScoringSerializer(
                comp.scorings.all(), many=True, context={"competition": comp}
            ).data
            data["units"] = [{"id": u.pk, "name": u.name} for u in _units(comp.organization)]
            data["prizes"] = [
                {"id": p.pk, "name": p.name, "award": p.award, "sort_order": p.sort_order}
                for p in comp.prizes.all()
            ]
            data["can_manage"] = False
            data["stand_access"] = {
                "label": access.label,
                "expires_at": access.expires_at.isoformat(),
            }
        return self.finish(data)


class StandStartersView(_StandPublic):
    def get(self, request, token: str):
        access = self.resolve(token)
        with unit_context(access.organization_id):
            comp = Competition.objects.get(pk=access.competition_id)
            data = _starters_with_values(comp)
        return self.finish(data)


class StandStandingsView(_StandPublic):
    """GET: Ranglisten aller Wertungen für die Live-Tabellen (ohne Kennzahlen)."""

    def get(self, request, token: str):
        access = self.resolve(token)
        with unit_context(access.organization_id):
            comp = Competition.objects.get(pk=access.competition_id)
            data = services.standings(comp)
        return self.finish({"scorings": data["scorings"], "open_shootoffs": data["open_shootoffs"]})


class StandVersionView(_StandPublic):
    def get(self, request, token: str):
        access = self.resolve(token)
        with unit_context(access.organization_id):
            comp = Competition.objects.get(pk=access.competition_id)
            return self.finish({"version": services.version(comp)})


class StandMembersView(_StandPublic):
    """GET: Mitglieder am Wettbewerbstag, nur Name und Untereinheit (Suche ohne Netz)."""

    def get(self, request, token: str):
        from django.db.models import Q

        from members.models import Membership
        from organizations.models import Department

        access = self.resolve(token)
        with unit_context(access.organization_id):
            comp = Competition.objects.get(pk=access.competition_id)
            on = comp.date
            rows = (
                Membership.objects.filter(
                    organization_id=access.organization_id, purged_at__isnull=True
                )
                .filter(periods__entry_date__lte=on)
                .filter(Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=on))
                .distinct()
                .select_related("person")
            )
            units = services.units_on(comp.organization, on)
            names = dict(
                Department.objects.filter(organization_id=access.organization_id).values_list(
                    "pk", "name"
                )
            )
            data = [
                {
                    "membership": m.pk,
                    "name": f"{m.person.first_name} {m.person.last_name}".strip(),
                    "birth_year": None,
                    "unit": units.get(m.pk),
                    "unit_name": names.get(units.get(m.pk), ""),
                }
                for m in sorted(rows, key=lambda m: (m.person.last_name, m.person.first_name))
            ]
        return self.finish(data)


class StandSyncView(_StandPublic):
    """POST {ops}: Eingaben nachreichen, wie im angemeldeten Standmodus."""

    def post(self, request, token: str):
        access = self.resolve(token)
        via = current_via.set(f"Standzugang {access.label}".strip()[:100])
        try:
            with unit_context(access.organization_id):
                comp = Competition.objects.select_related("organization").get(
                    pk=access.competition_id
                )
                data = sync(
                    comp.organization,
                    None,
                    comp,
                    request.data.get("ops"),
                    request.data.get("generation"),
                )
        finally:
            current_via.reset(via)
        return self.finish(data)


class _StandWrite(_StandPublic):
    """Schreiben über den Standzugang: wie „Ergebnisse erfassen“, im Protokoll mit Zugang."""

    def run(self, token: str, action):
        access = self.resolve(token)
        via = current_via.set(f"Standzugang {access.label}".strip()[:100])
        try:
            with unit_context(access.organization_id):
                comp = Competition.objects.select_related("organization").get(
                    pk=access.competition_id
                )
                return action(comp.organization, comp)
        finally:
            current_via.reset(via)


class StandShootoffsView(_StandWrite):
    """GET: Stechen · POST {scoring, keys, shots?, counted_shots?}: Stechen anlegen
    (Ralf 2026-11-01: auch am geliehenen Tablet; Abschluss bleibt angemeldet)."""

    def get(self, request, token: str):
        return self.finish(self.run(token, lambda org, comp: list_shootoffs(comp)))

    def post(self, request, token: str):
        data = self.run(token, lambda org, comp: create_shootoff(org, None, comp, request.data))
        resp = self.finish(data)
        resp.status_code = status.HTTP_201_CREATED
        return resp


class StandShootoffView(_StandWrite):
    """PATCH {shots?, counted_shots?}: Regeln des Stechens, solange kein Wert da ist."""

    def patch(self, request, token: str, pk: int):
        return self.finish(
            self.run(token, lambda org, comp: update_shootoff(org, None, comp, pk, request.data))
        )


class StandShootoffEntryView(_StandWrite):
    """PATCH {value?, membership?}: Wert im Stechen, beim Zugstechen den Schützen."""

    def patch(self, request, token: str, pk: int):
        return self.finish(
            self.run(
                token, lambda org, comp: update_shootoff_entry(org, None, comp, pk, request.data)
            )
        )


class StandUnitMembersView(_StandWrite):
    """GET ?unit=: Mitglieder einer Untereinheit (nur Name) für den Schützen im Zugstechen."""

    def get(self, request, token: str):
        unit = request.query_params.get("unit")
        return self.finish(self.run(token, lambda org, comp: unit_members(org, comp, unit)))


class StandPhotoView(_StandPublic):
    """POST (multipart) photo, scoring: Treffer auf dem Foto vorschlagen (nichts gespeichert)."""

    parser_classes = [MultiPartParser]

    def post(self, request, token: str):
        access = self.resolve(token)
        photo_rate(f"s{access.pk}")
        with unit_context(access.organization_id):
            comp = Competition.objects.get(pk=access.competition_id)
            data = detect_photo(comp, request.data, request.FILES)
        return self.finish(data)
