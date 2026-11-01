"""Auszeichnungen, Reihen, Wanderpokale und vergebene Titel (Schritt 4 der Wettbewerbe).

- ``competitions/<id>/awards/``: Auszeichnungen einer Wertung bzw. eines Pfands einrichten
- ``competitions/series/``: Reihen (Archiv, Bestenliste, Vergleich der Untereinheiten)
- ``competitions/trophies/``: Wanderpokale mit Inhaberliste
- ``competitions/grants/``: vergebene Titel, Würdenvorschläge, frühere Jahre von Hand
- ``competitions/member/<membership>/``: Reiter „Wettbewerbe“ der Mitgliedsakte
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import COMPETITIONS_MANAGE, COMPETITIONS_RESULTS, MEMBERS_EDIT, MEMBERS_VIEW
from audit.log import diff, record, snapshot
from core.api_base import AuditMixin, OrgScopedMixin
from members.models import Membership
from organizations.models import Organization

from . import awards
from .models import Award, AwardGrant, Competition, Series, Trophy
from .views import MODULE, _Mixin


def award_data(a: Award) -> dict:
    return {
        "id": a.pk,
        "scoring": a.scoring_id,
        "prize": a.prize_id,
        "place_from": a.place_from,
        "place_to": a.place_to,
        "title": a.title,
        "item": a.item,
        "dignity": a.dignity_id,
        "dignity_name": a.dignity.name if a.dignity_id else "",
        "trophy": a.trophy_id,
        "trophy_name": a.trophy.name if a.trophy_id else "",
        "sort_order": a.sort_order,
    }


def _text(data, field, limit) -> str:
    return str(data.get(field) or "").strip()[:limit]


def _place(raw, field) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: gettext("Bitte einen Platz angeben.")}) from None
    if not 1 <= value <= 999:
        raise ValidationError({field: gettext("Bitte einen Platz von 1 bis 999 angeben.")})
    return value


def _apply_award(org, comp: Competition, a: Award, data, *, partial: bool) -> None:
    from honors.models import Dignity

    if "scoring" in data or "prize" in data or not partial:
        scoring_id = data.get("scoring", a.scoring_id if partial else None)
        prize_id = data.get("prize", a.prize_id if partial else None)
        if scoring_id and not comp.scorings.filter(pk=scoring_id).exists():
            raise ValidationError({"scoring": gettext("Unbekannte Wertung.")})
        if prize_id and not comp.prizes.filter(pk=prize_id).exists():
            raise ValidationError({"prize": gettext("Unbekanntes Pfand.")})
        if bool(scoring_id) == bool(prize_id):
            raise ValidationError({"scoring": gettext("Bitte eine Wertung oder ein Pfand wählen.")})
        a.scoring_id = scoring_id or None
        a.prize_id = prize_id or None
    if "place_from" in data or not partial:
        a.place_from = _place(data.get("place_from", 1), "place_from")
    if "place_to" in data or not partial:
        a.place_to = _place(data.get("place_to", a.place_from), "place_to")
    if a.place_to < a.place_from:
        raise ValidationError({"place_to": gettext("„bis Platz“ liegt vor „ab Platz“.")})
    for field, limit in (("title", 200), ("item", 200)):
        if field in data or not partial:
            setattr(a, field, _text(data, field, limit))
    if "dignity" in data or not partial:
        raw = data.get("dignity")
        a.dignity = get_object_or_404(Dignity, pk=raw, organization=org) if raw else None
    if "trophy" in data or not partial:
        raw = data.get("trophy")
        a.trophy = get_object_or_404(Trophy, pk=raw, organization=org) if raw else None
    if "sort_order" in data:
        a.sort_order = _place(data["sort_order"], "sort_order") if data["sort_order"] else 0
    if not (a.title or a.item or a.dignity_id or a.trophy_id):
        raise ValidationError(
            {
                "title": gettext(
                    "Bitte einen Titel, einen Preis, eine Würde oder einen Pokal angeben."
                )
            }
        )


class AwardsView(_Mixin, APIView):
    """GET: Auszeichnungen des Wettbewerbs · POST: neue Auszeichnung."""

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        qs = comp.awards.select_related("dignity", "trophy")
        return Response([award_data(a) for a in qs])

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        a = Award(organization=self.org, competition=comp)
        _apply_award(self.org, comp, a, request.data, partial=False)
        a.save()
        record(self.org, request.user, "create", a, diff({}, snapshot(a)))
        return Response(award_data(a), status=status.HTTP_201_CREATED)


class AwardView(_Mixin, APIView):
    def _get(self, competition_id, pk) -> tuple[Competition, Award]:
        comp = self.competition(competition_id)
        return comp, get_object_or_404(Award, pk=pk, competition=comp)

    @transaction.atomic
    def patch(self, request, org_id: int, competition_id: int, pk: int):
        comp, a = self._get(competition_id, pk)
        before = snapshot(a)
        _apply_award(self.org, comp, a, request.data, partial=True)
        a.save()
        record(self.org, request.user, "update", a, diff(before, snapshot(a)))
        return Response(award_data(a))

    @transaction.atomic
    def delete(self, request, org_id: int, competition_id: int, pk: int):
        _, a = self._get(competition_id, pk)
        record(self.org, request.user, "delete", a, diff(snapshot(a), {}))
        a.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GrantAgainView(_Mixin, APIView):
    """POST: Auszeichnungen eines endgültigen Wettbewerbs neu vergeben (nach Änderung der
    Auszeichnungen); entschiedene Würdenvorschläge bleiben."""

    @transaction.atomic
    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        if comp.status != Competition.Status.FINAL:
            raise ValidationError(gettext("Vergeben wird erst, wenn der Wettbewerb endgültig ist."))
        awards.grant(comp)
        qs = comp.grants.select_related("competition", "trophy", "dignity")
        return Response([awards.grant_data(g) for g in qs])


# --- Reihen und Wanderpokale ---


class SeriesSerializer(serializers.ModelSerializer):
    competition_count = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = ["id", "name", "description", "on_website", "competition_count"]

    def get_competition_count(self, obj) -> int:
        return obj.competitions.count()

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(gettext("Bitte eine Bezeichnung angeben."))
        return value


class SeriesViewSet(_Mixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = SeriesSerializer

    def get_queryset(self):
        return Series.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    def retrieve(self, request, *args, **kwargs):
        return Response(awards.series_archive(self.get_object()))


class TrophySerializer(serializers.ModelSerializer):
    holders = serializers.SerializerMethodField()

    class Meta:
        model = Trophy
        fields = ["id", "name", "description", "keep_after", "is_archived", "on_website", "holders"]

    def get_holders(self, obj) -> list:
        return awards.trophy_holders(obj)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(gettext("Bitte eine Bezeichnung angeben."))
        return value

    def validate_keep_after(self, value):
        if value is not None and not 1 <= value <= 20:
            raise serializers.ValidationError(gettext("Bitte eine Zahl von 1 bis 20 angeben."))
        return value


class TrophyViewSet(_Mixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = TrophySerializer

    def get_queryset(self):
        return Trophy.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}


# --- Vergebene Auszeichnungen ---


def _apply_grant(org, g: AwardGrant, data, *, partial: bool) -> None:
    """Von Hand eingetragene Auszeichnung (frühere Jahre, Altdaten)."""
    if "year" in data or not partial:
        try:
            year = int(data.get("year"))
        except (TypeError, ValueError):
            raise ValidationError({"year": gettext("Bitte ein Jahr angeben.")}) from None
        if not 1000 <= year <= 2999:
            raise ValidationError({"year": gettext("Bitte ein vierstelliges Jahr angeben.")})
        g.year = year
    for field, limit in (
        ("title", 200),
        ("item", 200),
        ("scoring_name", 100),
        ("value_text", 40),
        ("note", 200),
    ):
        if field in data or not partial:
            setattr(g, field, _text(data, field, limit))
    if "place" in data or not partial:
        g.place = _place(data["place"], "place") if data.get("place") else None
    if "series" in data or not partial:
        raw = data.get("series")
        g.series = get_object_or_404(Series, pk=raw, organization=org) if raw else None
    if "trophy" in data or not partial:
        raw = data.get("trophy")
        g.trophy = get_object_or_404(Trophy, pk=raw, organization=org) if raw else None
    if "membership" in data or not partial:
        raw = data.get("membership")
        g.membership = get_object_or_404(Membership, pk=raw, organization=org) if raw else None
    if "name" in data or not partial or ("membership" in data and g.membership_id):
        name = _text(data, "name", 200)
        if not name and g.membership_id:
            p = g.membership.person
            name = f"{p.first_name} {p.last_name}".strip()
        g.name = name
    if not g.name:
        raise ValidationError(
            {"name": gettext("Bitte ein Mitglied wählen oder einen Namen angeben.")}
        )
    if not (g.title or g.item or g.trophy_id):
        raise ValidationError({"title": gettext("Bitte einen Titel, Preis oder Pokal angeben.")})


class GrantsView(_Mixin, APIView):
    """GET ?reihe=<id> · ?pokal=<id> · ?vorschlaege=1 · POST: früheres Jahr nachtragen."""

    def get(self, request, org_id: int):
        qs = AwardGrant.objects.filter(organization=self.org).select_related(
            "competition", "trophy", "dignity"
        )
        p = request.query_params
        if p.get("reihe", "").isdigit():
            qs = qs.filter(series_id=int(p["reihe"]))
        if p.get("pokal", "").isdigit():
            qs = qs.filter(trophy_id=int(p["pokal"]))
        if p.get("vorschlaege"):
            qs = qs.filter(dignity_state=AwardGrant.DignityState.PROPOSED)
        return Response([awards.grant_data(g) for g in qs[:2000]])

    @transaction.atomic
    def post(self, request, org_id: int):
        g = AwardGrant(organization=self.org, manual=True)
        _apply_grant(self.org, g, request.data, partial=False)
        g.save()
        record(self.org, request.user, "create", g, diff({}, snapshot(g)))
        return Response(awards.grant_data(g), status=status.HTTP_201_CREATED)


class GrantView(_Mixin, APIView):
    def _get(self, pk) -> AwardGrant:
        return get_object_or_404(AwardGrant, pk=pk, organization=self.org)

    @transaction.atomic
    def patch(self, request, org_id: int, pk: int):
        g = self._get(pk)
        if not g.manual:
            # Aus einem Wettbewerb vergeben: nur Bemerkung änderbar
            data = {k: v for k, v in request.data.items() if k == "note"}
        else:
            data = request.data
        before = snapshot(g)
        _apply_grant(self.org, g, data, partial=True)
        g.save()
        record(self.org, request.user, "update", g, diff(before, snapshot(g)))
        return Response(awards.grant_data(g))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        g = self._get(pk)
        if not g.manual and g.competition_id:
            raise ValidationError(
                gettext("Aus einem Wettbewerb vergeben: dort die Auszeichnung ändern.")
            )
        record(self.org, request.user, "delete", g, diff(snapshot(g), {}))
        g.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DignityDecisionView(_Mixin, APIView):
    """POST {decision: "bestaetigen"|"ablehnen"}: Würdenvorschlag entscheiden. Bestätigen
    legt die Regentschaft an und braucht zusätzlich das Recht „Mitglieder bearbeiten“."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        g = get_object_or_404(AwardGrant.objects.select_for_update(), pk=pk, organization=self.org)
        decision = request.data.get("decision")
        if g.dignity_state != AwardGrant.DignityState.PROPOSED:
            raise ValidationError(gettext("Dieser Vorschlag ist schon entschieden."))
        before = snapshot(g)
        if decision == "bestaetigen":
            if MEMBERS_EDIT not in self.org_permissions:
                raise PermissionDenied(
                    gettext("Würden eintragen braucht das Recht „Mitglieder bearbeiten“.")
                )
            awards.confirm_dignity(self.org, request.user, g)
        elif decision == "ablehnen":
            g.dignity_state = AwardGrant.DignityState.REJECTED
            g.save(update_fields=["dignity_state"])
        else:
            raise ValidationError({"decision": gettext("Bitte bestätigen oder ablehnen.")})
        record(self.org, request.user, "update", g, diff(before, snapshot(g)))
        return Response(awards.grant_data(g))


