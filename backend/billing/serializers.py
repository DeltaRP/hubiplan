from __future__ import annotations

from django.utils.translation import gettext
from rest_framework import serializers

from core.api_base import ModelCleanMixin
from finance.models import Account, Category
from members.models import MemberType

from .models import (
    AgeRate,
    BillingSettings,
    DebitItem,
    DebitRun,
    Dunning,
    DunningLevel,
    FeeRun,
    Invoice,
    InvoiceLine,
    Mandate,
    Payment,
)


class BillingSettingsSerializer(ModelCleanMixin, serializers.ModelSerializer):
    account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.all(), allow_null=True, required=False
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = BillingSettings
        fields = [
            "rhythm",
            "due_days",
            "pro_rata",
            "account",
            "category",
            "intro_text",
            "footer_text",
            "qr_code",
            "vat_enabled",
            "vat_rate",
            "tax_number",
            "club_rate_active",
            "club_rate_passive",
            "club_base_amount",
            "sepa_enabled",
            "creditor_id",
            "prenotification_days",
        ]

    def validate_creditor_id(self, value):
        from .sepa import creditor_id_valid

        value = value.replace(" ", "").upper()
        if value and not creditor_id_valid(value):
            raise serializers.ValidationError(
                gettext("Die Gläubiger-Identifikationsnummer ist ungültig.")
            )
        return value

    def validate_sepa_enabled(self, value):
        org = self.context.get("org")
        if value and org is not None and org.type == "unit":
            raise serializers.ValidationError(gettext("Lastschrift gibt es hier nicht."))
        return value

    def validate_prenotification_days(self, value):
        if not 1 <= value <= 30:
            raise serializers.ValidationError(gettext("Zwischen 1 und 30 Tagen."))
        return value

    def _own(self, obj, label):
        if obj is not None and obj.organization_id != self.context["org"].pk:
            raise serializers.ValidationError(gettext("Unbekannte {label}.").format(label=label))
        return obj

    def validate_account(self, value):
        return self._own(value, "Konto")

    def validate_category(self, value):
        value = self._own(value, "Kategorie")
        if value is not None and not value.allows("income"):
            raise serializers.ValidationError(gettext("Die Kategorie gilt nicht für Einnahmen."))
        return value

    def validate_due_days(self, value):
        if value > 365:
            raise serializers.ValidationError(gettext("Höchstens 365 Tage."))
        return value

    def _not_negative(self, value):
        # Nachlässe und Gutschriften gehören als eigener Posten in die Rechnung
        if value is not None and value < 0:
            raise serializers.ValidationError(gettext("Der Betrag darf nicht negativ sein."))
        return value

    validate_club_rate_active = _not_negative
    validate_club_rate_passive = _not_negative
    validate_club_base_amount = _not_negative

    def validate_vat_rate(self, value):
        if value is not None and not (0 <= value <= 100):
            raise serializers.ValidationError(
                gettext("Der Steuersatz liegt zwischen 0 und 100 Prozent.")
            )
        return value


