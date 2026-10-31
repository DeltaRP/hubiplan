"""API der Mitgliederentwicklung für Verein, Dachverband und Abteilung."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from portal.views import DepartmentScopedMixin

from . import statistics
from .federation_views import _FederationMixin
from .views import _ClubMixin


class ClubStatisticsView(_ClubMixin, APIView):
    def get(self, request, org_id: int):
        return Response(
            statistics.statistics(statistics.club_source(self.org), request.query_params)
        )


class FederationStatisticsView(_FederationMixin, APIView):
    def get(self, request, org_id: int):
        src = statistics.federation_source(self.org)
        return Response(statistics.statistics(src, request.query_params))


class DepartmentStatisticsView(DepartmentScopedMixin, APIView):
    def get(self, request, dept_id: int):
        src = statistics.department_source(self.dept)
        return Response(statistics.statistics(src, request.query_params))
