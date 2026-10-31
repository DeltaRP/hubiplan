"""API für Mitgliedsausweise mit QR-Code.

- Verein: Ausweis eines Mitglieds anzeigen, neu erzeugen, sperren; PDF für ein
  Mitglied, eine Abteilung oder alle aktuellen Mitglieder.
- Dachverband: PDF für alle aktuellen Mitglieder seiner Vereine (oder eines
  Vereins), nur mit Plattform-Freigabe für Mitgliedsdaten.
- Abteilung: dasselbe für die Mitglieder der Abteilung.
- Mitgliederbereich: der eigene Ausweis.
- Öffentlich: die Seite hinter dem QR-Code.
"""

from __future__ import annotations

import base64

from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import CARDS_MANAGE, DEPT_CARDS_MANAGE
from audit.log import record
from core.api_base import OrgScopedMixin
from core.tenancy import rls_bypass, tenant_context
from members.federation_views import federation_queryset, filter_federation
from members.models import Membership
from members.views import filter_members, member_queryset
from portal.views import DepartmentScopedMixin, _portal_access

from . import services
from .models import MemberCard

MAX_CARDS = 2000  # Obergrenze je PDF


def _with_qr(card: MemberCard | None) -> dict:
    data = services.card_info(card)
    if card is not None:
        svg = services.qr_svg(card.url).encode()
        data["qr"] = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    return data


def _pdf_response(pdf: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


class ActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["create", "renew", "revoke", "restore"])


ACTION_TEXT = {
    "create": "Mitgliedsausweis erstellt",
    "renew": "neuer QR-Code erzeugt (alter ungültig)",
    "revoke": "Mitgliedsausweis gesperrt",
    "restore": "Mitgliedsausweis wieder freigegeben",
}


def apply_action(club, membership: Membership, action: str, user) -> MemberCard:
    card = MemberCard.objects.filter(membership=membership).first()
    if card is None:
        card = services.ensure_card(membership, user)
    if action == "renew":
        services.renew(card)
    elif action == "revoke" and not card.revoked_at:
        card.revoked_at = timezone.now()
        card.save(update_fields=["revoked_at"])
    elif action == "restore" and card.revoked_at:
        card.revoked_at = None
        card.save(update_fields=["revoked_at"])
    record(
        club,
        user,
        "update",
        membership,
        {"Mitgliedsausweis": [None, ACTION_TEXT[action]]},
        person=membership.person,
    )
    return card


def cards_for(memberships: list[Membership], user) -> list[MemberCard]:
    """Ausweise für alle Mitgliedschaften (fehlende anlegen), gesperrte auslassen."""
    existing = {c.membership_id: c for c in MemberCard.objects.filter(membership__in=memberships)}
    result = []
    for m in memberships:
        card = existing.get(m.pk)
        if card is None:
            card = MemberCard.objects.create(
                membership=m, organization_id=m.organization_id, created_by=user
            )
        if card.revoked_at:
            continue
        card.membership = m
        result.append(card)
    return result


# --- Verein und Dachverband ---


class _CardOrgMixin(OrgScopedMixin):
    read_permission = CARDS_MANAGE
    write_permission = CARDS_MANAGE


class MemberCardView(_CardOrgMixin, APIView):
    allowed_org_types = ("club",)

    def membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"),
            organization=self.org,
            pk=self.kwargs["pk"],
            purged_at__isnull=True,
        )

    def get(self, request, org_id: int, pk: int):
        membership = self.membership()
        return Response(_with_qr(MemberCard.objects.filter(membership=membership).first()))

    def post(self, request, org_id: int, pk: int):
        data = ActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        membership = self.membership()
        card = apply_action(self.org, membership, data.validated_data["action"], request.user)
        return Response(_with_qr(card))


class OrgCardsPdfView(_CardOrgMixin, APIView):
    """PDF zum Drucken.

    Verein: ?mitglied=, ?abteilung=, ?art=; Dachverband: ?verein=, ?mitglied=.
    """

    allowed_org_types = ("club", "federation")

    def get(self, request, org_id: int):
        params = request.query_params.copy()
        params["status"] = "aktiv"
        if self.org.type == "federation":
            if self.org.federation_member_access == "none":
                raise PermissionDenied(
                    "Die Plattform hat den Zugriff auf Mitgliedsdaten nicht freigegeben."
                )
            qs = filter_federation(federation_queryset(self.org), params)
        else:
            qs = filter_members(member_queryset(self.org), params, self.org)
        qs = qs.filter(purged_at__isnull=True)
        if params.get("mitglied"):
            qs = qs.filter(pk=params["mitglied"])
        memberships = list(qs.select_related("person", "organization__parent__parent")[:MAX_CARDS])
        # Ausweise gehören dem jeweiligen Verein; der Dachverband legt sie stellvertretend an
        with rls_bypass():
            cards = cards_for(memberships, request.user)
            entries = services.card_entries(cards)
        record(
            self.org,
            request.user,
            "view",
            self.org,
            {"Mitgliedsausweise": [None, f"{len(entries)} Ausweise als PDF"]},
        )
        return _pdf_response(services.render_pdf(entries), "mitgliedsausweise.pdf")


