"""API Zählprotokoll und Kassenbericht: /api/orgs/<org_id>/finance/cash-counts/.

Lesen mit finance.view, Anlegen mit finance.edit. Einmal angelegt, nicht änderbar."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.log import record

from . import cash_count
from .bank_views import _drf
from .models import DENOMINATIONS, Booking, CashCount
from .views import BookingPagination, FinanceMixin


class CashCountSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    difference = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    takings = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    bookings = serializers.SerializerMethodField()

    class Meta:
        model = CashCount
        fields = [
            "id",
            "kind",
            "kind_label",
            "account",
            "account_name",
            "date",
            "title",
            "project",
            "denominations",
            "counted",
            "expected",
            "difference",
            "opening",
            "expenses",
            "withdrawals",
            "takings",
            "lines",
            "note",
            "counted_by",
            "witness",
            "bookings",
            "pdf_sha256",
            "created_at",
        ]
        read_only_fields = fields

    def get_bookings(self, obj) -> list[dict]:
        found = Booking.objects.filter(
            organization=obj.organization_id, pk__in=obj.booking_ids or []
        ).select_related("organization")
        return [{"id": b.pk, "number": b.display_number} for b in found]


class CashCountViewSet(
    FinanceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CashCountSerializer
    pagination_class = BookingPagination

    def get_queryset(self):
        return CashCount.objects.filter(organization=self.org).select_related(
            "account", "organization"
        )

    @extend_schema(request=dict, responses=CashCountSerializer)
    def create(self, request, org_id: int):
        try:
            item = cash_count.create(self.org, request.user, request.data)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        label = item.get_kind_display()
        text = (
            f"{item.date:%d.%m.%Y}, gezählt {item.counted} €, Differenz {item.difference} €"
            if item.kind == CashCount.Kind.COUNT
            else f"{item.title} {item.date:%d.%m.%Y}, Tageseinnahme {item.takings} €"
        )
        record(self.org, request.user, "create", item, {label: [None, text]})
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def denominations(self, request, org_id: int):
        return Response(DENOMINATIONS)

    @extend_schema(responses={(200, "*/*"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request, org_id: int, pk: int):
        item = self.get_object()
        with item.pdf.open("rb") as fh:
            content = fh.read()
        response = HttpResponse(content, content_type="application/pdf")
        name = f"{item.get_kind_display()}-{item.date:%Y-%m-%d}.pdf"
        disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response
