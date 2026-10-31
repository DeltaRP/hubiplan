"""API der Zuwendungsbestätigungen: /api/orgs/<org_id>/finance/donation…/

Für Einheiten mit Kasse; ausgestellt wird nur mit Schalter „steuerbegünstigt“ und
gültigem Bescheid. Lesen mit finance.view, Erfassen und Ausstellen mit finance.edit.
Ablauf und Regeln in finance/donations.py.
"""

from __future__ import annotations

import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import record
from core.api_base import AuditMixin
from members.models import Membership

from . import donations as svc
from .models import Donation, DonationSettings, DonationStatement
from .serializers import OrgRelatedField
from .views import BookingPagination, FinanceMixin


def _drf(exc: DjangoValidationError) -> serializers.ValidationError:
    if hasattr(exc, "error_dict"):
        return serializers.ValidationError(exc.message_dict)
    return serializers.ValidationError(" ".join(exc.messages))


class DonationMixin(FinanceMixin):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not svc.available(self.org):
            raise NotFound("Zuwendungsbestätigungen gibt es nicht für die Plattform.")


def _year(request, default: int | None = None) -> int:
    raw = request.data.get("year") if request.method != "GET" else None
    raw = raw or request.query_params.get("jahr") or default or timezone.localdate().year
    try:
        year = int(raw)
    except (TypeError, ValueError):
        raise serializers.ValidationError({"year": "Bitte ein Jahr angeben."}) from None
    if not 1900 <= year <= 2200:
        raise serializers.ValidationError({"year": "Bitte ein gültiges Jahr angeben."})
    return year


# --- Einstellungen ---


class DonationSettingsSerializer(serializers.ModelSerializer):
    notice_label = serializers.CharField(source="get_notice_display", read_only=True)

    class Meta:
        model = DonationSettings
        fields = [
            "enabled",
            "purposes",
            "notice",
            "notice_label",
            "tax_office",
            "tax_number",
            "notice_date",
            "assessment_period",
            "fees_allowed",
            "place",
        ]


