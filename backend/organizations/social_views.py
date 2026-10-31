"""Social-Media-Kanäle einer Einheit (Stammdaten)."""

from __future__ import annotations

from rest_framework import serializers, viewsets

from access.catalog import ORG_EDIT
from core.api_base import AuditMixin, ModelCleanMixin, OrgScopedMixin

from .models import Organization, SocialLink

MAX_LINKS = 20


class SocialLinkSerializer(ModelCleanMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    display = serializers.CharField(read_only=True)

    class Meta:
        model = SocialLink
        fields = ["id", "kind", "kind_label", "url", "label", "display", "position"]
        extra_kwargs = {"position": {"required": False}}

    def validate_url(self, value: str) -> str:
        if not value.lower().startswith(("https://", "http://")):
            raise serializers.ValidationError("Bitte eine Adresse mit https:// angeben.")
        return value


class SocialLinkViewSet(OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    """Lesen: jede Rolle der Einheit. Ändern: Organisationsdaten bearbeiten."""

    serializer_class = SocialLinkSerializer
    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.FEDERATION, Organization.Type.CLUB)
    pagination_class = None

    def get_queryset(self):
        return SocialLink.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        if SocialLink.objects.filter(organization=self.org).count() >= MAX_LINKS:
            raise serializers.ValidationError(f"Mehr als {MAX_LINKS} Kanäle sind nicht möglich.")
        last = (
            SocialLink.objects.filter(organization=self.org)
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
        )
        return {"organization": self.org, "position": (last or 0) + 1}
