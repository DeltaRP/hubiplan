from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext
from rest_framework import serializers

from core.api_base import ModelCleanMixin
from members.models import Membership
from organizations.models import Department

from .models import Account, Booking, Category, Project, ProjectSeries, Receipt


class AccountSerializer(ModelCleanMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    balance = serializers.SerializerMethodField()
    planned_balance = serializers.SerializerMethodField()
    booking_count = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "kind",
            "kind_label",
            "iban",
            "bic",
            "bank_name",
            "opening_balance",
            "opening_date",
            "is_active",
            "position",
            "datev_account",
            "balance",
            "planned_balance",
            "booking_count",
        ]

    def get_balance(self, obj) -> str:
        balances = self.context.get("balances") or {}
        value = balances.get(obj.pk)
        if value is None:
            from .services import balance

            value = balance(obj)
        return f"{value:.2f}"

    def get_planned_balance(self, obj) -> str | None:
        """Bestand mit vorgemerkten Buchungen (Datum in der Zukunft); None, wenn gleich."""
        all_dates = self.context.get("balances_all") or {}
        value = all_dates.get(obj.pk)
        if value is None:
            from .services import balance

            value = balance(obj, all_dates=True)
        today = self.get_balance(obj)
        planned = f"{value:.2f}"
        return None if planned == today else planned

    def get_booking_count(self, obj) -> int:
        # In Listen als Annotation (PERF-02), sonst einzeln
        if hasattr(obj, "n_out"):
            return obj.n_out + obj.n_in
        return obj.bookings.count() + obj.incoming_transfers.count()

    def validate_datev_account(self, value):
        return _datev_number(value)

    def validate_iban(self, value):
        return value.replace(" ", "").upper()

    def validate_bic(self, value):
        return value.replace(" ", "").upper()

    def validate_name(self, value):
        org = self.context["org"]
        qs = Account.objects.filter(organization=org, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(gettext("Ein Konto mit diesem Namen gibt es schon."))
        return value

    def validate(self, attrs):
        if self.instance and self.get_booking_count(self.instance):
            # Auch eingehende Umbuchungen zählen (Konto ist dort Ziel)
            first = (
                Booking.objects.filter(organization=self.instance.organization)
                .filter(Q(account=self.instance) | Q(to_account=self.instance))
                .order_by("date")
                .first()
            )
            new_date = attrs.get("opening_date")
            if first and new_date and new_date > first.date:
                raise serializers.ValidationError(
                    {"opening_date": gettext("Es gibt schon Buchungen vor diesem Stichtag.")}
                )
        return super().validate(attrs)


class CategorySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    tax_area_label = serializers.CharField(source="get_tax_area_display", read_only=True)
    booking_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "kind",
            "kind_label",
            "tax_area",
            "donations",
            "datev_account",
            "tax_area_label",
            "is_active",
            "booking_count",
        ]

    def get_booking_count(self, obj) -> int:
        if hasattr(obj, "n_bookings"):
            return obj.n_bookings
        return obj.bookings.count()

    def validate_name(self, value):
        org = self.context["org"]
        qs = Category.objects.filter(organization=org, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                gettext("Eine Kategorie mit diesem Namen gibt es schon.")
            )
        return value

    def validate_datev_account(self, value):
        return _datev_number(value)

    def validate_tax_area(self, value):
        if value and not self.context["org"].tax_areas_enabled:
            return ""
        return value


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = [
            "id",
            "name",
            "content_type",
            "size",
            "created_at",
            "hidden_at",
            "hidden_reason",
            "einvoice",
        ]


class OrgRelatedField(serializers.PrimaryKeyRelatedField):
    """Nur Objekte der eigenen Organisation zulassen."""

    def get_queryset(self):
        return self.queryset.model.objects.filter(organization=self.context["org"])