class DonationSettingsView(DonationMixin, APIView):
    def _data(self, cfg):
        data = DonationSettingsSerializer(cfg).data
        until = svc.notice_valid_until(cfg)
        data["valid_until"] = until.isoformat() if until else None
        data["problems"] = svc.problems(cfg)
        return data

    def get(self, request, org_id: int):
        return Response(self._data(svc.settings_for(self.org)))

    @transaction.atomic
    def put(self, request, org_id: int):
        cfg = svc.settings_for(self.org)
        created = cfg.pk is None
        ser = DonationSettingsSerializer(cfg, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        cfg = ser.save(organization=self.org)
        record(
            self.org,
            request.user,
            "create" if created else "update",
            cfg,
            {"Zuwendungsbestätigungen": [None, "Einstellungen gespeichert"]},
        )
        return Response(self._data(cfg))


# --- Zuwendungen ---


class DonationChecksSerializer(serializers.Serializer):
    open = serializers.IntegerField()
    without_address = serializers.IntegerField()
    goods_without_documents = serializers.IntegerField()
    goods_open = serializers.IntegerField()
    fees_skipped = serializers.IntegerField()


class DonationSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    membership = OrgRelatedField(
        queryset=Membership.objects.none(), allow_null=True, required=False
    )
    statement_number = serializers.SerializerMethodField()
    booking_number = serializers.CharField(
        source="booking.display_number", read_only=True, default=None
    )
    donor_address = serializers.CharField(required=False, allow_blank=True, max_length=500)

    class Meta:
        model = Donation
        fields = [
            "id",
            "date",
            "kind",
            "kind_label",
            "amount",
            "waiver",
            "membership",
            "donor_name",
            "donor_address",
            "goods_description",
            "goods_origin",
            "goods_documents",
            "note",
            "booking",
            "booking_number",
            "statement",
            "statement_number",
            "created_at",
        ]
        read_only_fields = ["booking", "statement", "created_at"]
        extra_kwargs = {"donor_name": {"required": False, "allow_blank": True}}

    def get_statement_number(self, obj) -> str | None:
        return obj.statement.number if obj.statement_id else None

    def validate(self, attrs):
        org = self.context["org"]
        # Auf einer Kopie prüfen: Die echte Zeile darf sich vor dem Speichern nicht ändern,
        # sonst fehlt der Vorher-Stand im Änderungsprotokoll (Audit 31.10. FIN31-05)
        inst = copy.copy(self.instance) if self.instance else Donation(organization=org)
        for key, value in attrs.items():
            setattr(inst, key, value)
        # Name und Anschrift aus dem Mitglied, wenn nichts angegeben ist
        if inst.membership_id and not inst.donor_name.strip():
            name, address = svc.donor_from_membership(org, inst.membership)
            attrs["donor_name"] = inst.donor_name = name
            if not inst.donor_address.strip():
                attrs["donor_address"] = inst.donor_address = address
        try:
            svc.check_donation(org, inst)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return attrs


class DonationViewSet(DonationMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = DonationSerializer
    pagination_class = BookingPagination

    def get_queryset(self):
        qs = Donation.objects.filter(organization=self.org).select_related(
            "statement", "booking__organization"
        )
        params = self.request.query_params
        if (year := params.get("jahr", "")).isdigit():
            qs = qs.filter(date__year=int(year))
        if params.get("offen") == "1":
            qs = qs.filter(statement__isnull=True)
        if term := params.get("suche", "").strip():
            qs = qs.filter(donor_name__icontains=term)
        return qs.order_by("-date", "-pk")

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org, "created_by": self.request.user}

    @staticmethod
    def _locked_editable(instance) -> Donation:
        """Zeile sperren, frisch lesen und erst dann prüfen (Audit 31.10. FIN31-R01):
        Eine gleichzeitig ausgestellte Bestätigung wird so sicher erkannt."""
        fresh = Donation.objects.select_for_update().get(pk=instance.pk)
        try:
            svc.ensure_editable(fresh)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return fresh

    @transaction.atomic
    def perform_update(self, serializer):
        self._locked_editable(serializer.instance)
        super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        self._locked_editable(instance)
        instance.refresh_from_db()
        super().perform_destroy(instance)

    @action(detail=False, methods=["post"], url_path="import")
    def import_bookings(self, request, org_id: int):
        """Einnahmen aus Kategorien mit Kennzeichen „Spenden“ übernehmen."""
        year = _year(request)
        created = svc.import_bookings(self.org, year, request.user)
        if created:
            record(
                self.org,
                request.user,
                "create",
                created[0],
                {"Zuwendungen": [None, f"{len(created)} aus dem Kassenbuch {year} übernommen"]},
            )
        return Response({"created": len(created)})

    @action(detail=False, methods=["get"], url_path="years")
    def years(self, request, org_id: int):
        """Alle Jahre mit Zuwendungen, neueste zuerst (UX-Audit 31.10. N01)."""
        found = Donation.objects.filter(organization=self.org).dates("date", "year", order="DESC")
        return Response([d.year for d in found])

    @extend_schema(responses=DonationChecksSerializer)
    @action(detail=False, methods=["get"], url_path="checks")
    def checks(self, request, org_id: int):
        """Zahlen für die Prüfliste vor den Jahresbestätigungen (blockiert nie)."""
        return Response(svc.year_checks(self.org, _year(request)))

    @action(detail=False, methods=["get"], url_path="year-end")
    def year_end(self, request, org_id: int):
        """Vorschau Jahresende: offene Geldzuwendungen je Zuwendendem."""
        year = _year(request)
        groups = svc.year_end_groups(self.org, year)
        cfg = svc.settings_for(self.org)
        rows = []
        for group in groups:
            items = group if cfg.fees_allowed else [d for d in group if d.kind != Donation.Kind.FEE]
            if not items:
                continue
            rows.append(
                {
                    "donor_name": items[0].donor_name,
                    "count": len(items),
                    "total": str(sum(d.amount for d in items)),
                    "ids": [d.pk for d in items],
                    "incomplete": next((r for d in items if (r := svc.incomplete(d))), ""),
                }
            )
        return Response({"year": year, "donors": rows, "problems": svc.problems(cfg)})


# --- Bestätigungen ---


class DonationStatementSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    issued_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DonationStatement
        fields = [
            "id",
            "number",
            "year",
            "kind",
            "kind_label",
            "goods",
            "membership",
            "donor_name",
            "donor_address",
            "total",
            "period_from",
            "period_to",
            "items",
            "issued_on",
            "issued_by_name",
            "signer_name",
            "cancelled_at",
            "cancel_reason",
        ]
        read_only_fields = fields

    def get_issued_by_name(self, obj) -> str:
        user = obj.issued_by
        return (user.get_full_name() or user.email) if user else ""


class IssueSerializer(serializers.Serializer):
    donations = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    signer_name = serializers.CharField(required=False, allow_blank=True, max_length=200)


class DonationStatementViewSet(
    DonationMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = DonationStatementSerializer
    pagination_class = BookingPagination

    def get_queryset(self):
        qs = DonationStatement.objects.filter(organization=self.org).select_related("issued_by")
        params = self.request.query_params
        if (year := params.get("jahr", "")).isdigit():
            qs = qs.filter(year=int(year))
        if term := params.get("suche", "").strip():
            qs = qs.filter(donor_name__icontains=term)
        return qs.order_by("-year", "-seq")

    @action(detail=False, methods=["get"], url_path="years")
    def years(self, request, org_id: int):
        """Alle Jahre mit gespeicherten Bestätigungen, neueste zuerst (UX-Audit 31.10. N01)."""
        found = (
            DonationStatement.objects.filter(organization=self.org)
            .order_by("-year")
            .values_list("year", flat=True)
            .distinct()
        )
        return Response(list(found))

    def _record(self, statement, text):
        record(
            self.org,
            self.request.user,
            "create",
            statement,
            {"Zuwendungsbestätigung": [None, text]},
        )

    def create(self, request, org_id: int):
        ser = IssueSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        donations = list(
            Donation.objects.filter(organization=self.org, pk__in=ser.validated_data["donations"])
        )
        if len(donations) != len(set(ser.validated_data["donations"])):
            raise serializers.ValidationError({"donations": "Unbekannte Zuwendung."})
        try:
            with transaction.atomic():
                statement = svc.issue(
                    self.org,
                    donations,
                    request.user,
                    signer_name=ser.validated_data.get("signer_name", ""),
                )
                self._record(
                    statement, f"{statement.number} für {statement.donor_name} ausgestellt"
                )
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return Response(self.get_serializer(statement).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="year-end")
    def year_end(self, request, org_id: int):
        """Sammelbestätigungen für alle offenen Geldzuwendungen eines Jahres."""
        year = _year(request)
        signer = str(request.data.get("signer_name", ""))[:200]
        try:
            with transaction.atomic():
                made = svc.issue_year_end(self.org, year, request.user, signer_name=signer)
                if made:
                    self._record(made[0], f"{len(made)} Bestätigungen für {year} ausgestellt")
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return Response({"created": len(made), "items": self.get_serializer(made, many=True).data})

    @action(detail=True, methods=["post"])
    def cancel(self, request, org_id: int, pk: int):
        statement = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            with transaction.atomic():
                statement = svc.cancel(statement, request.user, str(request.data.get("reason", "")))
                record(
                    self.org,
                    request.user,
                    "update",
                    statement,
                    {
                        "Zuwendungsbestätigung": [
                            statement.number,
                            f"storniert: {statement.cancel_reason}",
                        ]
                    },
                )
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return Response(self.get_serializer(statement).data)

    @action(detail=True, methods=["get"])
    def pdf(self, request, org_id: int, pk: int):
        """Das gespeicherte Doppel, genau wie ausgestellt."""
        statement = get_object_or_404(self.get_queryset(), pk=pk)
        if not statement.file:
            raise NotFound()
        with statement.file.open("rb") as fh:
            content = fh.read()
        from .donation_pdf import filename

        response = HttpResponse(content, content_type="application/pdf")
        name = filename(statement)
        if statement.cancelled_at:
            name = name.replace(".pdf", "-storniert.pdf")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response
