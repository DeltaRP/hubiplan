"""Jubiläumsliste eines Vereins (Meilenstein 4)."""

from __future__ import annotations

import datetime

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api_base import OrgScopedMixin
from organizations.jubilees import unit_jubilees
from organizations.models import Organization

from .birthdays import birthdays_between
from .duration import jubilees_between
from .models import today
from .views import _ClubMixin


class JubileeView(_ClubMixin, APIView):
    """Wer hat im gewählten Zeitraum ein Jubiläum (Verein und Dachverband)?"""

    @extend_schema(parameters=[OpenApiParameter("von", str), OpenApiParameter("bis", str)])
    def get(self, request, org_id: int):
        field = serializers.DateField()
        start = today()
        end = start + datetime.timedelta(days=365)
        try:
            if request.query_params.get("von"):
                start = field.to_internal_value(request.query_params["von"])
            if request.query_params.get("bis"):
                end = field.to_internal_value(request.query_params["bis"])
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"von": "Bitte gültige Daten angeben."}) from exc
        if end < start:
            raise serializers.ValidationError({"bis": "Das Ende liegt vor dem Beginn."})
        if (end - start).days > 3 * 366:
            raise serializers.ValidationError({"bis": "Höchstens drei Jahre auf einmal."})
        rows = jubilees_between(self.org, start, end)
        return Response({"von": start, "bis": end, "results": rows})


class UnitJubileeView(OrgScopedMixin, APIView):
    """Jubiläen von Einheiten im Zeitraum (aus dem Gründungsjahr, jahresgenau)."""

    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)

    @extend_schema(parameters=[OpenApiParameter("von", str), OpenApiParameter("bis", str)])
    def get(self, request, org_id: int):
        field = serializers.DateField()
        start = today()
        end = start + datetime.timedelta(days=365)
        try:
            if request.query_params.get("von"):
                start = field.to_internal_value(request.query_params["von"])
            if request.query_params.get("bis"):
                end = field.to_internal_value(request.query_params["bis"])
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"von": "Bitte gültige Daten angeben."}) from exc
        if end < start:
            raise serializers.ValidationError({"bis": "Das Ende liegt vor dem Beginn."})
        return Response({"von": start, "bis": end, "results": unit_jubilees(self.org, start, end)})


class BirthdayView(_ClubMixin, APIView):
    """Wer hat im gewählten Zeitraum Geburtstag (aktuelle Mitglieder)?"""

    @extend_schema(parameters=[OpenApiParameter("von", str), OpenApiParameter("bis", str)])
    def get(self, request, org_id: int):
        field = serializers.DateField()
        start = today()
        end = start + datetime.timedelta(days=30)
        try:
            if request.query_params.get("von"):
                start = field.to_internal_value(request.query_params["von"])
            if request.query_params.get("bis"):
                end = field.to_internal_value(request.query_params["bis"])
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"von": "Bitte gültige Daten angeben."}) from exc
        if end < start:
            raise serializers.ValidationError({"bis": "Das Ende liegt vor dem Beginn."})
        if (end - start).days > 366:
            raise serializers.ValidationError({"bis": "Höchstens ein Jahr auf einmal."})
        return Response(
            {"von": start, "bis": end, "results": birthdays_between(self.org, start, end)}
        )