class BookingSerializer(ModelCleanMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    display_number = serializers.CharField(read_only=True)
    account = OrgRelatedField(queryset=Account.objects.none())
    to_account = OrgRelatedField(queryset=Account.objects.none(), allow_null=True, required=False)
    category = OrgRelatedField(queryset=Category.objects.none(), allow_null=True, required=False)
    membership = OrgRelatedField(
        queryset=Membership.objects.none(), allow_null=True, required=False
    )
    department = OrgRelatedField(
        queryset=Department.objects.none(), allow_null=True, required=False
    )
    project = OrgRelatedField(queryset=Project.objects.none(), allow_null=True, required=False)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    account_name = serializers.CharField(source="account.name", read_only=True)
    to_account_name = serializers.CharField(source="to_account.name", read_only=True, default=None)
    category_name = serializers.CharField(source="category_label", read_only=True, default=None)
    tax_area = serializers.CharField(source="tax_area_value", read_only=True, default="")
    member_name = serializers.SerializerMethodField()
    department_name = serializers.CharField(
        source="department.display_name", read_only=True, default=None
    )
    receipts = ReceiptSerializer(many=True, read_only=True)
    invoice = serializers.SerializerMethodField()
    # Festschreibung und Storno (GoBD)
    fixed = serializers.SerializerMethodField()
    deletable = serializers.SerializerMethodField()
    cancels = serializers.SerializerMethodField()
    cancelled_by = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "year",
            "number",
            "display_number",
            "date",
            "kind",
            "kind_label",
            "amount",
            "account",
            "account_name",
            "to_account",
            "to_account_name",
            "category",
            "category_name",
            "tax_area",
            "text",
            "reference",
            "counterparty",
            "membership",
            "member_name",
            "department",
            "department_name",
            "project",
            "project_name",
            "receipts",
            "invoice",
            "created_at",
            "fixed",
            "deletable",
            "cancels",
            "cancel_reason",
            "cancelled_by",
        ]
        read_only_fields = ["year", "cancel_reason"]
        extra_kwargs = {"number": {"required": False, "min_value": 1}}

    def get_invoice(self, obj) -> dict | None:
        """Zahlungseingang zu einer Rechnung (Beiträge), falls die Buchung daraus stammt."""
        payment = getattr(obj, "payment", None)
        if payment is None:
            return None
        return {"id": payment.invoice_id, "number": payment.invoice.display_number}

    def get_fixed(self, obj) -> bool:
        from . import services

        return bool(services.fixed_reason(obj))

    def get_deletable(self, obj) -> bool:
        from . import services

        return services.deletable(obj)

    def get_cancels(self, obj) -> dict | None:
        if not obj.cancels_id:
            return None
        return {"id": obj.cancels_id, "number": obj.cancels.display_number}

    def get_cancelled_by(self, obj) -> dict | None:
        try:
            counter = obj.cancellation
        except Booking.DoesNotExist:
            return None
        return {
            "id": counter.pk,
            "number": counter.display_number,
            "reason": counter.cancel_reason,
            "date": counter.date,
        }

    def get_member_name(self, obj) -> str | None:
        from billing.units import visible_membership

        # Zahlung im Arbeitsbereich einer Untereinheit: Mitglied liegt darüber
        membership = visible_membership(obj)
        if membership is None:
            return None
        p = membership.person
        return f"{p.last_name}, {p.first_name}"

    def validate_counterparty(self, value):
        return " ".join(value.split())

    def validate(self, attrs):
        org = self.context["org"]
        kind = attrs.get("kind", self.instance.kind if self.instance else None)
        if kind == Booking.Kind.TRANSFER:
            attrs["project"] = None  # Umbuchungen gehören zu keiner Veranstaltung
            attrs["counterparty"] = ""
        if (
            self.instance
            and "date" in attrs
            and org.fiscal_year_of(attrs["date"]) != self.instance.year
        ):
            raise serializers.ValidationError(
                {
                    "date": gettext(
                        "Das Geschäftsjahr einer Buchung lässt sich nicht ändern. Bitte die "
                        "Buchung stornieren und neu anlegen."
                    )
                }
            )
        number = attrs.get("number")
        if number is not None:
            if self.instance is None:
                attrs.pop("number")  # neue Buchungen werden fortlaufend nummeriert
            elif number != self.instance.number:
                taken = Booking.objects.filter(
                    organization=org, year=self.instance.year, number=number
                ).exclude(pk=self.instance.pk)
                if taken.exists():
                    raise serializers.ValidationError(
                        {"number": gettext("Diese Nummer ist im Geschäftsjahr schon vergeben.")}
                    )
        return super().validate(attrs)


class ProjectSeriesSerializer(serializers.ModelSerializer):
    project_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ProjectSeries
        fields = ["id", "name", "project_count"]

    def validate_name(self, value):
        value = value.strip()
        org = self.context["org"]
        qs = ProjectSeries.objects.filter(organization=org, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(gettext("Eine Reihe mit diesem Namen gibt es schon."))
        return value


class ProjectSerializer(ModelCleanMixin, serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    department = OrgRelatedField(
        queryset=Department.objects.none(), allow_null=True, required=False
    )
    department_name = serializers.CharField(
        source="department.display_name", read_only=True, default=None
    )
    series = OrgRelatedField(queryset=ProjectSeries.objects.none(), allow_null=True, required=False)
    series_name = serializers.CharField(source="series.name", read_only=True, default=None)
    income = serializers.SerializerMethodField()
    expense = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    booking_count = serializers.SerializerMethodField()
    event_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "starts_on",
            "ends_on",
            "description",
            "status",
            "status_label",
            "department",
            "department_name",
            "series",
            "series_name",
            "income",
            "expense",
            "result",
            "booking_count",
            "event_count",
        ]

    def _totals(self, obj) -> dict:
        cache = self.context.setdefault("totals", {})
        if obj.pk not in cache:
            from .projects import totals

            cache.update(totals([obj.pk]))
        return cache[obj.pk]

    def get_income(self, obj) -> str:
        return f"{self._totals(obj)['income']:.2f}"

    def get_expense(self, obj) -> str:
        return f"{self._totals(obj)['expense']:.2f}"

    def get_result(self, obj) -> str:
        return f"{self._totals(obj)['result']:.2f}"

    def get_booking_count(self, obj) -> int:
        return self._totals(obj)["booking_count"]

    def validate_name(self, value):
        return value.strip()


def _datev_number(value: str) -> str:
    value = (value or "").strip()
    if value and (not value.isdigit() or len(value) > 9):
        raise serializers.ValidationError(gettext("Bitte nur Ziffern (höchstens 9)."))
    return value
