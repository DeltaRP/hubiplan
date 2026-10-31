"""Verwaltung in der App, Schritt B4: Kasse mit Belegfoto.

Lesen wie im Browser (Konten, Kategorien, Buchungen, Jahresübersicht, Beleg ansehen). Neu
gebucht wird aus der App nur mit Beleg, in einem Schritt (``app-booking/``): Buchung und
Beleg zusammen. Wie im Browser gibt es dafür kein „Rückgängig“ (Belege sind Dateien).
Storno, Abschlüsse und Berichte bleiben im Browser. Entwürfe, die ohne Netz auf dem
Telefon lagen, schickt die App später mit demselben ``Idempotency-Key``: doppelt
gesendet wird nur einmal gebucht.

Schritt B5: offene Rechnungen suchen und eine Barzahlung verbuchen (``billing/invoices/<pk>/
cash/``), immer in eine Barkasse. Die Quittung kommt als PDF von ``billing/payments/<pk>/
receipt/``. Beitragsläufe, Mahnungen und SEPA bleiben im Browser.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import diff, record, snapshot
from billing import pdf as billing_pdf
from billing import services as billing_services
from billing import views as billing_views
from billing.models import Invoice
from changes import idempotency
from finance import services
from finance import views as finance_views
from finance.models import Account, Booking
from finance.serializers import BookingSerializer

from .admin_api import AppAdminAccess


class AppBookingView(AppAdminAccess, finance_views.FinanceMixin, APIView):
    """POST (multipart): Buchung mit Beleg (``file``), Felder wie ``finance/bookings/``."""

    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses=dict)
    @transaction.atomic
    def post(self, request, org_id: int):
        claim = idempotency.claim(request, "finance.app-booking", required=True)
        if claim.done:
            booking = Booking.objects.get(organization=self.org, pk=claim.result["id"])
            return Response(self._data(booking), status=status.HTTP_201_CREATED)
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Aus der App nur mit Belegfoto."})
        values = {k: v for k, v in request.data.items() if k != "file"}
        data = BookingSerializer(data=values, context={"org": self.org, "request": request})
        data.is_valid(raise_exception=True)
        date = data.validated_data["date"]
        finance_views._ensure_open(self.org, self.org.fiscal_year_of(date))
        year = self.org.fiscal_year_of(date)
        booking = data.save(
            organization=self.org,
            year=year,
            number=services.next_number(self.org.pk, year),
            created_by=request.user,
        )
        finance_views.cash_ok([booking.account, booking.to_account], booking.date)
        record(self.org, request.user, "create", booking, diff({}, snapshot(booking)))
        finance_views.attach_receipt(self.org, booking, upload, request.user)
        claim.remember({"id": booking.pk})
        return Response(self._data(booking), status=status.HTTP_201_CREATED)

    def _data(self, booking: Booking) -> dict:
        booking = (
            Booking.objects.filter(pk=booking.pk)
            .select_related("account", "to_account", "category")
            .prefetch_related("receipts")
            .get()
        )
        return BookingSerializer(booking, context={"org": self.org, "request": self.request}).data


class CashPaymentSerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    account = serializers.IntegerField()


class AppCashPaymentView(AppAdminAccess, billing_views.BillingMixin, APIView):
    """POST: Barzahlung zu einer offenen Rechnung (ohne Betrag: der offene Rest).

    Antwort: die Rechnung wie im Browser und ``payment`` (Kennung für die Quittung)."""

    @extend_schema(request=CashPaymentSerializer, responses=dict)
    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        invoice = get_object_or_404(Invoice, organization=self.org, pk=pk)
        claim = idempotency.claim(request, f"billing.app-cash.{invoice.pk}", required=True)
        if claim.done:
            return self._answer(invoice, claim.result["payment"])
        ser = CashPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        account = Account.objects.filter(
            organization=self.org, pk=data["account"], is_active=True
        ).first()
        if account is None or account.kind != Account.Kind.CASH:
            raise serializers.ValidationError({"account": "Bitte eine Barkasse wählen."})
        amount = data.get("amount")
        try:
            payment = billing_services.add_payment(
                invoice,
                date=data.get("date") or timezone.localdate(),
                amount=invoice.outstanding if amount is None else amount,
                method="cash",
                account=account,
                user=request.user,
            )
        except DjangoValidationError as exc:
            raise billing_views._as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "create",
            payment,
            {
                "Zahlung": [
                    None,
                    f"{billing_pdf.euro(payment.amount)} zu {invoice.display_number} "
                    f"(bar, Buchung {payment.booking.display_number})",
                ]
            },
        )
        claim.remember({"payment": payment.pk})
        return self._answer(invoice, payment.pk, status.HTTP_201_CREATED)

    def _answer(self, invoice: Invoice, payment_id: int, code=status.HTTP_200_OK) -> Response:
        invoice = (
            billing_views._invoice_qs(self.org)
            .prefetch_related("lines", "payments__booking__account", "dunnings")
            .get(pk=invoice.pk)
        )
        data = billing_views.InvoiceDetailSerializer(invoice).data
        return Response({"invoice": data, "payment": payment_id}, status=code)
