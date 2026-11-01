"""API für Beiträge und Rechnungen: /api/orgs/<org_id>/billing/…"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import BILLING_EDIT, BILLING_VIEW, FINANCE_VIEW
from audit.log import diff, record, snapshot
from changes import idempotency
from core.api_base import OrgScopedMixin
from finance import services as finance_services
from finance.models import Account, Category
from members.models import Membership, MemberType
from organizations.models import Department, Organization
from organizations.terms import department_terms, fill
from outbox import mail

from . import pdf, sepa, services, units
from .archive import archived_pdf
from .models import (
    AgeRate,
    DebitItem,
    DebitRun,
    Dunning,
    DunningLevel,
    FeeRate,
    FeeRun,
    Invoice,
    InvoiceLine,
    Mandate,
    Payment,
    Rhythm,
)
from .serializers import (
    AgeRateSerializer,
    BillingSettingsSerializer,
    DebitRunSerializer,
    DunningLevelSerializer,
    FeeRunSerializer,
    InvoiceDetailSerializer,
    InvoiceInputSerializer,
    InvoiceListSerializer,
    MandateInputSerializer,
    MandateSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    RunCreateSerializer,
)


def _as_drf(exc: DjangoValidationError) -> serializers.ValidationError:
    if hasattr(exc, "message_dict"):
        return serializers.ValidationError(exc.message_dict)
    return serializers.ValidationError({"detail": " ".join(exc.messages)})


class BillingMixin(OrgScopedMixin):
    read_permission = BILLING_VIEW
    write_permission = BILLING_EDIT
    # Untereinheit mit eigenem Arbeitsbereich: Rechnungen an ihre Mitglieder,
    # ohne Beitragsläufe und Lastschrift
    allowed_org_types = (
        Organization.Type.CLUB,
        Organization.Type.FEDERATION,
        Organization.Type.UNIT,
    )
    WITHOUT_UNITS = (Organization.Type.CLUB, Organization.Type.FEDERATION)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if "billing" not in (self.org.enabled_modules or []):
            raise NotFound(gettext("Beiträge und Rechnungen sind hier nicht freigeschaltet."))

    @property
    def is_federation(self) -> bool:
        return self.org.type == Organization.Type.FEDERATION

    @property
    def is_unit(self) -> bool:
        return self.org.type == Organization.Type.UNIT

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx


# --- Einstellungen und Beitragssätze ---


class BillingSettingsView(BillingMixin, APIView):
    def data(self):
        cfg = services.settings_for(self.org)
        today = timezone.localdate()
        year = self.org.fiscal_year_of(today)
        return {
            **BillingSettingsSerializer(cfg, context={"org": self.org}).data,
            "rhythms": [{"value": v, "label": label} for v, label in Rhythm.choices],
            "accounts": [
                {"id": a.pk, "name": a.name, "kind": a.kind, "has_iban": bool(a.iban)}
                for a in Account.objects.filter(organization=self.org, is_active=True)
            ],
            "categories": [
                {"id": c.pk, "name": c.name}
                for c in Category.objects.filter(organization=self.org, is_active=True)
                if c.allows("income")
            ],
            "current_year": year,
            "years": [
                {"year": y, "label": self.org.fiscal_label(y)} for y in (year - 1, year, year + 1)
            ],
            "periods": {
                str(y): [
                    {
                        "index": p.index,
                        "label": p.label,
                        "start": p.start,
                        "end": p.end,
                    }
                    for p in services.periods(self.org, y, cfg.rhythm)
                ]
                for y in (year - 1, year, year + 1)
            },
            "org_type": self.org.type,
            "department_label": self.org.department_label,
            "department_label_plural": self.org.department_label_plural,
            "department_terms": department_terms(self.org),
            "clubs": [
                {"id": c.pk, "name": c.display_name}
                for c in Organization.objects.filter(
                    parent=self.org, type=Organization.Type.CLUB, is_active=True
                ).order_by("name")
            ]
            if self.is_federation
            else [],
            # Für alle Einheiten gleich: wer Rechnungen bekommen kann
            "keeps_members": self.is_unit or self.org.keeps_members,
            "units": self._units(),
            "can_edit": BILLING_EDIT in self.org_permissions,
        }

    def _units(self) -> list[dict]:
        """Untereinheiten, an die Rechnungen gehen können."""
        if self.is_unit:
            return []
        if self.is_federation:
            qs = Organization.objects.filter(
                parent=self.org, type=Organization.Type.CLUB, is_active=True
            ).order_by("name")
            return [{"id": u.pk, "name": u.display_name} for u in qs]
        from organizations.tree import UnitTree

        tree = UnitTree.of(self.org.pk)
        by_id = {u.pk: u for u in Department.objects.filter(organization=self.org, is_active=True)}
        return [
            {"id": pk, "name": tree.path(pk) if tree.depth(pk) else by_id[pk].display_name}
            for pk in tree.ordered()
            if pk in by_id
        ]

    def get(self, request, org_id: int):
        return Response(self.data())

    @transaction.atomic
    def patch(self, request, org_id: int):
        cfg = services.settings_for(self.org)
        before = snapshot(cfg)
        ser = BillingSettingsSerializer(
            cfg, data=request.data, partial=True, context={"org": self.org}
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        changes = diff(before, snapshot(cfg))
        if changes:
            record(self.org, request.user, "update", cfg, changes)
        return Response(self.data())


class BillingMembersView(BillingMixin, APIView):
    """Mitglieder einer Untereinheit als Rechnungsempfänger (Suche)."""

    allowed_org_types = (Organization.Type.UNIT,)

    def get(self, request, org_id: int):
        term = str(request.query_params.get("suche", "")).strip()
        if len(term) < 2:
            return Response([])
        return Response(units.search_members(self.org, term))


class FeeRatesView(BillingMixin, APIView):
    """Jahresbeitrag je Mitgliedsart: GET Liste, PUT [{member_type, amount|null}]."""

    allowed_org_types = (Organization.Type.CLUB,)

    def data(self):
        rates = {r.member_type_id: r.amount for r in FeeRate.objects.filter(organization=self.org)}
        return [
            {
                "member_type": t.pk,
                "name": t.name,
                "active": t.active,
                "amount": f"{rates[t.pk]:.2f}" if t.pk in rates else None,
            }
            for t in MemberType.objects.filter(organization=self.org, is_archived=False).order_by(
                "sort_order", "name"
            )
        ]

    def get(self, request, org_id: int):
        return Response(self.data())

    @transaction.atomic
    def put(self, request, org_id: int):
        items = request.data if isinstance(request.data, list) else []
        types = {t.pk: t for t in MemberType.objects.filter(organization=self.org)}
        for item in items:
            mt = types.get(item.get("member_type"))
            if mt is None:
                raise serializers.ValidationError(gettext("Unbekannte Mitgliedsart."))
            amount = item.get("amount")
            existing = FeeRate.objects.filter(member_type=mt).first()
            if amount in (None, ""):
                if existing:
                    record(
                        self.org,
                        request.user,
                        "delete",
                        existing,
                        {f"Beitrag {mt.name}": [f"{existing.amount:.2f}", None]},
                    )
                    existing.delete()
                continue
            field = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
            try:
                value = field.to_internal_value(amount)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({str(mt.pk): exc.detail}) from exc
            if existing is None:
                rate = FeeRate.objects.create(organization=self.org, member_type=mt, amount=value)
                record(
                    self.org,
                    request.user,
                    "create",
                    rate,
                    {f"Beitrag {mt.name}": [None, f"{value:.2f}"]},
                )
            elif existing.amount != value:
                record(
                    self.org,
                    request.user,
                    "update",
                    existing,
                    {f"Beitrag {mt.name}": [f"{existing.amount:.2f}", f"{value:.2f}"]},
                )
                existing.amount = value
                existing.save(update_fields=["amount"])
        return Response(self.data())


class AgeRateViewSet(BillingMixin, viewsets.ModelViewSet):
    allowed_org_types = BillingMixin.WITHOUT_UNITS
    serializer_class = AgeRateSerializer
    pagination_class = None

    def get_queryset(self):
        return AgeRate.objects.filter(organization=self.org).select_related("member_type")

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save(organization=self.org)
        record(self.org, self.request.user, "create", obj, diff({}, snapshot(obj)))

    @transaction.atomic
    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        obj = serializer.save()
        record(self.org, self.request.user, "update", obj, diff(before, snapshot(obj)))

    @transaction.atomic
    def perform_destroy(self, instance):
        record(self.org, self.request.user, "delete", instance, diff(snapshot(instance), {}))
        instance.delete()


# --- Versand ---


def send_invoice(invoice: Invoice) -> bool:
    if not invoice.recipient_email or invoice.status != Invoice.Status.OPEN:
        return False
    org = invoice.organization
    body = (
        f"Guten Tag,\n\n"
        f"anbei erhalten Sie die Rechnung {invoice.display_number} von {org.name} "
        f"über {pdf.euro(invoice.outstanding)}, zahlbar bis {invoice.due_date:%d.%m.%Y}.\n\n"
        f"Betreff: {invoice.subject}\n\n"
    )
    if invoice.recipient_kind == Invoice.Recipient.MEMBER and org.member_portal_enabled:
        body += (
            f"Im Mitgliederbereich sehen Sie Ihre Rechnungen jederzeit: {settings.FRONTEND_URL}\n\n"
        )
    body += f"Viele Grüße\n{org.name}\n"
    sent = mail.send(
        invoice.recipient_email,
        f"Rechnung {invoice.display_number} – {org.name}",
        body,
        organization=org,
        kind="rechnung",
        attachments=[(pdf.filename(invoice), archived_pdf(invoice), "application/pdf")],
        reply_to=[org.contact_email] if org.contact_email else None,
        fail_silently=True,
    )
    if sent:
        invoice.sent_at = timezone.now()
        invoice.save(update_fields=["sent_at", "updated_at"])
    return sent


def pdf_response(invoices: list[Invoice], name: str, download: bool) -> HttpResponse:
    response = HttpResponse(pdf.render(invoices), content_type="application/pdf")
    disposition = "attachment" if download else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{name}"'
    response["Cache-Control"] = "private, no-store"
    return response


def invoice_pdf_response(invoice: Invoice, download: bool) -> HttpResponse:
    """Eine Rechnung als PDF, in der ausgegebenen Fassung (siehe billing/archive.py)."""
    response = HttpResponse(archived_pdf(invoice), content_type="application/pdf")
    disposition = "attachment" if download else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{pdf.filename(invoice)}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _invoice_qs(org):
    return Invoice.objects.filter(organization=org).select_related(
        "organization", "department", "club", "run", "membership__person", "project"
    )


# --- Beitragsläufe ---


class FeeRunViewSet(BillingMixin, viewsets.ReadOnlyModelViewSet):
    allowed_org_types = BillingMixin.WITHOUT_UNITS
    serializer_class = FeeRunSerializer
    pagination_class = None

    def get_queryset(self):
        return FeeRun.objects.filter(organization=self.org)

    def _detail(self, run: FeeRun, extra: dict | None = None) -> dict:
        return {**FeeRunSerializer(run).data, "summary": services.run_summary(run), **(extra or {})}

    def list(self, request, *args, **kwargs):
        return Response([self._detail(r) for r in self.get_queryset()])

    def retrieve(self, request, *args, **kwargs):
        return Response(self._detail(self.get_object()))

    def _period(self, data):
        cfg = services.settings_for(self.org)
        try:
            return services.period(self.org, data["year"], cfg.rhythm, data["period"])
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc

    @action(detail=False, methods=["post"])
    def preview(self, request, org_id: int):
        ser = RunCreateSerializer(data={"invoice_date": timezone.localdate(), **request.data})
        ser.is_valid(raise_exception=True)
        p = self._period(ser.validated_data)
        exists = FeeRun.objects.filter(
            organization=self.org, start_date=p.start, end_date=p.end
        ).exists()
        if self.is_federation:
            items = services.plan_federation_run(self.org, p)
            return Response(
                finance_services._money(
                    {
                        "label": p.label,
                        "start": p.start,
                        "end": p.end,
                        "exists": exists,
                        "clubs": [
                            {
                                "id": i.club.pk,
                                "name": i.club.display_name,
                                "members": i.members,
                                "total": i.total,
                            }
                            for i in items
                        ],
                        "clubs_total": sum((i.total for i in items), services.ZERO),
                    }
                )
            )
        plan = services.plan_run(self.org, p)
        dept_total = {
            d: sum((i.amount for i in items), services.ZERO)
            for d, items in plan.department_items.items()
        }
        return Response(
            finance_services._money(
                {
                    "label": p.label,
                    "start": p.start,
                    "end": p.end,
                    "exists": exists,
                    "members": len(plan.member_items),
                    "members_total": sum((i.amount for i in plan.member_items), services.ZERO),
                    "departments": [
                        {
                            "id": d,
                            "name": plan.departments[d].display_name,
                            "members": len(items),
                            "total": dept_total[d],
                        }
                        for d, items in plan.department_items.items()
                    ],
                    "skipped": plan.skipped,
                    "checks": services.preview_checks(self.org, plan),
                }
            )
        )

    @transaction.atomic
    def create(self, request, org_id: int):
        ser = RunCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        p = self._period(data)
        if FeeRun.objects.filter(
            organization=self.org, start_date=p.start, end_date=p.end
        ).exists():
            raise serializers.ValidationError(
                {
                    "period": gettext("Für {label} gibt es schon einen Beitragslauf.").format(
                        label=p.label
                    )
                }
            )
        cfg = services.settings_for(self.org)
        due = data.get("due_date") or data["invoice_date"] + datetime.timedelta(days=cfg.due_days)
        if due < data["invoice_date"]:
            raise serializers.ValidationError(
                {"due_date": gettext("Fällig vor dem Rechnungsdatum?")}
            )
        run = FeeRun.objects.create(
            organization=self.org,
            year=p.year,
            rhythm=p.rhythm,
            period=p.index,
            start_date=p.start,
            end_date=p.end,
            label=p.label,
            invoice_date=data["invoice_date"],
            due_date=due,
            created_by=request.user,
        )
        result = services.build_run(run, request.user)
        record(
            self.org,
            request.user,
            "create",
            run,
            {"Beitragslauf": [None, f"{p.label}: {result['created']} Rechnungsentwürfe"]},
        )
        return Response(self._detail(run, result), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def rebuild(self, request, org_id: int, pk: int):
        """Entwürfe neu berechnen; Mitglieder ohne festgeschriebene Rechnung kommen dazu."""
        run = self.get_object()
        services.lock_run(run)
        edited = services.edited_drafts(run)
        if edited and request.query_params.get("bestaetigt") != "1":
            # Neu berechnen verwirft Handänderungen an Entwürfen: erst nachfragen
            return Response(
                {
                    "detail": gettext(
                        "{edited} Entwürfe wurden von Hand geändert. Neu berechnen verwirft "
                        "diese Änderungen."
                    ).format(edited=edited),
                    "edited": edited,
                },
                status=status.HTTP_409_CONFLICT,
            )
        result = services.build_run(run, request.user)
        return Response(self._detail(run, result))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def finalize(self, request, org_id: int, pk: int):
        run = self.get_object()
        services.lock_run(run)
        drafts = list(
            _invoice_qs(self.org)
            .filter(run=run, status=Invoice.Status.DRAFT)
            .order_by("recipient_kind", "recipient_name", "pk")
        )
        for invoice in drafts:
            try:
                services.finalize(invoice)
            except DjangoValidationError as exc:
                raise _as_drf(exc) from exc
        if drafts:
            record(
                self.org,
                request.user,
                "update",
                run,
                {"Beitragslauf": [None, f"{run.label}: {len(drafts)} Rechnungen festgeschrieben"]},
            )
        return Response(self._detail(run, {"finalized": len(drafts)}))

    @action(detail=True, methods=["post"])
    def send(self, request, org_id: int, pk: int):
        run = self.get_object()
        invoices = (
            _invoice_qs(self.org)
            .filter(run=run, status=Invoice.Status.OPEN, sent_at__isnull=True)
            .exclude(recipient_email="")
        )
        sent = failed = 0
        for invoice in invoices:
            with transaction.atomic():
                if send_invoice(invoice):
                    sent += 1
                else:
                    failed += 1
        if sent:
            record(
                self.org,
                request.user,
                "update",
                run,
                {"Beitragslauf": [None, f"{run.label}: {sent} Rechnungen per E-Mail verschickt"]},
            )
        return Response(self._detail(run, {"sent": sent, "failed": failed}))

    @action(detail=True, methods=["post"], url_path="postversand")
    def post_done(self, request, org_id: int, pk: int):
        """Postversand der Rechnungen ohne E-Mail als erledigt vermerken oder zurücknehmen."""
        run = self.get_object()
        done = bool(request.data.get("done", True))
        before = run.post_done_at
        run.post_done_at = timezone.localdate() if done else None
        run.save(update_fields=["post_done_at"])
        record(
            self.org,
            request.user,
            "update",
            run,
            {"Postversand erledigt": [str(before or ""), str(run.post_done_at or "")]},
        )
        return Response(self._detail(run))

    @action(detail=True, methods=["get"])
    def pdf(self, request, org_id: int, pk: int):
        run = self.get_object()
        qs = _invoice_qs(self.org).filter(run=run).exclude(status=Invoice.Status.CANCELLED)
        which = request.query_params.get("nur", "")
        if which == "ohne_email":
            qs = qs.filter(recipient_email="")
        if which == "entwuerfe":
            qs = qs.filter(status=Invoice.Status.DRAFT)
        else:
            qs = qs.exclude(status=Invoice.Status.DRAFT) if which else qs
        invoices = list(qs.order_by("recipient_kind", "recipient_name", "pk"))
        return pdf_response(invoices, f"Beitragslauf-{run.pk}.pdf", download=True)

    @transaction.atomic
    def destroy(self, request, org_id: int, pk: int):
        run = self.get_object()
        if run.invoices.exclude(status=Invoice.Status.DRAFT).exists():
            raise serializers.ValidationError(
                gettext(
                    "Der Lauf hat schon festgeschriebene Rechnungen. Diese bitte einzeln "
                    "stornieren."
                )
            )
        record(self.org, request.user, "delete", run, {"Beitragslauf": [run.label, None]})
        run.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Rechnungen ---


class InvoicePagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


class InvoiceViewSet(BillingMixin, viewsets.ModelViewSet):
    pagination_class = InvoicePagination
    http_method_names = ["get", "post", "patch", "delete"]

    def get_serializer_class(self):
        return InvoiceListSerializer if self.action == "list" else InvoiceDetailSerializer

    def get_queryset(self):
        qs = _invoice_qs(self.org)
        if self.action != "list":
            return qs.prefetch_related(
                "lines__membership__person",
                "payments__booking__account",
                "payments__booking",
                "dunnings",
            )
        p = self.request.query_params
        if (s := p.get("status")) in Invoice.Status.values:
            qs = qs.filter(status=s)
        if p.get("offen") in ("1", "true"):
            qs = qs.filter(status=Invoice.Status.OPEN)
        if p.get("ueberfaellig") in ("1", "true"):
            qs = qs.filter(status=Invoice.Status.OPEN, due_date__lt=timezone.localdate())
        if (run := p.get("lauf")) and run.isdigit():
            qs = qs.filter(run_id=run)
        if (year := p.get("jahr")) and year.isdigit():
            qs = qs.filter(Q(year=int(year)) | Q(year__isnull=True, run__year=int(year)))
        if (m := p.get("mitglied")) and m.isdigit():
            qs = qs.filter(Q(membership_id=m) | Q(lines__membership_id=m)).distinct()
        if (d := p.get("abteilung")) and d.isdigit():
            qs = qs.filter(department_id=d)
        if (c := p.get("verein")) and c.isdigit():
            qs = qs.filter(club_id=c)
        if (v := p.get("veranstaltung")) and v.isdigit():
            qs = qs.filter(project_id=v)
        if p.get("gemahnt") in ("1", "true"):
            qs = qs.filter(dunning_level__gt=0)
        if term := p.get("suche", "").strip():
            q = Q(recipient_name__icontains=term) | Q(subject__icontains=term)
            if term.upper().startswith("R") and "-" in term:
                try:
                    q |= Q(number=int(term.rsplit("-", 1)[1]))
                except ValueError:
                    pass
            qs = qs.filter(q)
        return qs.order_by("-date", "-number", "-pk")

    def _recipient(self, data, invoice: Invoice | None) -> dict:
        """Empfänger: ein Mitglied oder eine direkte Untereinheit.

        Für alle Einheiten gleich: „unit“ ist eine Untereinheit, technisch wird sie
        zu ``club`` (Einheit mit eigenen Mitgliedern) oder ``department``. Die alten
        Angaben ``club``/``department`` gelten weiter.
        """
        kind = data.get("recipient_kind") or (invoice.recipient_kind if invoice else None)
        empty = {"membership": None, "department": None, "club": None}
        if kind == Invoice.Recipient.MEMBER:
            if not (self.is_unit or self.org.keeps_members):
                raise serializers.ValidationError(
                    {"recipient_kind": gettext("Hier gibt es keine eigenen Mitglieder.")}
                )
            mid = data.get("membership") or (invoice.membership_id if invoice else None)
            if self.is_unit:
                membership = units.member_of(self.org, mid)
            else:
                membership = Membership.objects.filter(organization=self.org, pk=mid or 0).first()
            if membership is None:
                raise serializers.ValidationError(
                    {"membership": gettext("Bitte ein Mitglied wählen.")}
                )
            return {**empty, "recipient_kind": kind, "membership": membership}
        if self.is_unit:
            raise serializers.ValidationError(
                {"recipient_kind": gettext("Hier gehen Rechnungen nur an Mitglieder.")}
            )
        if kind is None and not self.is_federation:
            raise serializers.ValidationError(
                {"recipient_kind": gettext("Bitte den Empfänger wählen.")}
            )
        field = "unit" if data.get("unit") is not None or kind == "unit" else None
        if self.is_federation:
            field = field or "club"
            cid = data.get(field) or (invoice.club_id if invoice else None)
            club = Organization.objects.filter(
                parent=self.org, type=Organization.Type.CLUB, pk=cid or 0
            ).first()
            if club is None:
                raise serializers.ValidationError({field: fill("Bitte {einen} wählen.", self.org)})
            return {**empty, "recipient_kind": Invoice.Recipient.CLUB, "club": club}
        if kind not in ("unit", Invoice.Recipient.DEPARTMENT):
            raise serializers.ValidationError(
                {"recipient_kind": gettext("Bitte den Empfänger wählen.")}
            )
        field = field or "department"
        did = data.get(field) or (invoice.department_id if invoice else None)
        dept = Department.objects.filter(organization=self.org, pk=did or 0).first()
        if dept is None:
            raise serializers.ValidationError({field: fill("Bitte {einen} wählen.", self.org)})
        return {**empty, "recipient_kind": Invoice.Recipient.DEPARTMENT, "department": dept}

    def _set_project(self, invoice: Invoice, project_id) -> None:
        """Veranstaltung setzen; Buchungen bisheriger Zahlungen ziehen mit."""
        from finance.models import Project

        project = None
        if project_id:
            project = Project.objects.filter(organization=self.org, pk=project_id).first()
            if project is None:
                raise serializers.ValidationError({"project": gettext("Unbekannte Veranstaltung.")})
        if invoice.pk and invoice.project_id != (project.pk if project else None):
            from finance.models import Booking

            Booking.objects.filter(
                organization=self.org,
                payment__invoice=invoice,
                project_id=invoice.project_id,
            ).update(project=project)
        invoice.project = project

    def _save(self, invoice: Invoice, data: dict) -> Invoice:
        for key, value in self._recipient(data, invoice if invoice.pk else None).items():
            setattr(invoice, key, value)
        for key in ("date", "due_date", "subject", "note"):
            if key in data:
                setattr(invoice, key, data[key])
        if "project" in data:
            self._set_project(invoice, data["project"])
        if invoice.due_date < invoice.date:
            raise serializers.ValidationError(
                {"due_date": gettext("Fällig vor dem Rechnungsdatum?")}
            )
        services.refresh_recipient(invoice)
        invoice.save()
        if "lines" in data:
            self._save_lines(invoice, data["lines"])
        services.recalc_total(invoice)
        invoice.save(update_fields=["total", "updated_at"])
        return invoice

    def _save_lines(self, invoice: Invoice, lines: list) -> None:
        """Posten unter ihrer ID aktualisieren, neue anlegen, fehlende löschen.

        Beitragsposten aus dem Beitragslauf behalten so ihre Herkunft (Mitglied, Beitrag),
        sonst rechnete ein erneuter Lauf das Mitglied noch einmal ab. Wird dieselbe
        Änderung wiederholt (z. B. nach Verbindungsabbruch), passt sie unverändert.
        Unbekannte IDs (veralteter Stand) werden abgewiesen statt neu angelegt.
        """
        vat_on = services.settings_for(self.org).vat_enabled
        existing = {line.pk: line for line in invoice.lines.all()}
        sent_ids = [line.get("id") for line in lines if line.get("id")]
        unknown = [i for i in sent_ids if i not in existing]
        if unknown or len(sent_ids) != len(set(sent_ids)):
            raise serializers.ValidationError(
                {
                    "lines": gettext(
                        "Die Posten wurden inzwischen geändert. Bitte die Rechnung neu laden."
                    )
                }
            )
        keep = set(sent_ids)
        invoice.lines.exclude(pk__in=keep).delete()
        for n, line in enumerate(lines):
            vat_rate = (line.get("vat_rate") or None) if vat_on else None
            prev = existing.get(line.get("id") or 0)
            if prev is not None:
                prev.position = n
                prev.text = line["text"]
                prev.detail = line.get("detail", "")
                prev.amount = line["amount"]
                prev.vat_rate = vat_rate
                if not prev.is_fee:
                    prev.membership = invoice.membership
                prev.save()
            else:
                InvoiceLine.objects.create(
                    organization=self.org,
                    invoice=invoice,
                    position=n,
                    text=line["text"],
                    detail=line.get("detail", ""),
                    amount=line["amount"],
                    vat_rate=vat_rate,
                    membership=invoice.membership,
                    is_fee=False,
                )

    @transaction.atomic
    def create(self, request, org_id: int):
        ser = InvoiceInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if "lines" not in data:
            raise serializers.ValidationError(
                {"lines": gettext("Bitte mindestens einen Posten angeben.")}
            )
        claim = idempotency.claim(request, f"billing.invoice.new.{self.org.pk}")
        if claim.done:
            invoice = get_object_or_404(self.get_queryset(), pk=claim.result.get("invoice", 0))
            return Response(InvoiceDetailSerializer(invoice).data, status=status.HTTP_200_OK)
        today = timezone.localdate()
        cfg = services.settings_for(self.org)
        date = data.get("date") or today
        invoice = Invoice(
            organization=self.org,
            date=date,
            due_date=data.get("due_date") or date + datetime.timedelta(days=cfg.due_days),
            subject=data.get("subject") or "Rechnung",
            created_by=request.user,
        )
        self._save(invoice, data)
        claim.remember({"invoice": invoice.pk})
        record(
            self.org,
            request.user,
            "create",
            invoice,
            {"Rechnung": [None, f"Entwurf für {invoice.recipient_name.splitlines()[0]}"]},
        )
        return Response(
            InvoiceDetailSerializer(self.get_queryset().get(pk=invoice.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    def _locked_object(self) -> Invoice:
        """Rechnung sperren und frisch lesen: Zahlung, Festschreiben oder Lastschrift
        dazwischen werden nicht mit einem veralteten Stand überschrieben."""
        invoice = self.get_object()
        services.lock_invoice(invoice, fields=None)
        return invoice

    @transaction.atomic
    def partial_update(self, request, org_id: int, pk: int):
        invoice = self._locked_object()
        # Dieselbe Änderung erneut gesendet (Wiederholung nach Verbindungsabbruch)
        claim = idempotency.claim(request, f"billing.invoice.{invoice.pk}")
        if claim.done:
            return self._detail(invoice)
        ser = InvoiceInputSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if invoice.status != Invoice.Status.DRAFT:
            # Festgeschrieben: nur noch Hinweis, Fälligkeit und Veranstaltung änderbar
            allowed = {"note", "due_date", "project"}
            if set(data) - allowed:
                raise serializers.ValidationError(
                    gettext(
                        "Festgeschriebene Rechnungen lassen sich nicht mehr ändern. Bitte "
                        "stornieren und neu anlegen."
                    )
                )
            before = snapshot(invoice)
            if "project" in data:
                self._set_project(invoice, data.pop("project"))
            for key, value in data.items():
                setattr(invoice, key, value)
            if invoice.due_date < invoice.date:
                raise serializers.ValidationError(
                    {"due_date": gettext("Fällig vor dem Rechnungsdatum?")}
                )
            invoice.save(update_fields=[*data, "project", "updated_at"])
            record(self.org, request.user, "update", invoice, diff(before, snapshot(invoice)))
        else:
            self._save(invoice, data)
        claim.remember({"invoice": invoice.pk})
        return self._detail(invoice)

    @transaction.atomic
    def destroy(self, request, org_id: int, pk: int):
        invoice = self._locked_object()
        if invoice.status != Invoice.Status.DRAFT:
            raise serializers.ValidationError(
                gettext(
                    "Nur Entwürfe lassen sich löschen. Festgeschriebene Rechnungen bitte "
                    "stornieren."
                )
            )
        record(
            self.org,
            request.user,
            "delete",
            invoice,
            {"Rechnung": [f"Entwurf für {invoice.recipient_name.splitlines()[0]}", None]},
        )
        invoice.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _detail(self, invoice):
        return Response(InvoiceDetailSerializer(self.get_queryset().get(pk=invoice.pk)).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def finalize(self, request, org_id: int, pk: int):
        invoice = self.get_object()
        try:
            services.finalize(invoice)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            invoice,
            {"Rechnung": ["Entwurf", f"{invoice.display_number} festgeschrieben"]},
        )
        return self._detail(invoice)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, org_id: int, pk: int):
        invoice = self.get_object()
        try:
            services.cancel(invoice)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            invoice,
            {"Rechnung": [invoice.display_number, "storniert"]},
        )
        return self._detail(invoice)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def send(self, request, org_id: int, pk: int):
        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            raise serializers.ValidationError(
                gettext("Verschicken lassen sich nur offene Rechnungen.")
            )
        if not invoice.recipient_email:
            raise serializers.ValidationError(
                gettext("Für den Empfänger ist keine E-Mail-Adresse bekannt.")
            )
        if not send_invoice(invoice):
            raise serializers.ValidationError(gettext("Die E-Mail konnte nicht verschickt werden."))
        record(
            self.org,
            request.user,
            "update",
            invoice,
            {
                "Rechnung": [
                    None,
                    f"{invoice.display_number} an {invoice.recipient_email} verschickt",
                ]
            },
        )
        return self._detail(invoice)

    @extend_schema(responses={(200, "*/*"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request, org_id: int, pk: int):
        invoice = self.get_object()
        return invoice_pdf_response(invoice, request.query_params.get("download") == "1")

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def payments(self, request, org_id: int, pk: int):
        invoice = self.get_object()
        ser = PaymentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # Dieselbe Zahlung erneut gesendet (Doppelklick, Wiederholung): nicht noch einmal buchen
        claim = idempotency.claim(request, f"billing.payment.{invoice.pk}", required=True)
        if claim.done:
            return self._detail(invoice)
        # Ohne Betrag: der offene Rest. Eine ausdrückliche 0 bleibt 0 (und wird abgelehnt).
        amount = data.get("amount")
        try:
            payment = services.add_payment(
                invoice,
                date=data["date"],
                amount=invoice.outstanding if amount is None else amount,
                method=data["method"],
                account=data["account"],
                user=request.user,
            )
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "create",
            payment,
            {
                "Zahlung": [
                    None,
                    f"{pdf.euro(payment.amount)} zu {invoice.display_number} "
                    f"({payment.get_method_display()}, Buchung {payment.booking.display_number})",
                ]
            },
        )
        claim.remember({"payment": payment.pk})
        return self._detail(invoice)


class PaymentView(BillingMixin, APIView):
    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        payment = get_object_or_404(
            Payment.objects.select_related("invoice__organization", "booking__organization"),
            organization=self.org,
            pk=pk,
        )
        invoice = payment.invoice
        record(
            self.org,
            request.user,
            "delete",
            payment,
            {
                "Zahlung": [
                    f"{pdf.euro(payment.amount)} zu {invoice.display_number} "
                    f"(Buchung {payment.booking.display_number})",
                    None,
                ]
            },
        )
        try:
            counter = services.remove_payment(payment, request.user)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        if counter is not None:
            record(
                self.org,
                request.user,
                "create",
                counter,
                {
                    "Storno": [
                        None,
                        f"{counter.cancels.display_number} storniert durch "
                        f"{counter.display_number}: {counter.cancel_reason}",
                    ]
                },
            )
        return Response(PaymentSerializer(many=True).to_representation([]))


class PaymentReceiptView(BillingMixin, APIView):
    """Quittung über eine Zahlung als PDF (``?download=1`` zum Speichern)."""

    def get(self, request, org_id: int, pk: int):
        payment = get_object_or_404(
            Payment.objects.select_related("invoice__organization", "booking", "created_by"),
            organization=self.org,
            pk=pk,
        )
        signed = getattr(payment, "cash_receipt", None)
        if signed is not None and signed.document_id:
            # Mit Unterschrift quittiert: das gespeicherte PDF (konzepte/digitale-quittung.md)
            from finance import quittung

            content, name = quittung.document_bytes(signed)
            response = HttpResponse(content, content_type="application/pdf")
            disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
            response["Content-Disposition"] = f'{disposition}; filename="{name}"'
            response["Cache-Control"] = "private, no-store"
            return response
        response = HttpResponse(pdf.render_receipt(payment), content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
        response["Content-Disposition"] = (
            f'{disposition}; filename="{pdf.receipt_filename(payment)}"'
        )
        response["Cache-Control"] = "private, no-store"
        return response


# --- Mahnungen ---


class DunningLevelViewSet(BillingMixin, viewsets.ModelViewSet):
    serializer_class = DunningLevelSerializer
    pagination_class = None

    def get_queryset(self):
        return DunningLevel.objects.filter(organization=self.org).order_by("level")

    def _check_level(self, serializer):
        level = serializer.validated_data.get("level")
        qs = self.get_queryset().filter(level=level)
        if serializer.instance is not None:
            qs = qs.exclude(pk=serializer.instance.pk)
        if level is not None and qs.exists():
            raise serializers.ValidationError({"level": gettext("Diese Stufe gibt es schon.")})

    @transaction.atomic
    def perform_create(self, serializer):
        self._check_level(serializer)
        obj = serializer.save(organization=self.org)
        record(self.org, self.request.user, "create", obj, diff({}, snapshot(obj)))

    @transaction.atomic
    def perform_update(self, serializer):
        self._check_level(serializer)
        before = snapshot(serializer.instance)
        obj = serializer.save()
        record(self.org, self.request.user, "update", obj, diff(before, snapshot(obj)))

    @transaction.atomic
    def perform_destroy(self, instance):
        record(self.org, self.request.user, "delete", instance, diff(snapshot(instance), {}))
        instance.delete()


def send_dunning(dunning: Dunning) -> bool:
    invoice = dunning.invoice
    if not invoice.recipient_email:
        return False
    org = invoice.organization
    body = (
        f"Guten Tag,\n\n"
        f"zu der Rechnung {invoice.display_number} vom {invoice.date:%d.%m.%Y} "
        f"ist noch ein Betrag von {pdf.euro(invoice.outstanding)} offen. "
        f"Bitte überweisen Sie ihn bis zum {dunning.due_date:%d.%m.%Y}.\n\n"
        f"Die Einzelheiten stehen im angehängten Schreiben ({dunning.name}). "
        f"Falls Sie inzwischen bezahlt haben, betrachten Sie diese Nachricht bitte "
        f"als gegenstandslos.\n\n"
        f"Viele Grüße\n{org.name}\n"
    )
    sent = mail.send(
        invoice.recipient_email,
        f"{dunning.name}: Rechnung {invoice.display_number} – {org.name}",
        body,
        organization=org,
        kind="mahnung",
        attachments=[
            (
                pdf.dunning_filename(dunning),
                pdf.render([invoice], {invoice.pk: dunning}),
                "application/pdf",
            )
        ],
        reply_to=[org.contact_email] if org.contact_email else None,
        fail_silently=True,
    )
    if sent:
        dunning.sent_at = timezone.now()
        dunning.save(update_fields=["sent_at"])
    return sent


class DunningsView(BillingMixin, APIView):
    """GET: fällige Mahnungen (Vorschläge). POST {invoices: [ids], send: bool}: mahnen."""

    def _proposals(self):
        return services.dunning_proposals(self.org)

    def get(self, request, org_id: int):
        levels = DunningLevelSerializer(
            DunningLevel.objects.filter(organization=self.org).order_by("level"), many=True
        ).data
        today = timezone.localdate()
        return Response(
            {
                "levels": levels,
                "proposals": [
                    {
                        **InvoiceListSerializer(invoice).data,
                        "days_overdue": (today - invoice.due_date).days,
                        "next_level": lv.level,
                        "next_level_name": lv.name,
                        "fee": f"{lv.fee:.2f}",
                    }
                    for invoice, lv in self._proposals()
                ],
            }
        )

    def post(self, request, org_id: int):
        ids = {int(i) for i in request.data.get("invoices", []) if str(i).isdigit()}
        send = bool(request.data.get("send", True))
        proposals = [(i, lv) for i, lv in self._proposals() if i.pk in ids]
        if not proposals:
            raise serializers.ValidationError(
                gettext("Bitte mindestens eine fällige Rechnung auswählen.")
            )
        created: list[Dunning] = []
        sent = 0
        for invoice, level in proposals:
            with transaction.atomic():
                try:
                    dunning = services.dun(invoice, level, request.user)
                except DjangoValidationError as exc:
                    raise _as_drf(exc) from exc
                record(
                    self.org,
                    request.user,
                    "create",
                    dunning,
                    {"Mahnung": [None, f"{level.name} zu {invoice.display_number}"]},
                )
                created.append(dunning)
            if send and send_dunning(dunning):
                sent += 1
        unsent = [d.pk for d in created if d.sent_at is None]
        return Response(
            {"created": len(created), "sent": sent, "unsent": unsent},
            status=status.HTTP_201_CREATED,
        )


class DunningPdfView(BillingMixin, APIView):
    """Mahnschreiben als PDF: /dunnings/pdf/?ids=1,2,3"""

    def get(self, request, org_id: int):
        ids = [int(i) for i in request.query_params.get("ids", "").split(",") if i.isdigit()]
        dunnings = list(
            Dunning.objects.filter(organization=self.org, pk__in=ids)
            .select_related("invoice__organization", "invoice__membership", "invoice__club")
            .order_by("invoice__recipient_name", "pk")
        )
        if not dunnings:
            raise NotFound(gettext("Keine Mahnungen gefunden."))
        invoices = [d.invoice for d in dunnings]
        by_invoice = {d.invoice_id: d for d in dunnings}
        name = pdf.dunning_filename(dunnings[0]) if len(dunnings) == 1 else "Mahnungen.pdf"
        response = HttpResponse(pdf.render(invoices, by_invoice), content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response


# --- Übersicht für die Finanzen-Startseite ---


class BillingOverviewView(BillingMixin, APIView):
    """Kennzahlen für die Finanzen-Übersicht: Entwürfe, offene und überfällige
    Rechnungen, fällige Mahnungen, Lastschriften."""

    def get(self, request, org_id: int):
        today = timezone.localdate()
        invoices = Invoice.objects.filter(organization=self.org)

        def sums(qs):
            agg = qs.aggregate(n=Count("pk"), total=Sum("total"), paid=Sum("paid"))
            total = agg["total"] or Decimal("0")
            paid = agg["paid"] or Decimal("0")
            return {"count": agg["n"], "amount": f"{max(total - paid, Decimal('0')):.2f}"}

        drafts = invoices.filter(status=Invoice.Status.DRAFT).aggregate(
            n=Count("pk"), total=Sum("total")
        )
        open_qs = invoices.filter(status=Invoice.Status.OPEN)
        sepa_on = services.settings_for(self.org).sepa_enabled and not self.is_unit
        last_run = FeeRun.objects.filter(organization=self.org).order_by("-created_at").first()
        pending_debits = DebitRun.objects.filter(
            organization=self.org, status=DebitRun.Status.CREATED
        ).order_by("collection_date")
        return Response(
            {
                "drafts": {
                    "count": drafts["n"],
                    "amount": f"{drafts['total'] or Decimal('0'):.2f}",
                },
                "open": sums(open_qs),
                "overdue": sums(open_qs.filter(due_date__lt=today)),
                "dunnings_due": len(services.dunning_proposals(self.org, today)),
                "sepa_enabled": sepa_on,
                "debits_ready": len(sepa.proposals(self.org, today)) if sepa_on else 0,
                "debits_pending": [
                    {"id": r.pk, "collection_date": r.collection_date, "total": f"{r.total:.2f}"}
                    for r in (pending_debits if sepa_on else [])
                ],
                "last_run": (
                    {"id": last_run.pk, "label": last_run.label, "created_at": last_run.created_at}
                    if last_run
                    else None
                ),
                "can_edit": BILLING_EDIT in self.org_permissions,
            }
        )


# --- Rechnungen des Dachverbands an den Verein ---


class ReceivedInvoicesMixin(OrgScopedMixin):
    """Lesen dürfen Kassierer: Recht für Beiträge oder für die Kasse."""

    allowed_org_types = (Organization.Type.CLUB,)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not {BILLING_VIEW, FINANCE_VIEW} & self.org_permissions:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))

    def federation_qs(self):
        fed = self.org.parent
        if fed is None or fed.type != Organization.Type.FEDERATION:
            return None, Invoice.objects.none()
        return fed, Invoice.objects.filter(
            organization=fed,
            club=self.org,
            status__in=(Invoice.Status.OPEN, Invoice.Status.PAID, Invoice.Status.CANCELLED),
        ).select_related("organization", "club", "run")


class ReceivedInvoicesView(ReceivedInvoicesMixin, APIView):
    def get(self, request, org_id: int):
        from core.tenancy import tenant_context

        fed, _ = self.federation_qs()
        if fed is None:
            return Response({"federation": None, "invoices": []})
        with tenant_context(fed.pk, request.user.pk):
            _, qs = self.federation_qs()
            qs = qs.prefetch_related("lines", "dunnings", "payments__booking__account")
            data = InvoiceDetailSerializer(qs.order_by("-date", "-pk"), many=True).data
        return Response({"federation": fed.name, "invoices": data})


class ReceivedInvoicePdfView(ReceivedInvoicesMixin, APIView):
    def get(self, request, org_id: int, pk: int):
        from core.tenancy import tenant_context

        fed, _ = self.federation_qs()
        if fed is None:
            raise NotFound()
        with tenant_context(fed.pk, request.user.pk):
            _, qs = self.federation_qs()
            invoice = get_object_or_404(qs, pk=pk)
            return pdf_response(
                [invoice], pdf.filename(invoice), request.query_params.get("download") == "1"
            )


# --- SEPA-Lastschrift ---


class SepaMixin(BillingMixin):
    """Mandate und Lastschriften gibt es nur, wenn die Organisation sie eingeschaltet hat."""

    allowed_org_types = BillingMixin.WITHOUT_UNITS

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not services.settings_for(self.org).sepa_enabled:
            raise NotFound(gettext("SEPA-Lastschrift ist ausgeschaltet."))


class MandateViewSet(SepaMixin, viewsets.ReadOnlyModelViewSet):
    """Mandate: Liste, Papiermandat erfassen, widerrufen."""

    serializer_class = MandateSerializer
    pagination_class = InvoicePagination

    def get_queryset(self):
        qs = Mandate.objects.filter(organization=self.org).select_related(
            "membership__person", "club"
        )
        p = self.request.query_params
        if (s := p.get("status")) in Mandate.Status.values:
            qs = qs.filter(status=s)
        if (m := p.get("mitglied")) and m.isdigit():
            qs = qs.filter(membership_id=m)
        if term := p.get("suche", "").strip():
            # Kontoinhaber ist verschlüsselt (core/encfields.py): im Speicher suchen
            low = term.lower()
            by_holder = [
                pk for pk, holder in qs.values_list("pk", "holder") if low in holder.lower()
            ]
            qs = qs.filter(
                Q(reference__icontains=term)
                | Q(pk__in=by_holder)
                | Q(membership__person__last_name__icontains=term)
                | Q(club__name__icontains=term)
            )
        return qs

    @transaction.atomic
    def create(self, request, org_id: int):
        ser = MandateInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        membership = club = None
        if self.is_federation:
            club = Organization.objects.filter(
                parent=self.org, type=Organization.Type.CLUB, pk=data.get("club") or 0
            ).first()
            if club is None:
                raise serializers.ValidationError({"club": fill("Bitte {einen} wählen.", self.org)})
        else:
            membership = Membership.objects.filter(
                organization=self.org, pk=data.get("membership") or 0
            ).first()
            if membership is None:
                raise serializers.ValidationError(
                    {"membership": gettext("Bitte ein Mitglied wählen.")}
                )
        if data["signed_on"] > timezone.localdate():
            raise serializers.ValidationError(
                {"signed_on": gettext("Das Datum liegt in der Zukunft.")}
            )
        try:
            mandate = sepa.create_mandate(
                self.org,
                membership=membership,
                club=club,
                signed_on=data["signed_on"],
                source=Mandate.Source.PAPER,
                user=request.user,
                holder=data["holder"],
                iban=data["iban"],
                bic=data.get("bic", ""),
            )
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "create",
            mandate,
            {"SEPA-Mandat": [None, f"{mandate.reference} ({sepa.masked_iban(mandate.iban)})"]},
        )
        return Response(MandateSerializer(mandate).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def revoke(self, request, org_id: int, pk: int):
        mandate = self.get_object()
        try:
            sepa.revoke(mandate)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            mandate,
            {"SEPA-Mandat": [mandate.reference, "widerrufen"]},
        )
        return Response(MandateSerializer(mandate).data)


def send_prenotification(item: DebitItem) -> bool:
    invoice = item.invoice
    if not invoice.recipient_email:
        return False
    org = invoice.organization
    body = f"Guten Tag,\n\n{pdf.prenotification_text(item)}\n\nViele Grüße\n{org.name}\n"
    sent = mail.send(
        invoice.recipient_email,
        f"Ankündigung SEPA-Lastschrift {item.run.collection_date:%d.%m.%Y} – {org.name}",
        body,
        organization=org,
        kind="vorabankuendigung",
        reply_to=[org.contact_email] if org.contact_email else None,
        fail_silently=True,
    )
    if sent:
        item.prenotified_at = timezone.now()
        item.save(update_fields=["prenotified_at"])
    return sent


class DebitRunViewSet(SepaMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = DebitRunSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            DebitRun.objects.filter(organization=self.org)
            .select_related("account", "organization")
            .prefetch_related("items__invoice__organization", "items__mandate")
        )

    @action(detail=False, methods=["get"])
    def proposals(self, request, org_id: int):
        cfg = services.settings_for(self.org)
        return Response(
            {
                "creditor_id": cfg.creditor_id,
                "creditor_valid": sepa.creditor_id_valid(cfg.creditor_id),
                "expiring_soon": sepa.expiring_soon(self.org),
                "account": cfg.account.name if cfg.account else None,
                "account_has_iban": bool(cfg.account and cfg.account.iban),
                "earliest": sepa.earliest_collection(self.org),
                "prenotification_days": cfg.prenotification_days,
                "invoices": [
                    {
                        **InvoiceListSerializer(invoice).data,
                        "mandate": mandate.reference,
                        "holder": mandate.holder,
                        "iban_masked": sepa.masked_iban(mandate.iban),
                        "has_email": bool(invoice.recipient_email),
                    }
                    for invoice, mandate in sepa.proposals(self.org)
                ],
            }
        )

    @transaction.atomic
    def create(self, request, org_id: int):
        ids = [int(i) for i in request.data.get("invoices", []) if str(i).isdigit()]
        date = serializers.DateField().to_internal_value(request.data.get("collection_date"))
        try:
            run = sepa.create_run(self.org, ids, date, request.user)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "create",
            run,
            {
                "Lastschriftlauf": [
                    None,
                    f"{run.items.count()} Lastschriften über {pdf.euro(run.total)} "
                    f"zum {run.collection_date:%d.%m.%Y}",
                ]
            },
        )
        sent = sum(
            1
            for item in run.items.select_related("invoice__organization", "mandate", "run")
            if send_prenotification(item)
        )
        data = DebitRunSerializer(self.get_queryset().get(pk=run.pk)).data
        return Response({**data, "prenotified": sent}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def xml(self, request, org_id: int, pk: int):
        run = self.get_object()
        if run.status == DebitRun.Status.CANCELLED:
            raise serializers.ValidationError(gettext("Der Lauf ist verworfen."))
        problems = sepa.run_problems(run)
        if problems:
            raise serializers.ValidationError(
                "Die Datei passt nicht mehr zum Stand: "
                + "; ".join(problems)
                + ". Bitte den Lauf verwerfen und neu erstellen."
            )
        if not run.xml:
            run.xml = sepa.pain008(run).decode()
            run.save(update_fields=["xml"])
        response = HttpResponse(run.xml.encode(), content_type="application/xml")
        response["Content-Disposition"] = (
            f'attachment; filename="Lastschrift-{run.collection_date:%Y-%m-%d}-{run.pk}.xml"'
        )
        response["Cache-Control"] = "private, no-store"
        return response

    @action(detail=True, methods=["get"])
    def prenotifications(self, request, org_id: int, pk: int):
        """Vorabankündigungen zum Drucken (nur Zahler ohne E-Mail, ?alle=1 für alle)."""
        run = self.get_object()
        items = run.items.select_related("invoice__organization", "mandate", "run")
        if request.query_params.get("alle") != "1":
            items = items.filter(prenotified_at__isnull=True)
        response = HttpResponse(
            pdf.render_prenotifications(list(items)), content_type="application/pdf"
        )
        response["Content-Disposition"] = f'inline; filename="Vorabankuendigung-{run.pk}.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def book(self, request, org_id: int, pk: int):
        run = self.get_object()
        try:
            booked = sepa.book_run(run, request.user)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org,
            request.user,
            "update",
            run,
            {"Lastschriftlauf": ["erstellt", f"gebucht ({booked} Zahlungen)"]},
        )
        data = DebitRunSerializer(self.get_queryset().get(pk=run.pk)).data
        return Response({**data, "booked": booked})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, org_id: int, pk: int):
        run = self.get_object()
        try:
            sepa.cancel_run(run)
        except DjangoValidationError as exc:
            raise _as_drf(exc) from exc
        record(
            self.org, request.user, "update", run, {"Lastschriftlauf": ["erstellt", "verworfen"]}
        )
        return Response(DebitRunSerializer(self.get_queryset().get(pk=run.pk)).data)
