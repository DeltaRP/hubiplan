"""API der Quittungen: /api/orgs/<org_id>/finance/cash-receipts/… (Browser und App).

Ablauf: Entwurf anlegen → beide Unterschriften → abschließen (Buchung, Belegnummer, PDF)
→ ggf. per Mail schicken oder stornieren. Siehe konzepte/digitale-quittung.md.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import StoredSignature
from audit.log import current_via, record
from changes import idempotency
from members.models import Membership

from . import quittung, signature
from .models import Account, CashReceipt, Category, Project
from .serializers import OrgRelatedField
from .views import BookingPagination, FinanceMixin

# Diese Felder bestimmen, was unterschrieben wird: ändern leert die Unterschriften
SIGNED_FIELDS = ("direction", "counterparty_name", "amount", "purpose", "vat_rate")


def _drf(exc: DjangoValidationError) -> serializers.ValidationError:
    if hasattr(exc, "message_dict"):
        return serializers.ValidationError(exc.message_dict)
    return serializers.ValidationError(" ".join(exc.messages))


class CashReceiptSerializer(serializers.ModelSerializer):
    account = OrgRelatedField(queryset=Account.objects.none())
    category = OrgRelatedField(queryset=Category.objects.none())
    project = OrgRelatedField(queryset=Project.objects.none(), allow_null=True, required=False)
    membership = OrgRelatedField(
        queryset=Membership.objects.none(), allow_null=True, required=False
    )
    direction_label = serializers.CharField(source="get_direction_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    invoice_number = serializers.SerializerMethodField()
    booking_number = serializers.CharField(
        source="booking.display_number", read_only=True, default=None
    )
    cancel_number = serializers.CharField(
        source="cancel_booking.display_number", read_only=True, default=None
    )
    confirmation_text = serializers.SerializerMethodField()
    missing = serializers.SerializerMethodField()
    has_stored_signature = serializers.SerializerMethodField()

    class Meta:
        model = CashReceipt
        fields = [
            "id",
            "direction",
            "direction_label",
            "status",
            "status_label",
            "counterparty_name",
            "counterparty_address",
            "membership",
            "email",
            "amount",
            "purpose",
            "vat_rate",
            "account",
            "account_name",
            "category",
            "category_name",
            "project",
            "invoice",
            "invoice_number",
            "treasurer_signature",
            "treasurer_name",
            "treasurer_signed_at",
            "counterparty_signature",
            "counterparty_signed_at",
            "no_signature_reason",
            "confirmation_text",
            "missing",
            "has_stored_signature",
            "number",
            "receipt_date",
            "booking",
            "booking_number",
            "finalized_at",
            "pdf_sha256",
            "cancel_reason",
            "cancelled_at",
            "cancel_number",
            "cancel_sha256",
            "sent_at",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            f
            for f in fields
            if f
            not in (
                "direction",
                "counterparty_name",
                "counterparty_address",
                "membership",
                "email",
                "amount",
                "purpose",
                "vat_rate",
                "account",
                "category",
                "project",
            )
        ]

    def get_invoice_number(self, obj) -> str | None:
        return obj.invoice.display_number if obj.invoice_id else None

    def get_confirmation_text(self, obj) -> str:
        return obj.counterparty_confirmed or quittung.confirmation_text(obj)

    def get_missing(self, obj) -> list[str]:
        return quittung.missing(obj) if obj.status == CashReceipt.Status.DRAFT else []

    def get_has_stored_signature(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        # Einmal je Anfrage, nicht je Quittung der Liste (B-P03)
        if "_has_stored_signature" not in self.context:
            self.context["_has_stored_signature"] = bool(
                user
                and user.is_authenticated
                and StoredSignature.objects.filter(user=user).exists()
            )
        return self.context["_has_stored_signature"]

    def validate_counterparty_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(gettext("Bitte den Namen angeben."))
        return value

    def validate_purpose(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(gettext("Bitte den Zweck angeben."))
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(gettext("Der Betrag muss größer als 0 sein."))
        return value

    def validate_vat_rate(self, value):
        if value is not None and not (0 < value < 100):
            raise serializers.ValidationError(
                gettext("Bitte einen Steuersatz zwischen 0 und 100 angeben.")
            )
        return value

    def validate(self, attrs):
        org = self.context["org"]
        inst = self.instance
        if inst is not None and inst.status != CashReceipt.Status.DRAFT:
            raise serializers.ValidationError(
                gettext("Die Quittung ist abgeschlossen und lässt sich nicht mehr ändern.")
            )
        account = attrs.get("account", inst.account if inst else None)
        if account is not None:
            try:
                quittung.validate_account(org, account)
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
        direction = attrs.get("direction", inst.direction if inst else None)
        category = attrs.get("category", inst.category if inst else None)
        if category is not None and direction:
            kind = "income" if direction == CashReceipt.Direction.IN else "expense"
            if not category.allows(kind) or not category.is_active:
                raise serializers.ValidationError(
                    {"category": gettext("Die Kategorie passt nicht zu dieser Richtung.")}
                )
        membership = attrs.get("membership")
        if membership is not None and (inst is None or membership != inst.membership):
            # Anschrift und E-Mail aus der Mitgliederakte, wenn nicht selbst eingetragen.
            # Sie stehen in den Kontaktdaten, wie der Verein sie sieht (FIN-F01).
            from members.services import contact_for

            person = membership.person
            contact = contact_for(person, membership.organization)
            if contact is not None and not attrs.get(
                "counterparty_address", inst.counterparty_address if inst else ""
            ):
                attrs["counterparty_address"] = "\n".join(
                    x
                    for x in (contact.street, f"{contact.postal_code} {contact.city}".strip())
                    if x
                )
            if (
                contact is not None
                and contact.email
                and not attrs.get("email", inst.email if inst else "")
            ):
                attrs["email"] = contact.email
            if not attrs.get("counterparty_name"):
                attrs["counterparty_name"] = f"{person.first_name} {person.last_name}".strip()
        if inst is not None and inst.invoice_id:
            if any(k in attrs and attrs[k] != getattr(inst, k) for k in ("direction", "amount")):
                raise serializers.ValidationError(
                    gettext(
                        "Richtung und Betrag kommen aus der Rechnung und lassen sich nicht ändern."
                    )
                )
        return attrs


class CashReceiptViewSet(
    FinanceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CashReceiptSerializer
    pagination_class = BookingPagination
    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]

    def get_queryset(self):
        qs = CashReceipt.objects.filter(organization=self.org).select_related(
            "organization",
            "account",
            "category",
            "booking__organization",
            "cancel_booking__organization",
            "invoice__organization",
        )
        if (state := self.request.query_params.get("status")) in CashReceipt.Status.values:
            qs = qs.filter(status=state)
        if term := self.request.query_params.get("suche", "").strip():
            qs = qs.filter(counterparty_name__icontains=term) | qs.filter(number__icontains=term)
        return qs.order_by("-created_at")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        # Optionaler Idempotency-Key: die App sendet offline vorbereitete Quittungen später;
        # ein erneuter Versuch legt keinen zweiten Entwurf an.
        claim = idempotency.claim(request, "finance.cash-receipt.create")
        if claim.done:
            receipt = get_object_or_404(self.get_queryset(), pk=claim.result["id"])
            return Response(self.get_serializer(receipt).data, status=status.HTTP_200_OK)
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        claim.remember({"id": ser.instance.pk})
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        instance = serializer.save(
            organization=self.org,
            created_by=self.request.user,
            source=(current_via.get() or "Browser")[:60],
        )
        record(
            self.org,
            self.request.user,
            "create",
            instance,
            {
                "Quittung": [
                    None,
                    f"Entwurf {quittung.euro(instance.amount)} {instance.counterparty_name}",
                ]
            },
        )

    @transaction.atomic
    def perform_update(self, serializer):
        # Erst sperren, dann gegen den frischen Stand neu prüfen: Eine Änderung, die vor
        # einem parallelen Abschluss geprüft wurde, darf die Quittung danach nicht mehr ändern.
        inst = serializer.instance
        CashReceipt.objects.select_for_update().filter(pk=inst.pk).values_list("pk").first()
        inst.refresh_from_db()
        serializer = self._revalidate(serializer)
        data = serializer.validated_data
        changed = [k for k in SIGNED_FIELDS if k in data and data[k] != getattr(inst, k)]
        if changed:
            quittung.clear_signatures(inst)
        serializer.save()

    @staticmethod
    def _revalidate(serializer):
        fresh = type(serializer)(
            serializer.instance,
            data=serializer.initial_data,
            partial=serializer.partial,
            context=serializer.context,
        )
        fresh.is_valid(raise_exception=True)
        return fresh

    @transaction.atomic
    def perform_destroy(self, instance):
        CashReceipt.objects.select_for_update().filter(pk=instance.pk).values_list("pk").first()
        instance.refresh_from_db()
        if instance.status != CashReceipt.Status.DRAFT:
            raise serializers.ValidationError(
                gettext("Abgeschlossene Quittungen werden nicht gelöscht. Bitte stornieren.")
            )
        record(
            self.org,
            self.request.user,
            "delete",
            instance,
            {
                "Quittung": [
                    f"Entwurf {quittung.euro(instance.amount)} {instance.counterparty_name}",
                    None,
                ]
            },
        )
        instance.delete()

    def _detail(self, receipt, code=status.HTTP_200_OK):
        receipt = self.get_queryset().get(pk=receipt.pk)
        return Response(self.get_serializer(receipt).data, status=code)

    def _locked(self) -> CashReceipt:
        receipt = self.get_object()
        return CashReceipt.objects.select_for_update().get(pk=receipt.pk)

    @extend_schema(request=dict, responses=CashReceiptSerializer)
    @action(detail=True, methods=["put", "delete"], url_path=r"signatures/(?P<role>[a-z]+)")
    @transaction.atomic
    def signatures(self, request, org_id: int, pk: int, role: str):
        """Unterschrift setzen (PUT ``{strokes}``, Kassierer auch ``{use_stored: true}``;
        Gegenseite beim Eingang auch ``{declined: "Grund"}``) oder entfernen (DELETE)."""
        if role not in ("treasurer", "counterparty"):
            raise serializers.ValidationError(gettext("Unbekannte Unterschrift."))
        receipt = self._locked()
        try:
            if request.method == "DELETE":
                quittung._draft(receipt)
                if role == "treasurer":
                    receipt.treasurer_signature = None
                    receipt.treasurer_user = None
                    receipt.treasurer_name = ""
                    receipt.treasurer_signed_at = None
                else:
                    receipt.counterparty_signature = None
                    receipt.counterparty_signed_at = None
                    receipt.counterparty_confirmed = ""
                    receipt.no_signature_reason = ""
            else:
                data = request.data if isinstance(request.data, dict) else {}
                signed_at = _datetime(data.get("signed_at"))
                if role == "treasurer":
                    quittung.sign_treasurer(
                        receipt,
                        request.user,
                        strokes=None if data.get("use_stored") else data,
                        use_stored=bool(data.get("use_stored")),
                        signed_at=signed_at,
                    )
                elif data.get("declined") is not None:
                    quittung.without_counterparty(receipt, str(data.get("declined")))
                else:
                    quittung.sign_counterparty(receipt, strokes=data, signed_at=signed_at)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        receipt.save()
        return self._detail(receipt)

    @extend_schema(request=dict, responses=CashReceiptSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def finalize(self, request, org_id: int, pk: int):
        """Abschließen (``Idempotency-Key`` Pflicht): ``{confirmed: true, signed_at?}``."""
        receipt = self.get_object()
        claim = idempotency.claim(request, f"finance.cash-receipt.{receipt.pk}", required=True)
        if claim.done:
            return self._detail(receipt)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            receipt = quittung.finalize(
                receipt,
                request.user,
                confirmed=data.get("confirmed") is True,
                signed_at=_datetime(data.get("signed_at")),
            )
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            receipt,
            {
                "Quittung": [
                    "Entwurf",
                    f"{receipt.number} abgeschlossen: {quittung.euro(receipt.amount)} "
                    f"{'von' if receipt.receives else 'an'} {receipt.counterparty_name}, "
                    f"PDF SHA-256 {receipt.pdf_sha256}",
                ]
            },
        )
        claim.remember({"id": receipt.pk})
        if receipt.email and data.get("send") is True:
            quittung.send(receipt)
        return self._detail(receipt)

    @extend_schema(request=dict, responses=CashReceiptSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, org_id: int, pk: int):
        receipt = self.get_object()
        reason = str((request.data or {}).get("reason") or "")
        try:
            receipt = quittung.cancel(receipt, request.user, reason)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            receipt,
            {
                "Quittung": [
                    receipt.number,
                    f"storniert (Gegenbuchung {receipt.cancel_booking.display_number}): "
                    f"{receipt.cancel_reason}",
                ]
            },
        )
        return self._detail(receipt)

    @extend_schema(request=dict, responses=CashReceiptSerializer)
    @action(detail=True, methods=["post"])
    def send(self, request, org_id: int, pk: int):
        receipt = self.get_object()
        email = str((request.data or {}).get("email") or "").strip() or None
        if email:
            try:
                serializers.EmailField().run_validation(email)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"email": exc.detail}) from exc
        try:
            sent = quittung.send(receipt, email)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        if not sent:
            raise serializers.ValidationError(gettext("Die E-Mail konnte nicht verschickt werden."))
        record(
            self.org,
            request.user,
            "update",
            receipt,
            {"Quittung": [None, f"{receipt.number} an {receipt.email} verschickt"]},
        )
        return self._detail(receipt)

    @extend_schema(responses={(200, "*/*"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request, org_id: int, pk: int):
        """PDF: abgeschlossen das gespeicherte, sonst die Vorschau mit „Entwurf“."""
        receipt = self.get_object()
        content, name = quittung.document_bytes(receipt)
        response = HttpResponse(content, content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(request=dict, responses=CashReceiptSerializer)
    @action(detail=False, methods=["post"], url_path=r"from-invoice/(?P<invoice_id>\d+)")
    @transaction.atomic
    def from_invoice(self, request, org_id: int, invoice_id: str):
        """Entwurf zur Barzahlung einer Rechnung: ``{account, amount?}`` (ohne Betrag: Rest)."""
        from billing.models import Invoice
        from billing.services import settings_for

        if "billing" not in (self.org.enabled_modules or []):
            raise serializers.ValidationError(gettext("Beiträge sind nicht freigeschaltet."))
        invoice = get_object_or_404(Invoice, organization=self.org, pk=invoice_id)
        if invoice.status != Invoice.Status.OPEN or invoice.outstanding <= 0:
            raise serializers.ValidationError(gettext("Die Rechnung ist nicht offen."))
        cfg = settings_for(self.org)
        if cfg.category is None:
            raise serializers.ValidationError(
                gettext(
                    "Bitte unter Beiträge → Einstellungen eine Kategorie für "
                    "Beitragszahlungen wählen."
                )
            )
        data = request.data if isinstance(request.data, dict) else {}
        amount = data.get("amount")
        name_lines = invoice.recipient_name.splitlines()
        values = {
            "direction": CashReceipt.Direction.IN,
            "counterparty_name": name_lines[0] if name_lines else "Unbekannt",
            "counterparty_address": invoice.recipient_address,
            "email": invoice.recipient_email or "",
            "amount": amount if amount not in (None, "") else str(invoice.outstanding),
            "purpose": f"{invoice.subject} ({invoice.display_number})"[:200],
            "account": data.get("account"),
            "category": cfg.category_id,
            "project": invoice.project_id,
        }
        ser = self.get_serializer(data=values)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["amount"] > invoice.outstanding:
            raise serializers.ValidationError(
                {
                    "amount": gettext("Offen sind nur noch {x}.").format(
                        x=quittung.euro(invoice.outstanding)
                    )
                }
            )
        membership = (
            invoice.membership
            if invoice.membership and (invoice.membership.organization_id == self.org.pk)
            else None
        )
        receipt = ser.save(
            organization=self.org,
            created_by=request.user,
            invoice=invoice,
            membership=membership,
            source=(current_via.get() or "Browser")[:60],
        )
        record(
            self.org,
            request.user,
            "create",
            receipt,
            {"Quittung": [None, f"Entwurf zu {invoice.display_number}"]},
        )
        return self._detail(receipt, status.HTTP_201_CREATED)


def _datetime(value):
    if value in (None, ""):
        return None
    field = serializers.DateTimeField()
    try:
        return field.to_internal_value(value)
    except serializers.ValidationError as exc:
        raise serializers.ValidationError({"signed_at": exc.detail}) from exc


class MySignatureView(APIView):
    """Hinterlegte Unterschrift der angemeldeten Person (Mein Konto › Unterschrift)."""

    permission_classes = [IsAuthenticated]

    def _data(self, request):
        obj = StoredSignature.objects.filter(user=request.user).first()
        if obj is None:
            return {"signature": None, "updated_at": None}
        return {"signature": obj.strokes, "updated_at": obj.updated_at}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(self._data(request))

    @extend_schema(request=dict, responses=dict)
    def put(self, request):
        try:
            shape = signature.normalize(request.data if isinstance(request.data, dict) else None)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        StoredSignature.objects.update_or_create(user=request.user, defaults={"strokes": shape})
        return Response(self._data(request))

    def delete(self, request):
        StoredSignature.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
