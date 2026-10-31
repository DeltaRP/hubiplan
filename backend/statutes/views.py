"""API für Satzung, Beitragsordnung und Gründungsurkunde: Fassungen verwalten, öffentlich abrufen.

Die Art steht im Parameter ``kind`` (``statute``, ``fee_rules``, ``founding_deed``); ohne Angabe
gilt die Satzung, damit ältere Aufrufe weiter funktionieren.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import ORG_EDIT
from audit.log import record
from core.api_base import OrgScopedMixin
from core.tenancy import rls_bypass
from organizations.models import Department, Organization

from . import services
from .models import Kind, StatutePublication, StatuteVersion, kind_label


class UploadSerializer(serializers.Serializer):
    valid_from = serializers.DateField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class PublicationSerializer(serializers.Serializer):
    is_public = serializers.BooleanField()


def version_data(v: StatuteVersion, org_id: int, current_id: int | None) -> dict:
    return {
        "id": v.pk,
        "valid_from": v.valid_from,
        "note": v.note,
        "name": v.name,
        "size": v.size,
        "uploaded_at": v.uploaded_at,
        "uploaded_by": v.uploaded_by.get_full_name() or v.uploaded_by.email
        if v.uploaded_by
        else "",
        "is_current": v.pk == current_id,
        "url": f"/api/orgs/{org_id}/statutes/{v.pk}/",
    }


def public_urls(request, pub: StatutePublication | None) -> dict:
    if pub is None:
        return {"is_public": False, "pdf_url": None, "info_url": None}
    pdf = reverse("public-statute", args=[pub.public_key])
    info = reverse("public-statute-info", args=[pub.public_key])
    return {
        "is_public": pub.is_public,
        "pdf_url": request.build_absolute_uri(pdf) if pub.is_public else None,
        "info_url": request.build_absolute_uri(info) if pub.is_public else None,
    }


class _StatuteMixin(OrgScopedMixin):
    """Lesen: jede Rolle der Organisation · Verwalten: Organisation bearbeiten."""

    read_permission = None
    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.FEDERATION, Organization.Type.CLUB)

    def department(self, value) -> Department | None:
        if value in (None, "", "null"):
            return None
        if not str(value).isdigit():
            raise Http404
        return get_object_or_404(Department, organization=self.org, pk=int(value))

    def label(self, department) -> str:
        return f" ({department.name})" if department else ""

    def kind(self, value) -> str:
        if value in (None, ""):
            return Kind.STATUTE
        if value not in Kind.values:
            raise serializers.ValidationError({"kind": "Unbekannte Dokumentart."})
        return value


class StatuteListView(_StatuteMixin, APIView):
    """GET: Fassungen und Veröffentlichung · POST: neue Fassung hochladen."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def payload(self, request, department, kind) -> dict:
        items = list(services.versions(self.org, department, kind).select_related("uploaded_by"))
        current = items[0].pk if items else None
        return {
            "kind": kind,
            "versions": [version_data(v, self.org.pk, current) for v in items],
            "publication": public_urls(
                request, services.publication(self.org, department, kind=kind)
            ),
            "can_manage": ORG_EDIT in self.org_permissions,
        }

    def get(self, request, org_id: int):
        department = self.department(request.query_params.get("department"))
        kind = self.kind(request.query_params.get("kind"))
        return Response(self.payload(request, department, kind))

    @transaction.atomic
    def post(self, request, org_id: int):
        department = self.department(request.data.get("department"))
        kind = self.kind(request.data.get("kind"))
        data = UploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        upload = request.FILES.get("file")
        try:
            services.check_pdf(upload)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        version = StatuteVersion(
            organization=self.org,
            department=department,
            kind=kind,
            name=upload.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200],
            size=upload.size,
            valid_from=data.validated_data["valid_from"],
            note=data.validated_data.get("note", ""),
            uploaded_by=request.user,
        )
        version.file.save(services.safe_name(upload.name, kind), upload, save=False)
        version.save()
        record(
            self.org,
            request.user,
            "create",
            version,
            {
                kind_label(kind): [
                    None,
                    f"Fassung vom {version.valid_from:%d.%m.%Y}{self.label(department)}",
                ]
            },
        )
        return Response(self.payload(request, department, kind), status=status.HTTP_201_CREATED)


