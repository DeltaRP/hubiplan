"""API Rücklagen: /api/orgs/<org_id>/finance/reserves/ (Finanzamt-Prüfung C4).

Lesen mit finance.view, Ändern mit finance.edit; nur bei eingeschalteten Rücklagen."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from audit.log import record
from core.api_base import AuditMixin

from . import reserves
from .bank_views import _drf
from .models import Reserve, ReserveMovement
from .views import FinanceMixin


class ReserveMovementSerializer(serializers.ModelSerializer):
    direction_label = serializers.CharField(source="get_direction_display", read_only=True)
    year_label = serializers.SerializerMethodField()
    open = serializers.SerializerMethodField()

    class Meta:
        model = ReserveMovement
        fields = [
            "id",
            "direction",
            "direction_label",
            "date",
            "year",
            "year_label",
            "amount",
            "note",
            "created_by_name",
            "created_at",
            "open",
        ]
        read_only_fields = fields

    def get_year_label(self, obj) -> str:
        return obj.organization.fiscal_label(obj.year)

    def get_open(self, obj) -> bool:
        """Geschäftsjahr noch offen: Bewegung lässt sich löschen."""
        return obj.year not in self.context.get("closed_years", set())


class ReserveSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    balance = serializers.SerializerMethodField()
    movements = serializers.SerializerMethodField()

    class Meta:
        model = Reserve
        fields = [
            "id",
            "name",
            "kind",
            "kind_label",
            "purpose",
            "is_active",
            "balance",
            "movements",
        ]
        read_only_fields = ["id", "kind_label", "balance", "movements"]

    def get_balance(self, obj) -> str:
        known = self.context.get("balances")
        value = known[obj.pk] if known is not None and obj.pk in known else reserves.balance(obj)
        return f"{value:.2f}"

    def get_movements(self, obj) -> list[dict]:
        cache = getattr(obj, "_prefetched_objects_cache", {})
        if "movements" in cache:
            qs = sorted(cache["movements"], key=lambda m: (m.date, m.pk), reverse=True)
        else:
            qs = obj.movements.select_related("organization").order_by("-date", "-pk")
        return ReserveMovementSerializer(qs, many=True, context=self.context).data

    def validate(self, attrs):
        data = {
            "kind": attrs.get("kind", getattr(self.instance, "kind", None)),
            "purpose": attrs.get("purpose", getattr(self.instance, "purpose", "")),
        }
        try:
            reserves.validate_reserve(data)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return attrs


class ReserveViewSet(FinanceMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = ReserveSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.org.reserves_enabled:
            raise NotFound(gettext("Rücklagen sind für diese Einheit nicht eingeschaltet."))

    def get_queryset(self):
        return Reserve.objects.filter(organization=self.org)

    def get_serializer_context(self):
        from .models import YearClosing

        ctx = super().get_serializer_context()
        ctx["closed_years"] = set(
            YearClosing.objects.filter(organization=self.org).values_list("year", flat=True)
        )
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    def list(self, request, *args, **kwargs):
        from django.db.models import Prefetch

        data = reserves.overview(self.org)
        queryset = self.get_queryset().prefetch_related(
            Prefetch("movements", queryset=ReserveMovement.objects.select_related("organization"))
        )
        context = {**self.get_serializer_context(), "balances": data["balances"]}
        items = ReserveSerializer(queryset, many=True, context=context).data
        return Response(
            {
                "reserves": items,
                "total": f"{data['total']:.2f}",
                "funds": f"{data['funds']:.2f}",
                "free": f"{data['free']:.2f}",
            }
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        if instance.movements.exists():
            raise serializers.ValidationError(
                gettext("Die Rücklage hat Bewegungen; bitte stattdessen archivieren.")
            )
        super().perform_destroy(instance)

    @extend_schema(request=dict, responses=ReserveMovementSerializer)
    @action(detail=True, methods=["post"])
    def movements(self, request, org_id: int, pk: int):
        reserve = self.get_object()
        with transaction.atomic():
            try:
                movement = reserves.add_movement(self.org, reserve, request.data, request.user)
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
            record(
                self.org,
                request.user,
                "create",
                movement,
                {
                    movement.get_direction_display(): [
                        None,
                        f"{reserve.name}: {movement.amount} € am {movement.date:%d.%m.%Y}",
                    ]
                },
            )
        return Response(
            ReserveMovementSerializer(movement, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"movements/(?P<movement_id>\d+)",
        url_name="movement",
    )
    def delete_movement(self, request, org_id: int, pk: int, movement_id: str):
        reserve = self.get_object()
        movement = reserve.movements.filter(pk=int(movement_id)).first()
        if movement is None:
            raise NotFound()
        with transaction.atomic():
            record(
                self.org,
                request.user,
                "delete",
                movement,
                {
                    movement.get_direction_display(): [
                        f"{reserve.name}: {movement.amount} € am {movement.date:%d.%m.%Y}",
                        None,
                    ]
                },
            )
            try:
                reserves.delete_movement(self.org, movement)
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)
