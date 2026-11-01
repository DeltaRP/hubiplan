"""App: Kurzmitteilungen des Vorstands aus der App senden.

Nur die Art Kurzmitteilung und nur an alle Mitglieder der eigenen Einheit (Verein
bzw. Zug mit seinen Untereinheiten). Rechte wie im Browser: ``circulars.send`` im
Verein, ``dept.circulars.send`` in der Abteilung. Ausführliche Rundschreiben mit
Auswahl und Anhängen bleiben im Browser.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import CIRCULARS_SEND, DEPT_CIRCULARS_SEND
from access.models import RoleAssignment
from access.permissions import permissions_in
from audit.log import record
from circulars import recipients as rcp
from circulars import services as circular_services
from circulars.models import MAX_SHORT_BODY, Circular
from core.tenancy import scope_of, set_rls
from organizations.models import Organization
from portal import services as portal_services

from .auth import DeviceTokenAuthentication


def _clubs(user) -> list[Organization]:
    ids = (
        RoleAssignment.objects.active()
        .filter(user=user, organization__type=Organization.Type.CLUB)
        .values_list("organization_id", flat=True)
        .distinct()
    )
    clubs = Organization.objects.filter(pk__in=list(ids), is_active=True).order_by("name")
    return [c for c in clubs if CIRCULARS_SEND in permissions_in(user, c)]


def senders(user) -> list[dict]:
    """Einheiten, für die dieses Konto Kurzmitteilungen senden darf."""
    out = [
        {"key": f"org-{c.pk}", "name": c.display_name, "type": "org", "id": c.pk}
        for c in _clubs(user)
    ]
    for ctx in sorted(
        portal_services.department_contexts(user).values(),
        key=lambda c: (c.club.display_name, c.department.display_name),
    ):
        if DEPT_CIRCULARS_SEND in ctx.permissions:
            out.append(
                {
                    "key": f"dept-{ctx.department.pk}",
                    "name": ctx.department.display_name,
                    "club": ctx.club.display_name,
                    "type": "dept",
                    "id": ctx.department.pk,
                }
            )
    return out


class SendSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=MAX_SHORT_BODY)
    # false: nur zählen (Vorschau), true: senden
    confirm = serializers.BooleanField(default=False)


class SendersView(APIView):
    """GET: Einheiten, an deren Mitglieder dieses Konto aus der App senden darf."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"senders": senders(request.user), "max_body": MAX_SHORT_BODY})


class SendShortView(APIView):
    """POST: Kurzmitteilung vorbereiten (``confirm`` false: Empfängerzahl) oder senden."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def resolve(self, request, kind: str, pk: int):
        user = request.user
        if kind == "org":
            org = Organization.objects.filter(pk=pk, type=Organization.Type.CLUB).first()
            if org is None or not permissions_in(user, org):
                raise NotFound()
            if CIRCULARS_SEND not in permissions_in(user, org):
                raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
            set_rls(org.pk, user.pk, scope_id=scope_of(org.pk))
            return org, None
        if kind == "dept":
            ctx = portal_services.department_contexts(user).get(pk)
            if ctx is None:
                raise NotFound()
            if DEPT_CIRCULARS_SEND not in ctx.permissions:
                raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
            set_rls(ctx.club.pk, user.pk, scope_id=scope_of(ctx.club.pk))
            return ctx.club, ctx.department
        raise NotFound()

    def post(self, request, kind: str, pk: int):
        org, dept = self.resolve(request, kind, pk)
        data = SendSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        circular = Circular(
            organization=org,
            department=dept,
            kind=Circular.Kind.SHORT,
            audience=Circular.Audience.MEMBERS,
            subject=v["subject"].strip(),
            body=v["body"].strip(),
            via_app=True,
            filters={},
            created_by=request.user,
            reply_to=request.user.email,
        )
        errors = circular_services.problems(circular)
        if errors:
            raise serializers.ValidationError(errors)
        if not v["confirm"]:
            counts = rcp.select(circular).counts()
            return Response({"counts": counts, "sender": circular_services.sender_name(circular)})
        with transaction.atomic():
            circular.save()
            record(org, request.user, "create", circular, {"Betreff": [None, circular.subject]})
            counts = circular_services.start_sending(circular, request.user)
            record(
                org,
                request.user,
                "update",
                circular,
                {"versendet": [None, f"aus der App: {sum(counts.values())} Empfänger"]},
            )
        return Response({"id": circular.pk, "sent": counts}, status=201)