# --- Abteilung ---


class _DeptCardMixin(DepartmentScopedMixin):
    read_permission = DEPT_CARDS_MANAGE
    write_permission = DEPT_CARDS_MANAGE


class DeptMemberCardView(_DeptCardMixin, APIView):
    def get(self, request, dept_id: int, pk: int):
        membership = self.get_member(pk)
        return Response(_with_qr(MemberCard.objects.filter(membership=membership).first()))

    def post(self, request, dept_id: int, pk: int):
        data = ActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        membership = self.get_member(pk)
        card = apply_action(self.org, membership, data.validated_data["action"], request.user)
        return Response(_with_qr(card))


class DeptCardsPdfView(_DeptCardMixin, APIView):
    def get(self, request, dept_id: int):
        qs = self.dept_members().filter(purged_at__isnull=True)
        if request.query_params.get("mitglied"):
            qs = qs.filter(pk=request.query_params["mitglied"])
        memberships = list(
            qs.select_related("person", "organization__parent__parent").order_by(
                "person__last_name", "person__first_name", "pk"
            )[:MAX_CARDS]
        )
        cards = cards_for(memberships, request.user)
        entries = services.card_entries(cards)
        record(
            self.org,
            request.user,
            "view",
            self.org,
            {"Mitgliedsausweise": [None, f"{len(entries)} Ausweise ({self.dept.name}) als PDF"]},
        )
        return _pdf_response(services.render_pdf(entries), "mitgliedsausweise.pdf")


# --- Mitgliederbereich ---


class PortalCardView(APIView):
    """Eigener Ausweis. Wird beim ersten Aufruf angelegt, solange die Mitgliedschaft gilt."""

    def get(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        with tenant_context(club.pk, request.user.pk):
            membership = (
                Membership.objects.select_related("person")
                .filter(pk=access.membership_id, purged_at__isnull=True)
                .first()
            )
            if membership is None:
                raise NotFound()
            card = MemberCard.objects.filter(membership=membership).first()
            if card is None and membership.current_period():
                card = services.ensure_card(membership, request.user)
            data = _with_qr(card)
            data.pop("token", None)
            if card is not None and not card.revoked_at:
                # Für die App: alles, was der Ausweis zeigt, damit sie ihn auch ohne Netz
                # anzeigen kann (QR-Code erzeugt sie selbst aus der Adresse).
                display = services.public_data(card)
                display["club_number"] = membership.club_number or ""
                data["display"] = display
        return Response(data)


class PortalCardPdfView(APIView):
    def get(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        with tenant_context(club.pk, request.user.pk):
            card = (
                MemberCard.objects.select_related(
                    "membership__person", "organization__parent__parent"
                )
                .filter(membership_id=access.membership_id, revoked_at__isnull=True)
                .first()
            )
            if card is None:
                raise NotFound()
            entries = services.card_entries([card])
        return _pdf_response(services.render_pdf(entries), "mitgliedsausweis.pdf")


# --- Öffentliche Seite hinter dem QR-Code ---

RATE = (60, 600)  # 60 Aufrufe je 10 Minuten und IP


def _rate_limited(request) -> bool:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    key = f"card:{ip}"
    count = cache.get(key, 0)
    if count >= RATE[0]:
        return True
    cache.set(key, count + 1, RATE[1])
    return False


class PublicCardView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, token: str):
        if _rate_limited(request):
            return Response({"detail": "Zu viele Aufrufe. Bitte später erneut."}, status=429)
        card = services.find_valid(token)
        if card is None:
            raise Http404
        response = Response(services.public_data(card))
        response["Cache-Control"] = "no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response


class PublicCardPhotoView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, token: str):
        card = services.find_valid(token)
        if card is None:
            raise Http404
        with rls_bypass():
            if not card.membership.current_period():
                raise Http404
            photo = services.has_public_photo(card.membership)
            if photo is None:
                raise Http404
            response = FileResponse(photo.image.open("rb"), content_type="image/jpeg")
        response["Cache-Control"] = "private, max-age=600"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
