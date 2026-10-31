"""Impressum und Datenschutzhinweise: öffentlich abrufen und pflegen."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import ORG_EDIT
from audit.log import diff, record, snapshot
from core.api_base import ModelCleanMixin, OrgScopedMixin

from . import imprint as service
from .imprint_generator import privacy_for
from .models import Department, Imprint, Organization
from .views import IsPlatformAdmin

EDIT_FIELDS = [
    "mode",
    "external_url",
    "name",
    "legal_form",
    "street",
    "postal_code",
    "city",
    "representatives",
    "email",
    "phone",
    "registered",
    "register_court",
    "register_number",
    "vat_id",
    "responsible",
    "data_protection_officer",
    "extra_text",
    "privacy_mode",
    "privacy_text",
    "privacy_url",
]


class ImprintSerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = Imprint
        fields = [
            "public_key",
            *EDIT_FIELDS,
            "privacy_published_text",
            "privacy_published_at",
            "updated_at",
        ]
        read_only_fields = [
            "public_key",
            "privacy_published_text",
            "privacy_published_at",
            "updated_at",
        ]

    def validate_mode(self, value):
        org = self.instance.organization if self.instance else None
        if org is not None and org.type == Organization.Type.PLATFORM and value != "own":
            raise serializers.ValidationError("Die Plattform braucht ein eigenes Impressum.")
        return value


def _state(org: Organization, imprint: Imprint) -> dict:
    """Gepflegte Werte, Vorschau nach außen und fehlende Angaben."""
    owner, effective = service.owner_of(org)
    preview = service.details(owner, effective)
    return {
        "organization": {"id": org.pk, "name": org.name, "type": org.type},
        "imprint": ImprintSerializer(imprint).data,
        "owner": {"id": owner.pk, "name": owner.name, "is_self": owner.pk == org.pk},
        "preview": preview,
        "representatives": service.representatives(org),
        "missing": service.missing(owner, effective, preview),
        "urls": service.page_urls(org),
        # Aus den Einstellungen erzeugter Vorschlag für die Datenschutzhinweise
        "template": privacy_for(org),
    }


def _update(request, org: Organization, audit_org: Organization) -> dict:
    imprint = service.ensure(org)
    serializer = ImprintSerializer(imprint, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    before = snapshot(imprint)
    obj = serializer.save()
    changes = diff(before, snapshot(obj))
    if changes:
        record(audit_org, request.user, "update", obj, changes)
    return _state(org, obj)


def _publish(request, org: Organization, audit_org: Organization) -> dict:
    """Entwurf der Datenschutzhinweise veröffentlichen (POST {"action": "publish_privacy"})."""
    if request.data.get("action") != "publish_privacy":
        raise serializers.ValidationError("Unbekannte Aktion.")
    imprint = service.ensure(org)
    if not imprint.privacy_text.strip():
        raise serializers.ValidationError({"privacy_text": "Der Entwurf ist leer."})
    before = imprint.privacy_published_at
    imprint.privacy_published_text = imprint.privacy_text
    imprint.privacy_published_at = timezone.now()
    imprint.save(update_fields=["privacy_published_text", "privacy_published_at", "updated_at"])
    record(
        audit_org,
        request.user,
        "update",
        imprint,
        {
            "Datenschutzhinweise veröffentlicht": [
                str(before or ""),
                str(imprint.privacy_published_at),
            ]
        },
    )
    return _state(org, imprint)


class OrgImprintView(OrgScopedMixin, APIView):
    """Impressum der Einheit selbst (lesen: jede Rolle, ändern: org.edit)."""

    write_permission = ORG_EDIT

    def get(self, request, org_id: int):
        return Response(_state(self.org, service.ensure(self.org)))

    def patch(self, request, org_id: int):
        return Response(_update(request, self.org, self.org))

    def post(self, request, org_id: int):
        return Response(_publish(request, self.org, self.org))


class UnitImprintView(OrgScopedMixin, APIView):
    """Impressum einer Untereinheit (Standard: von oben übernehmen)."""

    write_permission = ORG_EDIT

    def unit(self, unit_id: int) -> Department:
        return get_object_or_404(Department, pk=unit_id, organization=self.org)

    def get(self, request, org_id: int, unit_id: int):
        unit = self.unit(unit_id)
        return Response(_state(unit, service.ensure(unit)))

    def patch(self, request, org_id: int, unit_id: int):
        return Response(_update(request, self.unit(unit_id), self.org))

    def post(self, request, org_id: int, unit_id: int):
        return Response(_publish(request, self.unit(unit_id), self.org))


class PlatformImprintView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        platform = Organization.platform()
        return Response(_state(platform, service.ensure(platform)))

    def patch(self, request):
        platform = Organization.platform()
        return Response(_update(request, platform, platform))

    def post(self, request):
        platform = Organization.platform()
        return Response(_publish(request, platform, platform))


def _public(data: dict) -> Response:
    response = Response(data)
    response["Cache-Control"] = "public, max-age=300"
    return response


class PublicPlatformImprintView(APIView):
    """Impressum und Datenschutzerklärung der Plattform."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return _public(service.public_data(Organization.platform()))


class PublicImprintView(APIView):
    """Impressum und Datenschutzhinweise einer Einheit (fester Schlüssel)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, key: str):
        imprint = Imprint.objects.select_related("organization").filter(public_key=key).first()
        if imprint is None or not imprint.organization.is_active:
            raise Http404
        data = service.public_data(imprint.organization)
        data["platform"] = service.page_urls(Organization.platform())
        return _public(data)