class MemberHistoryView(OrgScopedMixin, APIView):
    """Reiter „Wettbewerbe“ der Mitgliedsakte (Recht „Mitglieder ansehen“)."""

    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    read_permission = MEMBERS_VIEW

    def get(self, request, org_id: int, membership_id: int):
        if MODULE not in (self.org.enabled_modules or []):
            raise NotFound(gettext("Das Modul Wettbewerbe ist nicht freigeschaltet."))
        m = get_object_or_404(Membership, pk=membership_id, organization=self.org)
        ids = list(
            Membership.objects.filter(organization=self.org, person_id=m.person_id).values_list(
                "pk", flat=True
            )
        )
        data = awards.member_history(self.org, ids)
        data["can_open"] = bool({COMPETITIONS_MANAGE, COMPETITIONS_RESULTS} & self.org_permissions)
        return Response(data)


class PortalResultsView(APIView):
    """Mitgliederbereich und App: „Meine Ergebnisse“ – eigene Starts mit Platz und Wert,
    Titel und Auszeichnungen über alle Jahre (nur eigene, keine fremden Namen)."""

    def get(self, request, access_id: int):
        from core.tenancy import tenant_context
        from portal.views import _portal_access

        access = _portal_access(request.user, access_id)
        club = access.organization
        if MODULE not in (club.enabled_modules or []):
            return Response({"starts": [], "grants": []})
        with tenant_context(club.pk, request.user.pk):
            ids = list(
                Membership.objects.filter(
                    organization=club, person_id=access.membership.person_id
                ).values_list("pk", flat=True)
            )
            data = awards.member_history(club, ids)
        # Nur Abgeschlossenes und Laufendes; Vorbereitung bleibt intern
        data["starts"] = [s for s in data["starts"] if s["status"] != "vorbereitung"]
        for g in data["grants"]:
            g.pop("membership", None)
            g.pop("reign", None)
        return Response(data)
