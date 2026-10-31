"""API der Kasse: /api/orgs/<org_id>/finance/…"""

from __future__ import annotations

import datetime
import mimetypes

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Max, ProtectedError, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import FINANCE_EDIT, FINANCE_VIEW, ROLES_MANAGE
from audit.log import diff, record, snapshot
from core.api_base import AuditMixin, OrgScopedMixin
from core.files import delete_on_commit
from organizations.models import Organization

from . import retention, services, statistics
from .models import (
    Account,
    BankLine,
    Booking,
    Category,
    Project,
    ProjectSeries,
    Receipt,
    ReopenedClosing,
    TaxArea,
    YearClosing,
)
from .serializers import (
    AccountSerializer,
    BookingSerializer,
    CategorySerializer,
    ProjectSerializer,
    ProjectSeriesSerializer,
    ReceiptSerializer,
)

MAX_RECEIPT_BYTES = 15 * 1024 * 1024
RECEIPT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    # E-Rechnungen (XRechnung, reines XML)
    "application/xml",
    "text/xml",
}


def _count(model, field: str):
    """Anzahl verbundener Zeilen als Unterabfrage (ohne Mehrfachzählung bei mehreren)."""
    from django.db.models import IntegerField, OuterRef, Subquery
    from django.db.models.functions import Coalesce

    rows = (
        model.objects.filter(**{field: OuterRef("pk")})
        .order_by()
        .values(field)
        .annotate(n=Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(rows, output_field=IntegerField()), 0)


class FinanceMixin(OrgScopedMixin):
    read_permission = FINANCE_VIEW
    write_permission = FINANCE_EDIT
    allowed_org_types = (
        Organization.Type.CLUB,
        Organization.Type.FEDERATION,
        Organization.Type.UNIT,
    )

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if "finance" not in (self.org.enabled_modules or []):
            raise NotFound("Die Kasse ist für diese Organisation nicht freigeschaltet.")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx


class _ProtectedDeleteMixin:
    protected_message = "Wird noch verwendet."

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            raise serializers.ValidationError(self.protected_message) from exc


class AccountViewSet(FinanceMixin, AuditMixin, _ProtectedDeleteMixin, viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    pagination_class = None
    protected_message = (
        "Auf dem Konto gibt es Buchungen. Statt zu löschen bitte auf „inaktiv“ setzen."
    )

    def get_queryset(self):
        # Anzahl Buchungen als Unterabfragen statt je Konto (PERF-02)
        return Account.objects.filter(organization=self.org).annotate(
            n_out=_count(Booking, "account"), n_in=_count(Booking, "to_account")
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "org", None) is not None and self.action == "list":
            ctx["balances"] = services.balances(self.org.pk)
            ctx["balances_all"] = services.balances(self.org.pk, all_dates=True)
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @transaction.atomic
    def perform_update(self, serializer):
        if self._lock_and_refresh(serializer.instance):
            serializer = self._revalidate(serializer)
        instance = serializer.instance
        data = serializer.validated_data
        changes_opening = any(
            k in data and data[k] != getattr(instance, k)
            for k in ("opening_balance", "opening_date")
        )
        if changes_opening:
            dates = [instance.opening_date, data.get("opening_date", instance.opening_date)]
            first = min(self.org.fiscal_year_of(d) for d in dates)
            # Alle betroffenen Jahre gegen einen gleichzeitigen Abschluss sperren
            services.lock_years_from(self.org, first)
            if YearClosing.objects.filter(organization=self.org, year__gte=first).exists():
                raise serializers.ValidationError(
                    "Der Anfangsbestand betrifft ein abgeschlossenes Geschäftsjahr und lässt "
                    "sich nicht mehr ändern."
                )
        with transaction.atomic():
            super().perform_update(serializer)
            account = serializer.instance
            if changes_opening or "kind" in data:
                cash_ok([account], account.opening_date)


class CategoryViewSet(FinanceMixin, AuditMixin, viewsets.ModelViewSet):
    """Kategorien. Gebuchte Kategorien werden archiviert (``is_active=False``), nie gelöscht,
    damit Buchungen und Kassenberichte unverändert bleiben."""

    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        return Category.objects.filter(organization=self.org).annotate(
            n_bookings=_count(Booking, "category")
        )

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    def _reasons(self, category: Category) -> list[str]:
        from billing.models import BillingSettings

        reasons = []
        count = category.bookings.count()
        if count:
            years = sorted(set(category.bookings.values_list("year", flat=True)))
            labels = ", ".join(self.org.fiscal_label(y) for y in years)
            reasons.append(
                f"in {count} {'Buchung' if count == 1 else 'Buchungen'} verwendet "
                f"(Geschäftsjahr {labels})"
            )
        if BillingSettings.objects.filter(organization=self.org, category=category).exists():
            reasons.append("als Kategorie für Beitragszahlungen eingestellt")
        return reasons

    @action(detail=True, methods=["get"])
    def usage(self, request, org_id: int, pk: int):
        """Vorschau: wird die Kategorie gelöscht oder archiviert, und warum?"""
        category = self.get_object()
        reasons = self._reasons(category)
        return Response(
            {
                "deletable": not reasons,
                "reasons": reasons,
                "is_archived": not category.is_active,
            }
        )

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Löschen, wenn unbenutzt; sonst 409 mit Grund (dann archivieren)."""
        category = self.get_object()
        reasons = self._reasons(category)
        if reasons:
            return Response(
                {
                    "detail": f"„{category.name}“ wird noch verwendet und kann nur "
                    "archiviert werden.",
                    "reasons": reasons,
                    "can_archive": category.is_active,
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            self.perform_destroy(category)
        except ProtectedError as exc:  # gleichzeitig gebucht
            raise serializers.ValidationError(
                "Die Kategorie wurde gerade gebucht. Bitte archivieren."
            ) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def archive(self, request, org_id: int, pk: int):
        return self._set_archived(True)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def restore(self, request, org_id: int, pk: int):
        return self._set_archived(False)

    def _set_archived(self, archived: bool):
        category = self.get_object()
        if category.is_active == archived:
            category.is_active = not archived
            category.save(update_fields=["is_active"])
            record(
                self.org,
                self.request.user,
                "update",
                category,
                {"archiviert": [not archived, archived]},
            )
        return Response(self.get_serializer(category).data)


class BookingPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


class BookingViewSet(FinanceMixin, AuditMixin, _ProtectedDeleteMixin, viewsets.ModelViewSet):
    serializer_class = BookingSerializer
    protected_message = (
        "Die Buchung gehört zu einem Zahlungseingang. Bitte die Zahlung unter "
        "Beiträge → Rechnungen entfernen."
    )
    pagination_class = BookingPagination

    def get_queryset(self):
        qs = Booking.objects.filter(organization=self.org).select_related(
            "organization",
            "account",
            "to_account",
            "category",
            "membership__person",
            "department",
            "payment__invoice__organization",
            "project",
            "cancels__organization",
            "cancellation__organization",
        )
        if self.action != "list":
            return qs.prefetch_related("receipts")
        p = self.request.query_params
        year = p.get("jahr")
        if year and year.isdigit():
            qs = qs.filter(year=int(year))
        if (account := p.get("konto")) and account.isdigit():
            qs = qs.filter(account_id=account) | qs.filter(to_account_id=account)
        if (cat := p.get("kategorie")) and cat.isdigit():
            qs = qs.filter(category_id=cat)
        if (kind := p.get("art")) in Booking.Kind.values:
            qs = qs.filter(kind=kind)
        if (area := p.get("bereich")) is not None and (area in TaxArea.values or area == "-"):
            qs = qs.filter(category__tax_area="" if area == "-" else area)
        if (member := p.get("mitglied")) and member.isdigit():
            qs = qs.filter(membership_id=member)
        if (project := p.get("veranstaltung")) == "-":
            qs = qs.filter(project__isnull=True)
        elif project and project.isdigit():
            qs = qs.filter(project_id=project)
        if von := _date_param(p.get("von")):
            qs = qs.filter(date__gte=von)
        if bis := _date_param(p.get("bis")):
            qs = qs.filter(date__lte=bis)
        if partner := p.get("partner", "").strip():
            qs = qs.filter(counterparty__iexact=partner)
        if p.get("ohne_beleg") in ("1", "true"):
            # Ausgeblendete Belege zählen nicht
            qs = qs.exclude(
                pk__in=Receipt.objects.filter(organization=self.org, hidden_at__isnull=True).values(
                    "booking_id"
                )
            )
        if term := p.get("suche", "").strip():
            qs = qs.filter(services.search_filter(term))
        return qs.prefetch_related("receipts").order_by("-date", "-number").distinct()

    @transaction.atomic
    def perform_create(self, serializer):
        self._open(date=serializer.validated_data["date"])
        year = self.org.fiscal_year_of(serializer.validated_data["date"])
        number = services.next_number(self.org.pk, year)
        instance = serializer.save(
            organization=self.org,
            year=year,
            number=number,
            created_by=self.request.user,
        )
        cash_ok([instance.account, instance.to_account], instance.date)
        record(self.org, self.request.user, "create", instance, diff({}, snapshot(instance)))

    @action(detail=False, methods=["get"])
    def counterparties(self, request, org_id: int):
        """Bisherige Empfänger/Zahler als Vorschläge, häufige zuerst.

        ?art=expense|income bevorzugt Namen dieser Art, ?jahr= begrenzt auf ein Jahr.
        """
        qs = Booking.objects.filter(organization=self.org).exclude(counterparty="")
        p = request.query_params
        if (year := p.get("jahr")) and year.isdigit():
            qs = qs.filter(year=int(year))
        rows = qs.values("counterparty", "kind").annotate(n=Count("id"), last=Max("date"))
        kind = p.get("art")
        names: dict[str, dict] = {}
        for row in rows:
            key = row["counterparty"].casefold()
            entry = names.setdefault(
                key, {"name": row["counterparty"], "count": 0, "same": 0, "last": row["last"]}
            )
            entry["count"] += row["n"]
            if row["kind"] == kind:
                entry["same"] += row["n"]
            if row["last"] and (entry["last"] is None or row["last"] > entry["last"]):
                entry["last"] = row["last"]
        result = sorted(
            names.values(), key=lambda e: (-e["same"], -e["count"], e["name"].casefold())
        )
        return Response([{"name": e["name"], "count": e["count"]} for e in result[:500]])

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def renumber(self, request, org_id: int):
        """Buchungsnummern eines Geschäftsjahres nach Datum neu vergeben."""
        year = request.data.get("year")
        try:
            year = int(year)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({"year": "Bitte ein Geschäftsjahr angeben."}) from exc
        self._open(year=year)
        try:
            changed = services.renumber(self.org, year)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(" ".join(exc.messages)) from exc
        if changed:
            record(
                self.org,
                request.user,
                "update",
                self.org,
                {
                    "Buchungsnummern": [
                        None,
                        f"Geschäftsjahr {self.org.fiscal_label(year)} nach Datum neu nummeriert "
                        f"({changed} geändert)",
                    ]
                },
            )
        return Response({"changed": changed})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def storno(self, request, org_id: int, pk: int):
        """Storno mit Pflicht-Grund: Gegenbuchung im laufenden Jahr, Buchung bleibt."""
        booking = self.get_object()
        self._lock_and_refresh(booking)
        try:
            counter = services.cancel_booking(booking, request.user, request.data.get("reason"))
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict) from exc
            raise serializers.ValidationError(" ".join(exc.messages)) from exc
        record(
            self.org,
            request.user,
            "create",
            counter,
            {
                "Storno": [
                    None,
                    f"{booking.display_number} storniert durch {counter.display_number}: "
                    f"{counter.cancel_reason}",
                ]
            },
        )
        fresh = self.get_queryset().get(pk=booking.pk)
        return Response(self.get_serializer(fresh).data, status=status.HTTP_201_CREATED)

    def _open(self, **kwargs):
        try:
            services.ensure_open(self.org, **kwargs)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(" ".join(exc.messages)) from exc

    @transaction.atomic
    def perform_update(self, serializer):
        # Alles in einer Transaktion: Zeile sperren, frisch prüfen, Jahr sperren, schreiben.
        # Sonst endet die Jahressperre vor dem Schreiben, und ein paralleler Abschluss
        # könnte dazwischenkommen.
        if self._lock_and_refresh(serializer.instance):
            serializer = self._revalidate(serializer)
        instance = serializer.instance
        changed = {k for k, v in serializer.validated_data.items() if v != getattr(instance, k)}
        if changed <= {"project"}:
            # Nur die Veranstaltung: ändert keine Beträge, auch in abgeschlossenen Jahren
            super().perform_update(serializer)
            return
        self._open(year=instance.year)
        if "date" in serializer.validated_data:
            self._open(date=serializer.validated_data["date"])
        # Festgeschrieben (Folgemonat abgelaufen oder „Festschreiben bis“): nur noch Storno
        try:
            services.ensure_not_fixed(instance)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(" ".join(exc.messages)) from exc
        if services.in_storno(instance):
            data = serializer.validated_data
            locked = ("amount", "kind", "account", "to_account", "date", "number", "category")
            if any(k in data and data[k] != getattr(instance, k) for k in locked):
                raise serializers.ValidationError(
                    "Die Buchung gehört zu einem Storno. Betrag, Art, Konto, Datum, Nummer und "
                    "Kategorie bleiben, wie sie sind."
                )
        if _quittung_of(instance) is not None:
            data = serializer.validated_data
            locked = ("amount", "kind", "account", "date", "number", "category", "counterparty")
            if any(k in data and data[k] != getattr(instance, k) for k in locked):
                raise serializers.ValidationError(QUITTUNG_LOCKED)
        if hasattr(instance, "payment"):
            data = serializer.validated_data
            locked = ("amount", "kind", "account", "date")
            if any(k in data and data[k] != getattr(instance, k) for k in locked):
                raise serializers.ValidationError(
                    "Die Buchung gehört zu einem Zahlungseingang. Datum, Betrag und Konto "
                    "bitte über die Zahlung unter Beiträge → Rechnungen ändern."
                )
        if instance.bank_lines.exists():
            # Audit 31.10. FIN31-R03: zugeordneter Kontoumsatz muss zur Buchung passen
            data = serializer.validated_data
            locked = ("amount", "kind", "account")
            if any(k in data and data[k] != getattr(instance, k) for k in locked):
                raise serializers.ValidationError(
                    "Die Buchung ist einem Kontoumsatz zugeordnet. Betrag, Art und Konto "
                    "bitte nur ändern, nachdem die Zuordnung unter Kontoauszüge gelöst ist."
                )
        before = (instance.account, instance.to_account, instance.date)
        with transaction.atomic():
            super().perform_update(serializer)
            after = serializer.instance
            cash_ok(
                [before[0], before[1], after.account, after.to_account],
                min(before[2], after.date),
            )

    @transaction.atomic
    def perform_destroy(self, instance):
        self._lock_and_refresh(instance)
        self._open(year=instance.year)
        if _quittung_of(instance) is not None:
            raise serializers.ValidationError(QUITTUNG_LOCKED)
        if hasattr(instance, "payment"):
            raise serializers.ValidationError(self.protected_message)
        # GoBD: Löschen nur am Tag der Erfassung vor der Festschreibung, sonst Storno
        if not services.deletable(instance):
            raise serializers.ValidationError(
                f"Die Buchung {instance.display_number} lässt sich nicht mehr löschen (nur am "
                "Tag der Erfassung). Bitte stornieren: Das legt eine Gegenbuchung an, und "
                "beides bleibt nachvollziehbar."
            )
        accounts, since = [instance.account, instance.to_account], instance.date
        with transaction.atomic():
            # Zugeordnete Kontoumsätze wieder öffnen statt sie „erledigt“ ohne Buchung
            # stehen zu lassen (Audit 31.10. FIN31-R03)
            for line in BankLine.objects.select_for_update().filter(booking=instance):
                line.status = BankLine.Status.OPEN
                line.booking = None
                line.done_by = None
                line.done_at = None
                line.save(update_fields=["status", "booking", "done_by", "done_at"])
                record(
                    self.org,
                    self.request.user,
                    "update",
                    line,
                    {"Kontoumsatz": ["erledigt", "wieder offen (Buchung gelöscht)"]},
                )
            for receipt in instance.receipts.all():
                delete_on_commit(receipt.file)
            super().perform_destroy(instance)
            cash_ok(accounts, since)


def cash_ok(accounts, since) -> None:
    """Barkasse nie unter null (siehe services.ensure_cash_ok), als API-Fehler."""
    try:
        services.ensure_cash_ok(accounts, since)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(" ".join(exc.messages)) from exc


QUITTUNG_LOCKED = (
    "Die Buchung gehört zu einer unterschriebenen Quittung und lässt sich nicht ändern oder "
    "löschen. Bitte die Quittung stornieren."
)


def _quittung_of(booking: Booking):
    """Quittung, zu der die Buchung gehört (Abschluss oder Storno), sonst None."""
    from .models import CashReceipt

    return CashReceipt.objects.filter(Q(booking=booking) | Q(cancel_booking=booking)).first()


def _date_param(value):
    import datetime

    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class ReceiptUploadView(FinanceMixin, APIView):
    """POST: Beleg (Foto oder PDF) an eine Buchung hängen."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        booking = get_object_or_404(Booking, organization=self.org, pk=pk)
        _ensure_open(self.org, booking.year)
        receipt = attach_receipt(self.org, booking, request.FILES.get("file"), request.user)
        return Response(ReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)


def attach_receipt(org, booking: Booking, upload, user) -> Receipt:
    """Beleg prüfen, speichern und protokollieren (Browser und App)."""
    if upload is None:
        raise serializers.ValidationError({"file": "Bitte eine Datei wählen."})
    if upload.size > MAX_RECEIPT_BYTES:
        raise serializers.ValidationError({"file": "Die Datei ist größer als 15 MB."})
    content_type = (upload.content_type or mimetypes.guess_type(upload.name)[0] or "").lower()
    if content_type not in RECEIPT_TYPES:
        raise serializers.ValidationError(
            {"file": "Erlaubt sind PDF, Fotos (JPEG, PNG, WebP, HEIC) und E-Rechnungen (XML)."}
        )
    head = upload.read(16)
    upload.seek(0)
    if content_type == "application/pdf" and not head.startswith(b"%PDF"):
        raise serializers.ValidationError({"file": "Die Datei ist kein PDF."})
    info: dict = {}
    if content_type in ("application/pdf", "application/xml", "text/xml"):
        from . import einvoice

        data = upload.read()
        upload.seek(0)
        try:
            found = einvoice.read(data, content_type)
        except einvoice.EInvoiceError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
        if found:
            info = einvoice.as_json(found)
        if content_type != "application/pdf":
            content_type = "application/xml"
    name = upload.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
    receipt = Receipt(
        organization=org,
        booking=booking,
        name=name,
        content_type=content_type,
        size=upload.size,
        uploaded_by=user,
        einvoice=info,
    )
    receipt.file.save(_safe_name(name), upload, save=False)
    receipt.save()
    record(
        org,
        user,
        "create",
        receipt,
        {"Beleg": [None, f"{name} zu Buchung {booking.display_number}"]},
    )
    return receipt


# Versehentlich hochgeladene Datei: nur kurz danach und nur von derselben Person löschbar
RECEIPT_DELETE_MINUTES = 15


def receipt_deletable(receipt: Receipt, user) -> bool:
    if receipt.uploaded_by_id is None or receipt.uploaded_by_id != getattr(user, "pk", None):
        return False
    if timezone.now() - receipt.created_at > datetime.timedelta(minutes=RECEIPT_DELETE_MINUTES):
        return False
    return not services.fixed_reason(receipt.booking)


def _ensure_open(org, year: int) -> None:
    try:
        services.ensure_open(org, year=year)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(" ".join(exc.messages)) from exc


def _safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)
    return keep[-80:] or "beleg"


class EInvoiceReadView(FinanceMixin, APIView):
    """POST (Datei): E-Rechnung lesen, Buchungsvorschlag liefern; nichts wird gespeichert."""

    def post(self, request, org_id: int):
        from . import einvoice

        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Bitte eine Datei wählen."})
        if upload.size > MAX_RECEIPT_BYTES:
            raise serializers.ValidationError({"file": "Die Datei ist größer als 15 MB."})
        data = upload.read()
        content_type = "application/pdf" if data.startswith(b"%PDF") else "application/xml"
        try:
            found = einvoice.read(data, content_type)
        except einvoice.EInvoiceError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
        if not found:
            raise serializers.ValidationError(
                {"file": "In dieser PDF steckt keine E-Rechnung (ZUGFeRD/Factur-X)."}
            )
        info = einvoice.as_json(found)
        number = info["number"]
        seller = info["seller"]
        return Response(
            {
                "einvoice": info,
                "suggestion": {
                    "kind": "income" if info["credit_note"] else "expense",
                    "date": info["date"],
                    "amount": info["payable"],
                    "counterparty": seller[:200],
                    "reference": number[:100],
                    "text": f"Rechnung {number} {seller}".strip()[:200],
                },
            }
        )


class ReceiptView(FinanceMixin, APIView):
    """GET: Beleg anzeigen · DELETE: Beleg entfernen."""

    def get_receipt(self, pk: int) -> Receipt:
        return get_object_or_404(Receipt, organization=self.org, pk=pk)

    def get(self, request, org_id: int, pk: int):
        receipt = self.get_receipt(pk)
        xml = receipt.content_type == "application/xml"
        if xml and request.query_params.get("ansicht") == "1" and receipt.einvoice:
            # Lesbare Ansicht der E-Rechnung; die XML-Datei bleibt das Original
            from . import einvoice

            response = HttpResponse(
                einvoice.render(receipt.einvoice, self.org.name), content_type="application/pdf"
            )
            response["Content-Disposition"] = 'inline; filename="e-rechnung-ansicht.pdf"'
            response["Cache-Control"] = "private, no-store"
            return response
        response = FileResponse(
            receipt.file.open("rb"),
            content_type=receipt.content_type,
            # XML nie im Browser darstellen (könnte Skript enthalten), nur herunterladen
            as_attachment=xml or request.query_params.get("download") == "1",
            filename=receipt.name,
        )
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        receipt = self.get_receipt(pk)
        from .models import CashReceipt

        if CashReceipt.objects.filter(Q(document=receipt) | Q(cancel_document=receipt)).exists():
            raise serializers.ValidationError(
                "Das ist das PDF einer unterschriebenen Quittung. Es bleibt erhalten."
            )
        if receipt.hidden_at:
            raise serializers.ValidationError("Der Beleg ist schon ausgeblendet.")
        if not receipt_deletable(receipt, request.user):
            # Aufbewahrungspflicht (§ 147 AO): ausblenden statt löschen, mit Grund
            reason = " ".join(str(request.data.get("reason") or "").split())
            if len(reason) < 3:
                raise serializers.ValidationError(
                    {
                        "reason": "Belege werden nicht gelöscht, nur ausgeblendet. Bitte einen "
                        "Grund angeben (z. B. „falsche Datei, richtiger Beleg folgt“)."
                    }
                )
            receipt.hidden_at = timezone.now()
            receipt.hidden_by = request.user
            receipt.hidden_reason = reason[:300]
            receipt.save(update_fields=["hidden_at", "hidden_by", "hidden_reason"])
            record(
                self.org,
                request.user,
                "update",
                receipt,
                {
                    "Beleg ausgeblendet": [
                        f"{receipt.name} zu Buchung {receipt.booking.display_number}",
                        reason[:300],
                    ]
                },
            )
            return Response(ReceiptSerializer(receipt).data)
        _ensure_open(self.org, receipt.booking.year)
        record(
            self.org,
            request.user,
            "delete",
            receipt,
            {"Beleg": [f"{receipt.name} zu Buchung {receipt.booking.display_number}", None]},
        )
        delete_on_commit(receipt.file)
        receipt.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OverviewView(FinanceMixin, APIView):
    def get(self, request, org_id: int):
        year = request.query_params.get("jahr", "")
        year = int(year) if year.isdigit() else self.org.fiscal_year_of(timezone.localdate())
        return Response(services.overview(self.org, year))


class FinanceSettingsView(FinanceMixin, APIView):
    """Einstellungen der Kasse. PATCH {tax_areas_enabled}: Verein bzw. Dachverband
    entscheidet selbst, ob Kategorien steuerlichen Bereichen zugeordnet werden."""

    def get(self, request, org_id: int):
        return Response(self.data())

    @transaction.atomic
    def patch(self, request, org_id: int):
        if "locked_until" in request.data:
            return self._lock(request)
        if any(k.startswith("datev_") for k in request.data):
            return self._datev(request)
        if "cash_counts_enabled" in request.data:
            return self._switch(request, "cash_counts_enabled", "Zählprotokoll und Kassenbericht")
        if "reserves_enabled" in request.data:
            return self._switch(request, "reserves_enabled", "Rücklagen führen")
        value = request.data.get("tax_areas_enabled")
        if not isinstance(value, bool):
            raise serializers.ValidationError({"tax_areas_enabled": "Bitte ja oder nein angeben."})
        if value != self.org.tax_areas_enabled:
            record(
                self.org,
                request.user,
                "update",
                self.org,
                {
                    "steuerliche Bereiche in der Kasse": [
                        "ja" if not value else "nein",
                        "ja" if value else "nein",
                    ]
                },
            )
            self.org.tax_areas_enabled = value
            self.org.save(update_fields=["tax_areas_enabled"])
        return Response(self.data())

    def _switch(self, request, field: str, label: str):
        value = request.data.get(field)
        if not isinstance(value, bool):
            raise serializers.ValidationError({field: "Bitte ja oder nein angeben."})
        if value != getattr(self.org, field):
            record(
                self.org,
                request.user,
                "update",
                self.org,
                {label: ["ja" if not value else "nein", "ja" if value else "nein"]},
            )
            setattr(self.org, field, value)
            self.org.save(update_fields=[field])
        return Response(self.data())

    def _datev(self, request):
        """DATEV-Export ein/aus und Stammdaten (Berater, Mandant, Sachkontenlänge)."""
        if FINANCE_EDIT not in self.org_permissions:
            raise PermissionDenied()
        org, data, changes = self.org, request.data, {}
        if "datev_enabled" in data:
            if not isinstance(data["datev_enabled"], bool):
                raise serializers.ValidationError({"datev_enabled": "Bitte ja oder nein angeben."})
        for field, size in (("datev_consultant", 7), ("datev_client", 5)):
            if field in data:
                value = str(data[field] or "").strip()
                if value and (not value.isdigit() or len(value) > size):
                    raise serializers.ValidationError(
                        {field: f"Bitte nur Ziffern (höchstens {size})."}
                    )
        if "datev_account_length" in data:
            try:
                length = int(data["datev_account_length"])
            except (TypeError, ValueError):
                length = 0
            if not 4 <= length <= 8:
                raise serializers.ValidationError(
                    {"datev_account_length": "Die Sachkontenlänge liegt zwischen 4 und 8."}
                )
        for field, label in (
            ("datev_enabled", "DATEV-Export"),
            ("datev_consultant", "DATEV Beraternummer"),
            ("datev_client", "DATEV Mandantennummer"),
            ("datev_account_length", "DATEV Sachkontenlänge"),
            ("datev_chart", "Kontenrahmen"),
        ):
            if field not in data:
                continue
            value = data[field]
            if field == "datev_account_length":
                value = int(value)
            elif field != "datev_enabled":
                value = str(value or "").strip()[:20]
            before = getattr(org, field)
            if value != before:
                changes[label] = [before, value]
                setattr(org, field, value)
        if changes:
            org.save(
                update_fields=[
                    "datev_enabled",
                    "datev_consultant",
                    "datev_client",
                    "datev_account_length",
                    "datev_chart",
                ]
            )
            record(org, request.user, "update", org, changes)
        return Response(self.data())

    def _lock(self, request):
        """Kasse bis zu einem Tag festschreiben (GoBD); lässt sich nicht zurücknehmen."""
        if FINANCE_EDIT not in self.org_permissions:
            raise PermissionDenied()
        try:
            until = datetime.date.fromisoformat(str(request.data.get("locked_until")))
        except ValueError as exc:
            raise serializers.ValidationError({"locked_until": "Bitte ein Datum angeben."}) from exc
        org = Organization.objects.select_for_update().get(pk=self.org.pk)
        before = org.finance_locked_until
        try:
            services.fix_until(org, until)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"locked_until": " ".join(exc.messages)}) from exc
        record(
            self.org,
            request.user,
            "update",
            self.org,
            {
                "Kasse festgeschrieben bis": [
                    before.strftime("%d.%m.%Y") if before else None,
                    until.strftime("%d.%m.%Y"),
                ]
            },
        )
        self.org.finance_locked_until = until
        return Response(self.data())

    def data(self):
        auto = services.auto_fix_cutoff() - datetime.timedelta(days=1)
        return {
            "locked_until": self.org.finance_locked_until,
            # Automatisch festgeschrieben: alles bis Ende des vorletzten Monats
            "auto_locked_until": auto,
            "tax_areas_enabled": self.org.tax_areas_enabled,
            "cash_counts_enabled": self.org.cash_counts_enabled,
            "reserves_enabled": self.org.reserves_enabled,
            "datev_enabled": self.org.datev_enabled,
            "datev_consultant": self.org.datev_consultant,
            "datev_client": self.org.datev_client,
            "datev_account_length": self.org.datev_account_length,
            "datev_chart": self.org.datev_chart,
            "fiscal_start_month": self.org.fiscal_start_month,
            "fiscal_start_day": self.org.fiscal_start_day,
            "current_year": self.org.fiscal_year_of(timezone.localdate()),
            "current_label": self.org.fiscal_label(self.org.fiscal_year_of(timezone.localdate())),
            "tax_areas": [{"value": v, "label": label} for v, label in TaxArea.choices],
            "can_edit": FINANCE_EDIT in self.org_permissions,
            "years": [
                {"year": y, "label": self.org.fiscal_label(y)} for y in services.years(self.org)
            ],
        }