class StatuteDetailView(_StatuteMixin, APIView):
    """GET: PDF einer Fassung · DELETE: Fassung löschen."""

    def get_version(self, pk: int) -> StatuteVersion:
        return get_object_or_404(StatuteVersion, organization=self.org, pk=pk)

    def get(self, request, org_id: int, pk: int):
        version = self.get_version(pk)
        response = FileResponse(
            version.file.open("rb"),
            content_type="application/pdf",
            as_attachment=request.query_params.get("download") == "1",
            filename=version.name,
        )
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        version = self.get_version(pk)
        department = version.department
        record(
            self.org,
            request.user,
            "delete",
            version,
            {
                kind_label(version.kind): [
                    f"Fassung vom {version.valid_from:%d.%m.%Y}{self.label(department)}",
                    None,
                ]
            },
        )
        version.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatutePublicationView(_StatuteMixin, APIView):
    """PUT: öffentlichen Abruf ein- oder ausschalten."""

    @transaction.atomic
    def put(self, request, org_id: int):
        department = self.department(request.data.get("department"))
        kind = self.kind(request.data.get("kind"))
        data = PublicationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        pub = services.publication(self.org, department, create=True, kind=kind)
        new = data.validated_data["is_public"]
        if pub.is_public != new:
            pub.is_public = new
            pub.save(update_fields=["is_public"])
            record(
                self.org,
                request.user,
                "update",
                pub,
                {f"{kind_label(kind)} öffentlich{self.label(department)}": [not new, new]},
            )
        return Response(public_urls(request, pub))


# --- öffentlicher Abruf ohne Anmeldung ---


def _published(key: str) -> tuple[StatutePublication, list[StatuteVersion]]:
    with rls_bypass():
        pub = (
            StatutePublication.objects.select_related("organization", "department")
            .filter(public_key=key, is_public=True)
            .first()
        )
        # Deaktivierte Organisation oder Untereinheit: Link gesperrt (Audit B-V05)
        if (
            pub is None
            or not pub.organization.is_active
            or (pub.department is not None and not pub.department.is_active)
        ):
            raise Http404
        items = list(services.versions(pub.organization, pub.department, pub.kind))
    if not items:
        raise Http404
    return pub, items


def _pdf(version: StatuteVersion) -> FileResponse:
    response = FileResponse(
        version.file.open("rb"), content_type="application/pdf", filename=version.name
    )
    response["Cache-Control"] = "public, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    response["Access-Control-Allow-Origin"] = "*"
    return response


class PublicStatuteView(APIView):
    """Aktuelle Fassung als PDF (stabiler Link)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str):
        _, items = _published(key)
        return _pdf(items[0])


class PublicStatuteVersionView(APIView):
    """Eine bestimmte Fassung als PDF."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str, pk: int):
        _, items = _published(key)
        version = next((v for v in items if v.pk == pk), None)
        if version is None:
            raise Http404
        return _pdf(version)


class PublicStatuteInfoView(APIView):
    """Metadaten aller Fassungen, z. B. für Webseiten."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str):
        pub, items = _published(key)
        owner = pub.department or pub.organization
        data = {
            "kind": pub.kind,
            "title": kind_label(pub.kind),
            "name": owner.name,
            "organization": pub.organization.name,
            "department": pub.department.name if pub.department else None,
            "current_url": request.build_absolute_uri(reverse("public-statute", args=[key])),
            "versions": [
                {
                    "valid_from": v.valid_from,
                    "note": v.note,
                    "size": v.size,
                    "is_current": i == 0,
                    "url": request.build_absolute_uri(
                        reverse("public-statute-version", args=[key, v.pk])
                    ),
                }
                for i, v in enumerate(items)
            ],
        }
        response = Response(data)
        response["Access-Control-Allow-Origin"] = "*"
        response["Cache-Control"] = "public, max-age=300"
        return response