class AgeRateSerializer(ModelCleanMixin, serializers.ModelSerializer):
    member_type = serializers.PrimaryKeyRelatedField(
        queryset=MemberType.objects.all(), allow_null=True, required=False
    )
    member_type_name = serializers.CharField(
        source="member_type.name", read_only=True, default=None
    )

    class Meta:
        model = AgeRate
        fields = [
            "id",
            "name",
            "member_type",
            "member_type_name",
            "min_age",
            "max_age",
            "amount",
            "discount_percent",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        get = lambda key: attrs.get(key, getattr(self.instance, key, None))  # noqa: E731
        low, high = get("min_age"), get("max_age")
        low = 0 if low is None else low
        high = 10_000 if high is None else high
        others = AgeRate.objects.filter(
            organization=self.context["org"], member_type=get("member_type")
        )
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        for other in others:
            o_low = 0 if other.min_age is None else other.min_age
            o_high = 10_000 if other.max_age is None else other.max_age
            if low <= o_high and o_low <= high:
                # Sonst entschiede eine unsichtbare Reihenfolge, welche Stufe gilt
                raise serializers.ValidationError(
                    {
                        "min_age": gettext(
                            "Die Altersgrenzen überschneiden sich mit „{name}“."
                        ).format(name=other.name)
                    }
                )
        return attrs

    def validate_member_type(self, value):
        if value is not None and value.organization_id != self.context["org"].pk:
            raise serializers.ValidationError(gettext("Unbekannte Mitgliedsart."))
        if value is not None and value.is_archived:
            changed = self.instance is None or self.instance.member_type_id != value.pk
            if changed:
                raise serializers.ValidationError(gettext("Diese Art wird nicht mehr verwendet."))
        return value


class FeeRunSerializer(serializers.ModelSerializer):
    rhythm_label = serializers.CharField(source="get_rhythm_display", read_only=True)

    class Meta:
        model = FeeRun
        fields = [
            "id",
            "year",
            "rhythm",
            "rhythm_label",
            "period",
            "start_date",
            "end_date",
            "label",
            "invoice_date",
            "due_date",
            "created_at",
            "post_done_at",
        ]
        read_only_fields = fields


class RunCreateSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    period = serializers.IntegerField(min_value=1, max_value=12, default=1)
    invoice_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)


class LineSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "text",
            "detail",
            "amount",
            "vat_rate",
            "membership",
            "member_name",
            "is_fee",
            "is_dunning_fee",
        ]
        read_only_fields = ["id", "membership", "member_name", "is_fee", "is_dunning_fee"]

    def get_member_name(self, obj) -> str | None:
        from .units import visible_membership

        membership = visible_membership(obj)
        if membership is None:
            return None
        p = membership.person
        return f"{p.last_name}, {p.first_name}"


class PaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    account_name = serializers.CharField(source="booking.account.name", read_only=True)
    booking_number = serializers.CharField(source="booking.display_number", read_only=True)
    booking_id = serializers.IntegerField(source="booking.pk", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "date",
            "amount",
            "method",
            "method_label",
            "account_name",
            "booking_id",
            "booking_number",
        ]


class PaymentCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.all())


class InvoiceListSerializer(serializers.ModelSerializer):
    number = serializers.CharField(source="display_number", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    outstanding = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    department_name = serializers.CharField(
        source="department.display_name", read_only=True, default=None
    )
    club_name = serializers.CharField(source="club.display_name", read_only=True, default=None)
    issuer_name = serializers.CharField(source="organization.display_name", read_only=True)
    run_label = serializers.CharField(source="run.label", read_only=True, default=None)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "status",
            "status_label",
            "recipient_kind",
            "recipient_name",
            "recipient_email",
            "membership",
            "department",
            "department_name",
            "club",
            "club_name",
            "issuer_name",
            "run",
            "run_label",
            "project",
            "project_name",
            "date",
            "due_date",
            "subject",
            "total",
            "paid",
            "outstanding",
            "sent_at",
            "overdue",
            "dunning_level",
            "dunned_at",
        ]

    def get_overdue(self, obj) -> bool:
        from django.utils import timezone

        return obj.status == Invoice.Status.OPEN and obj.due_date < timezone.localdate()


class DunningLevelSerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = DunningLevel
        fields = ["id", "level", "name", "days", "fee", "text"]


class DunningSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dunning
        fields = ["id", "level", "name", "date", "due_date", "fee", "sent_at"]
        read_only_fields = fields


class InvoiceDetailSerializer(InvoiceListSerializer):
    lines = LineSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    dunnings = DunningSerializer(many=True, read_only=True)
    vat = serializers.SerializerMethodField()

    def get_vat(self, obj) -> list[dict]:
        from .services import vat_breakdown

        return [
            {k: (f"{v:.2f}" if k != "rate" else f"{v.normalize():f}") for k, v in row.items()}
            for row in vat_breakdown(obj)
        ]

    class Meta(InvoiceListSerializer.Meta):
        fields = [
            *InvoiceListSerializer.Meta.fields,
            "recipient_address",
            "note",
            "cancelled_at",
            "lines",
            "payments",
            "dunnings",
            "vat",
        ]