def closing_checks(org, year: int, start, last) -> dict:
    """Zahlen für die Prüfliste vor dem Jahresabschluss (blockieren nie)."""
    from billing.models import DebitRun, Invoice

    bookings = Booking.objects.filter(organization=org, year=year).exclude(
        kind=Booking.Kind.TRANSFER
    )
    checks = {
        "bookings": bookings.count(),
        "without_receipt": bookings.exclude(
            pk__in=Receipt.objects.filter(organization=org, hidden_at__isnull=True).values(
                "booking_id"
            )
        ).count(),
        "tax_areas_enabled": org.tax_areas_enabled,
        "categories_without_area": (
            bookings.filter(category__isnull=False, category__tax_area="")
            .values("category")
            .distinct()
            .count()
            if org.tax_areas_enabled
            else 0
        ),
    }
    if "billing" in (org.enabled_modules or []):
        checks["open_invoices"] = Invoice.objects.filter(
            organization=org,
            status=Invoice.Status.OPEN,
            date__gte=start,
            date__lte=last,
        ).count()
        checks["unbooked_debit_runs"] = DebitRun.objects.filter(
            organization=org,
            status=DebitRun.Status.CREATED,
            collection_date__gte=start,
            collection_date__lte=last,
        ).count()
    return checks


class RetentionView(FinanceMixin, APIView):
    """POST {year}: nach Ablauf der Aufbewahrungsfrist Belege löschen bzw. Bücher
    anonymisieren (Finanzamt-Prüfung C6). Nur Vorstände mit Rollenverwaltung."""

    def post(self, request, org_id: int):
        if ROLES_MANAGE not in self.org_permissions:
            raise PermissionDenied("Das dürfen nur Vorstände mit Rollenverwaltung.")
        try:
            year = int(request.data.get("year"))
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({"year": "Bitte ein Geschäftsjahr angeben."}) from exc
        try:
            result = retention.purge(self.org, year, request.user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(" ".join(exc.messages)) from exc
        return Response(result)


class YearClosingView(FinanceMixin, APIView):
    """GET: Geschäftsjahre mit Abschlussstand · POST {year}: abschließen ·
    DELETE ?jahr= {reason}: Abschluss aufheben (nur mit Recht, Rollen zu verwalten); der
    alte Stand bleibt als aufgehobener Abschluss erhalten."""

    def data(self):
        closings = {c.year: c for c in YearClosing.objects.filter(organization=self.org)}
        history: dict[int, list] = {}
        for h in ReopenedClosing.objects.filter(organization=self.org):
            history.setdefault(h.year, []).append(h)
        today = timezone.localdate()
        result = []
        for y in services.years(self.org):
            start, last = self.org.fiscal_range(y)
            c = closings.get(y)
            past = history.get(y, [])
            result.append(
                {
                    "year": y,
                    "label": self.org.fiscal_label(y),
                    "end_date": last,
                    "running": last >= today,
                    "closed": c is not None,
                    "closed_at": c.closed_at if c else None,
                    "closed_by": (c.closed_by.get_full_name() or c.closed_by.email)
                    if c and c.closed_by
                    else None,
                    "checks": None if c else closing_checks(self.org, y, start, last),
                    # Frühere, aufgehobene Abschlüsse (neueste zuerst) und was sich seit dem
                    # letzten aufgehobenen Stand geändert hat
                    "reopened": [
                        {
                            "closed_at": h.closed_at,
                            "closed_by": h.closed_by_name,
                            "reopened_at": h.reopened_at,
                            "reopened_by": h.reopened_by_name,
                            "reason": h.reason,
                        }
                        for h in past
                    ],
                    "changes": services.closing_changes(past[0].snapshot, c.snapshot)
                    if c and past
                    else [],
                    # Aufbewahrungsfrist (Finanzamt-Prüfung C6)
                    "retention": retention.state(self.org, c) if c else None,
                }
            )
        return {
            "years": result,
            "can_close": FINANCE_EDIT in self.org_permissions,
            "can_reopen": FINANCE_EDIT in self.org_permissions
            and ROLES_MANAGE in self.org_permissions,
        }

    def get(self, request, org_id: int):
        return Response(self.data())

    @transaction.atomic
    def post(self, request, org_id: int):
        try:
            year = int(request.data.get("year"))
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({"year": "Bitte ein Geschäftsjahr angeben."}) from exc
        try:
            closing = services.close_year(self.org, year, request.user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(" ".join(exc.messages)) from exc
        record(
            self.org,
            request.user,
            "create",
            closing,
            {
                "Jahresabschluss": [
                    None,
                    f"Geschäftsjahr {self.org.fiscal_label(year)} abgeschlossen",
                ]
            },
        )
        return Response(self.data(), status=status.HTTP_201_CREATED)

    @transaction.atomic
    def delete(self, request, org_id: int):
        if ROLES_MANAGE not in self.org_permissions:
            raise PermissionDenied("Einen Abschluss heben nur Vorstände mit Rollenverwaltung auf.")
        year = request.query_params.get("jahr", "")
        closing = YearClosing.objects.filter(
            organization=self.org, year=int(year) if year.isdigit() else -1
        ).first()
        if closing is None:
            raise NotFound("Kein Abschluss für dieses Geschäftsjahr.")
        if closing.documents_purged_at or closing.records_purged_at:
            raise serializers.ValidationError(
                "Nach Ablauf der Aufbewahrungsfrist bereinigte Jahre bleiben abgeschlossen."
            )
        later = YearClosing.objects.filter(organization=self.org, year__gt=closing.year).exists()
        if later:
            raise serializers.ValidationError(
                "Bitte zuerst den Abschluss des Folgejahres aufheben."
            )
        label = self.org.fiscal_label(closing.year)
        # Erst protokollieren (braucht die ID), bei fehlendem Grund rollt alles zurück
        record(
            self.org,
            request.user,
            "delete",
            closing,
            {
                "Jahresabschluss": [
                    f"Geschäftsjahr {label}",
                    f"aufgehoben, Grund: {request.data.get('reason', '').strip()}",
                ]
            },
        )
        try:
            services.reopen_year(closing, request.user, request.data.get("reason", ""))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"reason": exc.messages}) from exc
        return Response(self.data())


