"""API Kontoauszüge: /api/orgs/<org_id>/finance/bank-statements/ und …/bank-lines/.

Lesen mit finance.view, Einlesen und Zuordnen mit finance.edit. Ablauf in
finance/bank_import.py.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from audit.log import record
from core.files import delete_on_commit
from members.models import Membership

from . import bank_import, camt
from .models import Account, BankLine, BankStatement, Booking, Category, Project
from .views import BookingPagination, FinanceMixin


def _drf(exc: DjangoValidationError) -> serializers.ValidationError:
    if hasattr(exc, "error_dict"):
        return serializers.ValidationError(exc.message_dict)
    return serializers.ValidationError(" ".join(exc.messages))


class BankStatementSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)
    open_count = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = BankStatement
        fields = [
            "id",
            "account",
            "account_name",
            "file_name",
            "reference",
            "date_from",
            "date_to",
            "opening_balance",
            "closing_balance",
            "line_count",
            "duplicate_count",
            "open_count",
            "balance",
            "created_at",
        ]
        read_only_fields = fields

    def get_open_count(self, obj) -> int:
        return obj.lines.filter(status=BankLine.Status.OPEN).count()

    def get_balance(self, obj) -> dict | None:
        return bank_import.balance_check(obj)


class BankLineSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    suggestion_label = serializers.CharField(source="get_suggestion_display", read_only=True)
    suggested = serializers.SerializerMethodField()
    booking_number = serializers.CharField(
        source="booking.display_number", read_only=True, default=None
    )

    class Meta:
        model = BankLine
        fields = [
            "id",
            "statement",
            "account",
            "date",
            "value_date",
            "amount",
            "credit",
            "name",
            "iban",
            "purpose",
            "end_to_end",
            "return_code",
            "batch_count",
            "details",
            "status",
            "status_label",
            "suggestion",
            "suggestion_label",
            "suggestion_sure",
            "suggested",
            "booking",
            "booking_number",
        ]
        read_only_fields = fields

    def get_suggested(self, obj) -> dict:
        data: dict = {}
        if obj.suggested_invoice_id:
            inv = obj.suggested_invoice
            data["invoice"] = {
                "id": inv.pk,
                "number": inv.display_number,
                "recipient": (inv.recipient_name or "").splitlines()[0]
                if inv.recipient_name
                else "",
                "outstanding": str(inv.outstanding),
            }
        if obj.suggested_run_id:
            run = obj.suggested_run
            data["run"] = {"id": run.pk, "date": run.collection_date, "total": str(run.total)}
        if obj.suggested_booking_id:
            b = obj.suggested_booking
            data["booking"] = {"id": b.pk, "number": b.display_number, "text": b.text}
        if obj.suggested_membership_id:
            p = obj.suggested_membership.person
            data["membership"] = {
                "id": obj.suggested_membership_id,
                "name": f"{p.first_name} {p.last_name}",
            }
        return data


class BankStatementViewSet(
    FinanceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = BankStatementSerializer
    pagination_class = BookingPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = BankStatement.objects.filter(organization=self.org).select_related("account")
        if (acc := self.request.query_params.get("konto", "")).isdigit():
            qs = qs.filter(account_id=int(acc))
        return qs.order_by("-created_at", "-pk")

    def create(self, request, org_id: int):
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": gettext("Bitte die CAMT-Datei wählen.")})
        if upload.size > camt.MAX_FILE:
            raise serializers.ValidationError({"file": gettext("Die Datei ist größer als 10 MB.")})
        account = None
        if raw := request.data.get("account"):
            account = Account.objects.filter(organization=self.org, pk=raw).first()
            if account is None:
                raise serializers.ValidationError({"account": gettext("Unbekanntes Konto.")})
        try:
            result = bank_import.import_file(
                self.org, upload.read(), upload.name or "kontoauszug.xml", request.user, account
            )
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        for st in result["statements"]:
            record(
                self.org,
                request.user,
                "create",
                st,
                {"Kontoauszug": [None, f"{st.file_name}: {st.line_count} Umsätze eingelesen"]},
            )
        return Response(
            {
                "lines": result["lines"],
                "duplicates": result["duplicates"],
                "statements": self.get_serializer(result["statements"], many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        # Zeilen sperren, damit keine parallele Zuordnung zwischen Prüfung und Löschen landet
        list(instance.lines.select_for_update().values_list("pk", flat=True))
        if instance.lines.filter(status=BankLine.Status.DONE).exists():
            raise serializers.ValidationError(
                gettext(
                    "Aus diesem Auszug ist schon etwas gebucht oder zugeordnet. Er bleibt erhalten."
                )
            )
        record(
            self.org,
            self.request.user,
            "delete",
            instance,
            {"Kontoauszug": [instance.file_name, None]},
        )
        if instance.source:
            delete_on_commit(instance.source)
        instance.delete()


class AssignSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["invoice", "run", "booking", "link", "ignore", "reopen", "suggestion"]
    )
    invoice = serializers.IntegerField(required=False)
    run = serializers.IntegerField(required=False)
    link = serializers.IntegerField(required=False)
    category = serializers.IntegerField(required=False)
    membership = serializers.IntegerField(required=False, allow_null=True)
    project = serializers.IntegerField(required=False, allow_null=True)
    text = serializers.CharField(required=False, allow_blank=True, max_length=200)


class BankLineViewSet(FinanceMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = BankLineSerializer
    pagination_class = BookingPagination

    def get_queryset(self):
        qs = BankLine.objects.filter(organization=self.org).select_related(
            "suggested_invoice__organization",
            "suggested_run",
            "suggested_booking__organization",
            "suggested_membership__person",
            "booking__organization",
        )
        params = self.request.query_params
        if (st := params.get("auszug", "")).isdigit():
            qs = qs.filter(statement_id=int(st))
        if (state := params.get("status")) in BankLine.Status.values:
            qs = qs.filter(status=state)
        if term := params.get("suche", "").strip():
            qs = qs.filter(name__icontains=term) | qs.filter(purpose__icontains=term)
        return qs.order_by("date", "pk")

    def _get(self, model, pk, field):
        obj = model.objects.filter(organization=self.org, pk=pk).first() if pk else None
        if obj is None:
            raise serializers.ValidationError({field: gettext("Bitte auswählen.")})
        return obj

    @action(detail=True, methods=["post"])
    def assign(self, request, org_id: int, pk: int):
        from billing.models import DebitRun, Invoice

        line = get_object_or_404(self.get_queryset(), pk=pk)
        ser = AssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        what = d["action"]
        if what == "suggestion":
            what = {
                BankLine.Suggestion.INVOICE: "invoice",
                BankLine.Suggestion.DEBIT_RUN: "run",
                BankLine.Suggestion.BOOKED: "link",
            }.get(line.suggestion)
            if what is None:
                raise serializers.ValidationError(
                    gettext("Für diesen Umsatz gibt es keinen Vorschlag.")
                )
            d = {
                "invoice": line.suggested_invoice_id,
                "run": line.suggested_run_id,
                "link": line.suggested_booking_id,
            }
        try:
            if what == "invoice":
                inv = self._get(Invoice, d.get("invoice"), "invoice")
                line = bank_import.pay_invoice(line, inv, request.user)
                text = f"Zahlung zu {inv.display_number}"
            elif what == "run":
                run = self._get(DebitRun, d.get("run"), "run")
                line = bank_import.book_debit_run(line, run, request.user)
                text = f"Lastschriftlauf vom {run.collection_date:%d.%m.%Y} gebucht"
            elif what == "link":
                booking = self._get(Booking, d.get("link"), "link")
                line = bank_import.link_booking(line, booking, request.user)
                text = f"Buchung {booking.display_number} zugeordnet"
            elif what == "booking":
                category = self._get(Category, d.get("category"), "category")
                membership = (
                    self._get(Membership, d["membership"], "membership")
                    if d.get("membership")
                    else None
                )
                project = self._get(Project, d["project"], "project") if d.get("project") else None
                line = bank_import.book(
                    line,
                    request.user,
                    category=category,
                    membership=membership,
                    text=d.get("text", ""),
                    project=project,
                )
                text = f"gebucht als {line.booking.display_number}"
            elif what == "ignore":
                line = bank_import.ignore(line, request.user)
                text = "übergangen"
            else:
                line = bank_import.reopen(line)
                text = "wieder offen"
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            line,
            {"Kontoumsatz": [None, f"{line.date:%d.%m.%Y} {line.amount} €: {text}"]},
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=line.pk)).data)

    @action(detail=False, methods=["post"], url_path="apply-suggestions")
    def apply_suggestions(self, request, org_id: int):
        statement = None
        if raw := request.data.get("statement"):
            statement = get_object_or_404(BankStatement, organization=self.org, pk=raw)
        result = bank_import.apply_suggestions(self.org, request.user, statement)
        if result["done"]:
            record(
                self.org,
                request.user,
                "update",
                statement or self.org,
                {"Kontoauszug": [None, f"{result['done']} Vorschläge übernommen"]},
            )
        return Response(result)