class LineInputSerializer(serializers.Serializer):
    # Bisheriger Posten (behält seine Herkunft, z. B. Beitrag eines Mitglieds)
    id = serializers.IntegerField(required=False, allow_null=True)
    text = serializers.CharField(max_length=200)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    vat_rate = serializers.DecimalField(
        max_digits=4, decimal_places=2, min_value=0, max_value=99, required=False, allow_null=True
    )


class InvoiceInputSerializer(serializers.Serializer):
    recipient_kind = serializers.ChoiceField(
        choices=[*Invoice.Recipient.choices, ("unit", "Untereinheit")], required=False
    )
    unit = serializers.IntegerField(required=False, allow_null=True)
    membership = serializers.IntegerField(required=False, allow_null=True)
    department = serializers.IntegerField(required=False, allow_null=True)
    club = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False)
    subject = serializers.CharField(max_length=200, required=False)
    note = serializers.CharField(required=False, allow_blank=True)
    project = serializers.IntegerField(required=False, allow_null=True)
    lines = LineInputSerializer(many=True, required=False)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(gettext("Bitte mindestens einen Posten angeben."))
        return value


class MandateSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    payer_name = serializers.SerializerMethodField()
    iban_masked = serializers.SerializerMethodField()
    expired = serializers.SerializerMethodField()

    class Meta:
        model = Mandate
        fields = [
            "id",
            "reference",
            "membership",
            "club",
            "payer_name",
            "holder",
            "iban",
            "iban_masked",
            "bic",
            "signed_on",
            "source",
            "source_label",
            "status",
            "status_label",
            "revoked_on",
            "last_used_on",
            "expired",
            "created_at",
        ]
        read_only_fields = fields

    def get_payer_name(self, obj) -> str:
        if obj.membership_id:
            p = obj.membership.person
            return f"{p.last_name}, {p.first_name}"
        return obj.club.display_name if obj.club_id else ""

    def get_iban_masked(self, obj) -> str:
        from .sepa import masked_iban

        return masked_iban(obj.iban)

    def get_expired(self, obj) -> bool:
        from .sepa import mandate_expired

        return obj.status == Mandate.Status.ACTIVE and mandate_expired(obj)


class MandateInputSerializer(serializers.Serializer):
    membership = serializers.IntegerField(required=False, allow_null=True)
    club = serializers.IntegerField(required=False, allow_null=True)
    holder = serializers.CharField(max_length=70)
    iban = serializers.CharField(max_length=42)
    bic = serializers.CharField(max_length=14, required=False, allow_blank=True, default="")
    signed_on = serializers.DateField()


class DebitItemSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.display_number", read_only=True)
    payer = serializers.CharField(source="mandate.holder", read_only=True)
    recipient_name = serializers.CharField(source="invoice.recipient_name", read_only=True)
    recipient_email = serializers.CharField(source="invoice.recipient_email", read_only=True)
    mandate_reference = serializers.CharField(source="mandate.reference", read_only=True)

    class Meta:
        model = DebitItem
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "recipient_name",
            "recipient_email",
            "payer",
            "mandate_reference",
            "amount",
            "sequence",
            "prenotified_at",
            "payment",
        ]
        read_only_fields = fields


class DebitRunSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    items = DebitItemSerializer(many=True, read_only=True)
    problems = serializers.SerializerMethodField()

    class Meta:
        model = DebitRun
        fields = [
            "id",
            "collection_date",
            "account",
            "account_name",
            "status",
            "status_label",
            "total",
            "created_at",
            "booked_at",
            "items",
            "problems",
        ]
        read_only_fields = fields

    def get_problems(self, run) -> list[str]:
        from .sepa import run_problems

        return run_problems(run)