class ExportView(FinanceMixin, APIView):
    """Datenexport für eine Prüfung (Finanzamt, Kassenprüfer) als ZIP: ?jahr="""

    def get(self, request, org_id: int):
        from . import gobd_export

        year = request.query_params.get("jahr", "")
        year = int(year) if year.isdigit() else self.org.fiscal_year_of(timezone.localdate())
        handle, name, count = gobd_export.build(self.org, year)
        record(
            self.org,
            request.user,
            "update",
            self.org,
            {
                "Datenexport Kasse": [
                    None,
                    f"Geschäftsjahr {self.org.fiscal_label(year)}, {count} Buchungen",
                ]
            },
        )
        response = FileResponse(
            handle, content_type="application/zip", as_attachment=True, filename=name
        )
        response["Cache-Control"] = "private, no-store"
        return response


class DatevExportView(FinanceMixin, APIView):
    """DATEV-Buchungsstapel (EXTF) für die Steuerberatung: ?jahr= (Geschäftsjahr)."""

    def get(self, request, org_id: int):
        from . import datev

        year = request.query_params.get("jahr", "")
        year = int(year) if year.isdigit() else self.org.fiscal_year_of(timezone.localdate())
        start, end = self.org.fiscal_range(year)
        try:
            content = datev.build(self.org, start, end, start)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(" ".join(exc.messages)) from exc
        record(
            self.org,
            request.user,
            "update",
            self.org,
            {"DATEV-Export": [None, f"Geschäftsjahr {self.org.fiscal_label(year)}"]},
        )
        name = f"EXTF_Buchungsstapel_{start:%Y%m%d}_{end:%Y%m%d}.csv"
        response = HttpResponse(content, content_type="text/csv; charset=windows-1252")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response


