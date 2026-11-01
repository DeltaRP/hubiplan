"""Rechnungen im Mitgliederbereich und im Abteilungsbereich."""

from __future__ import annotations

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import DEPT_INVOICES_VIEW
from core.tenancy import tenant_context
from organizations.terms import fill
from portal.views import DepartmentScopedMixin, _portal_access

from .models import Invoice, InvoiceLine
from .serializers import InvoiceDetailSerializer, InvoiceListSerializer
from .units import portal_issuers
from .views import invoice_pdf_response

VISIBLE = (Invoice.Status.OPEN, Invoice.Status.PAID, Invoice.Status.CANCELLED)


def _billing_on(club) -> bool:
    return "billing" in (club.enabled_modules or [])


def _own(issuer, access):
    return (
        Invoice.objects.filter(
            organization=issuer,
            membership_id=access.membership_id,
            recipient_kind=Invoice.Recipient.MEMBER,
            status__in=VISIBLE,
        )
        .select_related("organization", "department", "run")
        .order_by("-date", "-pk")
    )


class PortalInvoicesView(APIView):
    """Eigene Rechnungen und Beiträge, die über eine Sammelrechnung laufen."""

    def get(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        if not _billing_on(club):
            return Response({"invoices": [], "collective": []})
        # Rechnungen von Untereinheiten mit eigenem Arbeitsbereich stehen dabei
        invoices = []
        for issuer in portal_issuers(club)[1:]:
            with tenant_context(issuer.pk, request.user.pk):
                invoices += InvoiceListSerializer(_own(issuer, access), many=True).data
        with tenant_context(club.pk, request.user.pk):
            own = _own(club, access)
            collective = (
                InvoiceLine.objects.filter(
                    membership_id=access.membership_id,
                    invoice__recipient_kind=Invoice.Recipient.DEPARTMENT,
                    invoice__status__in=VISIBLE,
                )
                .select_related("invoice__organization", "invoice__department")
                .order_by("-invoice__date")
            )
            return Response(
                {
                    "invoices": sorted(
                        [*InvoiceListSerializer(own, many=True).data, *invoices],
                        key=lambda row: (str(row["date"]), row["id"]),
                        reverse=True,
                    ),
                    "collective": [
                        {
                            "id": line.pk,
                            "number": line.invoice.display_number,
                            "date": line.invoice.date,
                            "subject": line.invoice.subject,
                            "department_name": line.invoice.department.name,
                            "amount": f"{line.amount:.2f}",
                            "status": line.invoice.status,
                            "status_label": line.invoice.get_status_display(),
                        }
                        for line in collective
                    ],
                }
            )


class PortalInvoicePdfView(APIView):
    def get(self, request, access_id: int, pk: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        for issuer in portal_issuers(club) or [club]:
            with tenant_context(issuer.pk, request.user.pk):
                invoice = _own(issuer, access).filter(pk=pk).first()
                if invoice is not None:
                    return invoice_pdf_response(
                        invoice, request.query_params.get("download") == "1"
                    )
        raise Http404


class DepartmentInvoicesView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_INVOICES_VIEW
    write_permission = DEPT_INVOICES_VIEW

    def get(self, request, dept_id: int):
        if not _billing_on(self.org):
            return Response([])
        qs = (
            Invoice.objects.filter(organization=self.org, department=self.dept, status__in=VISIBLE)
            .select_related("organization", "department", "run")
            .prefetch_related("lines__membership__person", "payments__booking__account")
        )
        return Response(InvoiceDetailSerializer(qs, many=True).data)


class DepartmentInvoicePdfView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_INVOICES_VIEW

    def get(self, request, dept_id: int, pk: int):
        invoice = get_object_or_404(
            Invoice.objects.select_related("organization"),
            organization=self.org,
            department=self.dept,
            status__in=VISIBLE,
            pk=pk,
        )
        return invoice_pdf_response(invoice, request.query_params.get("download") == "1")


class PortalMandateView(APIView):
    """SEPA-Mandat im Mitgliederbereich: ansehen, erteilen, widerrufen."""

    def _context(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        return access, access.organization

    def _data(self, club, access) -> dict:
        from . import sepa
        from .models import Mandate
        from .serializers import MandateSerializer
        from .services import settings_for

        cfg = settings_for(club)
        mandate = (
            Mandate.objects.filter(
                organization=club,
                membership_id=access.membership_id,
                status=Mandate.Status.ACTIVE,
            )
            .select_related("membership__person")
            .first()
        )
        available = (
            _billing_on(club) and cfg.sepa_enabled and sepa.creditor_id_valid(cfg.creditor_id)
        )
        preview_ref = mandate.reference if mandate else "wird bei Erteilung vergeben"
        return {
            "available": available,
            "club_name": club.name,
            "creditor_id": cfg.creditor_id,
            "mandate": MandateSerializer(mandate).data if mandate else None,
            "text": sepa.mandate_text(club, cfg.creditor_id, preview_ref),
        }

    def get(self, request, access_id: int):
        access, club = self._context(request, access_id)
        with tenant_context(club.pk, request.user.pk):
            return Response(self._data(club, access))

    @transaction.atomic
    def post(self, request, access_id: int):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.utils import timezone
        from rest_framework import serializers

        from audit.log import record
        from outbox import mail

        from . import sepa
        from .models import Mandate

        access, club = self._context(request, access_id)
        with tenant_context(club.pk, request.user.pk):
            if not self._data(club, access)["available"]:
                raise serializers.ValidationError(
                    fill("{e_Nom} bietet keine Lastschrift an.", club)
                )
            if request.data.get("consent") is not True:
                raise serializers.ValidationError(
                    {"consent": gettext("Bitte bestätige den Text des Mandats.")}
                )
            try:
                mandate = sepa.create_mandate(
                    club,
                    membership=access.membership,
                    signed_on=timezone.localdate(),
                    source=Mandate.Source.ONLINE,
                    user=request.user,
                    holder=str(request.data.get("holder", "")),
                    iban=str(request.data.get("iban", "")),
                    bic=str(request.data.get("bic", "")),
                )
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.message_dict) from exc
            record(
                club,
                request.user,
                "create",
                mandate,
                {"SEPA-Mandat": [None, f"{mandate.reference} im Mitgliederbereich erteilt"]},
            )
            data = self._data(club, access)
            if request.user.email:
                mail.send(
                    request.user.email,
                    f"Ihr SEPA-Lastschriftmandat für {club.name}",
                    "Guten Tag,\n\nSie haben folgendes Mandat erteilt:\n\n"
                    f"{data['text']}\n\nKontoinhaber: {mandate.holder}\n"
                    f"IBAN: {sepa.masked_iban(mandate.iban)}\n"
                    f"Datum: {mandate.signed_on:%d.%m.%Y}\n\n"
                    "Sie können es im Mitgliederbereich jederzeit widerrufen.\n\n"
                    f"Viele Grüße\n{club.name}\n",
                    organization=club,
                    kind="mandat",
                    fail_silently=True,
                )
            return Response(data, status=201)

    @transaction.atomic
    def delete(self, request, access_id: int):
        from rest_framework.exceptions import NotFound

        from audit.log import record

        from . import sepa
        from .models import Mandate

        access, club = self._context(request, access_id)
        with tenant_context(club.pk, request.user.pk):
            mandate = Mandate.objects.filter(
                organization=club,
                membership_id=access.membership_id,
                status=Mandate.Status.ACTIVE,
            ).first()
            if mandate is None:
                raise NotFound(gettext("Kein gültiges Mandat."))
            sepa.revoke(mandate)
            record(
                club,
                request.user,
                "update",
                mandate,
                {"SEPA-Mandat": [mandate.reference, "im Mitgliederbereich widerrufen"]},
            )
            return Response(self._data(club, access))