class CashReportView(FinanceMixin, APIView):
    """Kassenbericht als PDF: ?jahr="""

    def get(self, request, org_id: int):
        from .report import render

        year = request.query_params.get("jahr", "")
        year = int(year) if year.isdigit() else self.org.fiscal_year_of(timezone.localdate())
        response = HttpResponse(render(self.org, year), content_type="application/pdf")
        name = f"Kassenbericht-{self.org.fiscal_label(year).replace('/', '-')}.pdf"
        disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response


# --- Veranstaltungen ---


def _file_response(content: bytes, name: str, fmt: str, download: bool) -> HttpResponse:
    types = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    response = HttpResponse(content, content_type=types[fmt])
    disposition = "attachment" if download or fmt == "xlsx" else "inline"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:80] or "Auswertung"
    response["Content-Disposition"] = f'{disposition}; filename="{safe}.{fmt}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _ids(value) -> list[int]:
    if not isinstance(value, list) or not all(isinstance(v, int) for v in value):
        raise serializers.ValidationError("Bitte eine Liste von Nummern angeben.")
    return value


class ProjectSeriesViewSet(FinanceMixin, AuditMixin, viewsets.ModelViewSet):
    """Reihen wiederkehrender Veranstaltungen. Löschen lässt die Veranstaltungen stehen."""

    serializer_class = ProjectSeriesSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            ProjectSeries.objects.filter(organization=self.org)
            .annotate(project_count=Count("projects"))
            .order_by("name")
        )

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @action(detail=True, methods=["get"])
    def comparison(self, request, org_id: int, pk: int):
        from .projects import comparison

        return Response(comparison(self.get_object()))

    @action(detail=True, methods=["get"])
    def report(self, request, org_id: int, pk: int):
        from .project_report import series_pdf, series_xlsx

        series = self.get_object()
        fmt = "xlsx" if request.query_params.get("als") == "xlsx" else "pdf"
        content = series_xlsx(series) if fmt == "xlsx" else series_pdf(series)
        return _file_response(
            content,
            f"Vergleich-{series.name}",
            fmt,
            request.query_params.get("download") == "1",
        )


class ProjectViewSet(FinanceMixin, AuditMixin, viewsets.ModelViewSet):
    """Veranstaltungen mit Summen; Auswertung, Buchungen zuordnen, Termine verknüpfen."""

    serializer_class = ProjectSerializer
    pagination_class = None

    def get_queryset(self):
        qs = (
            Project.objects.filter(organization=self.org)
            .select_related("department", "series", "organization")
            .annotate(event_count=Count("events", distinct=True))
            .order_by("-starts_on", "name", "pk")
        )
        if self.action != "list":
            return qs
        p = self.request.query_params
        if (status_ := p.get("status")) in Project.Status.values:
            qs = qs.filter(status=status_)
        if (series := p.get("reihe")) and series.isdigit():
            qs = qs.filter(series_id=series)
        if (year := p.get("jahr")) and year.isdigit():
            qs = qs.filter(starts_on__year=int(year))
        if term := p.get("suche", "").strip():
            qs = qs.filter(name__icontains=term)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "org", None) is not None and self.action == "list":
            from .projects import totals

            ids = list(self.get_queryset().values_list("pk", flat=True))
            ctx["totals"] = totals(ids)
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org, "created_by": self.request.user}

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        project = self.get_object()
        reasons = []
        if n := project.bookings.count():
            reasons.append(f"{n} {'Buchung' if n == 1 else 'Buchungen'} zugeordnet")
        if hasattr(project, "invoices") and (n := project.invoices.count()):
            reasons.append(f"{n} {'Rechnung' if n == 1 else 'Rechnungen'} zugeordnet")
        if reasons:
            return Response(
                {
                    "detail": f"„{project.name}“ hat noch "
                    + " und ".join(reasons)
                    + ". Bitte die Zuordnung zuerst lösen.",
                    "reasons": reasons,
                },
                status=status.HTTP_409_CONFLICT,
            )
        self.perform_destroy(project)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def evaluation(self, request, org_id: int, pk: int):
        from .projects import evaluation

        return Response(evaluation(self.get_object()))

    @action(detail=True, methods=["get"])
    def report(self, request, org_id: int, pk: int):
        from .project_report import project_pdf, project_xlsx

        project = self.get_object()
        fmt = "xlsx" if request.query_params.get("als") == "xlsx" else "pdf"
        content = project_xlsx(project) if fmt == "xlsx" else project_pdf(project)
        return _file_response(
            content,
            f"Auswertung-{project.name}",
            fmt,
            request.query_params.get("download") == "1",
        )

    def _set_bookings(self, project: Project | None, ids: list[int], current: Project):
        bookings = Booking.objects.filter(organization=self.org, pk__in=ids).exclude(
            kind=Booking.Kind.TRANSFER
        )
        if project is None:
            bookings = bookings.filter(project=current)
        changed = 0
        for b in bookings.select_related("project", "organization"):
            if b.project_id == (project.pk if project else None):
                continue
            before = b.project.name if b.project_id else None
            b.project = project
            b.save(update_fields=["project", "updated_at"])
            record(
                self.org,
                self.request.user,
                "update",
                b,
                {"Veranstaltung": [before, project.name if project else None]},
            )
            changed += 1
        return changed

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def assign(self, request, org_id: int, pk: int):
        """{bookings: [ids]}: Buchungen der Veranstaltung zuordnen (auch aus
        abgeschlossenen Jahren, denn Beträge ändern sich dadurch nicht)."""
        project = self.get_object()
        changed = self._set_bookings(project, _ids(request.data.get("bookings")), project)
        return Response({"changed": changed})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def unassign(self, request, org_id: int, pk: int):
        project = self.get_object()
        changed = self._set_bookings(None, _ids(request.data.get("bookings")), project)
        return Response({"changed": changed})

    @action(detail=True, methods=["get"], url_path="event-candidates")
    def event_candidates(self, request, org_id: int, pk: int):
        """Termine der Organisation rund um den Zeitraum, die noch zu keiner
        anderen Veranstaltung gehören."""
        import datetime

        from events.models import Event

        project = self.get_object()
        start = project.starts_on - datetime.timedelta(days=60)
        end = (project.ends_on or project.starts_on) + datetime.timedelta(days=60)
        if term := request.query_params.get("suche", "").strip():
            qs = Event.objects.filter(organization=self.org, title__icontains=term)
        else:
            # Einzeltermine im Zeitraum und Serien, die dann noch laufen
            series_running = ~Q(repeat=Event.Repeat.NONE) & (
                Q(repeat_until__isnull=True) | Q(repeat_until__gte=start)
            )
            qs = Event.objects.filter(organization=self.org, starts_at__date__lte=end).filter(
                Q(starts_at__date__gte=start) | series_running
            )
        qs = qs.filter(Q(project__isnull=True) | Q(project=project)).order_by("starts_at")[:100]
        return Response(
            [
                {
                    "id": e.pk,
                    "title": e.title,
                    "starts_at": e.starts_at,
                    "ends_at": e.ends_at,
                    "all_day": e.all_day,
                    "is_series": e.is_series,
                    "linked": e.project_id == project.pk,
                }
                for e in qs
            ]
        )

    @action(detail=True, methods=["post"], url_path="link-events")
    @transaction.atomic
    def link_events(self, request, org_id: int, pk: int):
        """{events: [ids]} verknüpfen, {unlink: [ids]} lösen."""
        from events.models import Event

        project = self.get_object()
        link = _ids(request.data.get("events", []))
        unlink = _ids(request.data.get("unlink", []))
        for e in Event.objects.filter(organization=self.org, pk__in=link).exclude(project=project):
            if e.project_id:
                raise serializers.ValidationError(
                    f"Der Termin „{e.title}“ gehört schon zu einer anderen Veranstaltung."
                )
            e.project = project
            e.save(update_fields=["project"])
            record(self.org, request.user, "update", e, {"Veranstaltung": [None, project.name]})
        for e in Event.objects.filter(organization=self.org, pk__in=unlink, project=project):
            e.project = None
            e.save(update_fields=["project"])
            record(self.org, request.user, "update", e, {"Veranstaltung": [project.name, None]})
        from .projects import evaluation

        return Response(evaluation(project))


class StatisticsView(FinanceMixin, APIView):
    """Entwicklung über die Zeit: ?von=JJJJ-MM&bis=JJJJ-MM&raster=monat|jahr"""

    def get(self, request, org_id: int):
        return Response(statistics.statistics(self.org, request.query_params))
