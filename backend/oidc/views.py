"""Schnittstellen der Nextcloud-Anmeldung.

Öffentlich (für die Nextcloud): ``/api/oidc/.well-known/openid-configuration``, ``jwks``,
``token``, ``userinfo``. Für die Seite „Bei der Nextcloud anmelden“ in HUBIplan:
``/api/oidc/authorize/`` (angemeldet, mit CSRF). Einstellungen je Einheit:
``/api/orgs/<id>/nextcloud/``.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import gettext
from rest_framework import serializers, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import ROLES_MANAGE
from audit.log import record
from core.api_base import AuditMixin, OrgScopedMixin
from core.ratelimit import client_ip, too_many

from . import provider
from .models import Client

TOKEN_RATE = (60, 60)


def _json(data: dict, status: int = 200) -> JsonResponse:
    response = JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


class _Public(APIView):
    """Für die Nextcloud (Server oder Browser): ohne Anmeldung, ohne Sitzung, ohne CSRF."""

    authentication_classes: list = []
    permission_classes = [AllowAny]


class DiscoveryView(_Public):
    def get(self, request):
        response = JsonResponse(provider.discovery())
        response["Cache-Control"] = "public, max-age=3600"
        return response


class JwksView(_Public):
    def get(self, request):
        response = JsonResponse(provider.jwks())
        response["Cache-Control"] = "public, max-age=3600"
        return response


def _token_error(exc: provider.TokenError) -> JsonResponse:
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    response = _json(body, status=exc.status)
    if exc.status == 401:
        basic = exc.error == "invalid_client"
        response["WWW-Authenticate"] = (
            'Basic realm="hubiplan"' if basic else 'Bearer error="invalid_token"'
        )
    return response


class TokenView(_Public):
    """Code einlösen. Aufrufer ist der Server der Nextcloud (Formular, kein JSON)."""

    parser_classes = [FormParser]

    def post(self, request):
        if too_many(f"oidc:token:{client_ip(request)}", *TOKEN_RATE):
            return _json({"error": "slow_down"}, status=429)
        try:
            return _json(provider.token(request._request))
        except provider.TokenError as exc:
            return _token_error(exc)


class UserinfoView(_Public):
    def _answer(self, request):
        if too_many(f"oidc:userinfo:{client_ip(request)}", *TOKEN_RATE):
            return _json({"error": "slow_down"}, status=429)
        try:
            return _json(provider.userinfo(request._request))
        except provider.TokenError as exc:
            return _token_error(exc)

    def get(self, request):
        return self._answer(request)

    def post(self, request):
        return self._answer(request)


class AuthorizeView(APIView):
    """Für die Seite „Bei der Nextcloud anmelden“: Dienst beschreiben bzw. Code ausstellen."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            return Response(provider.describe(request.query_params))
        except provider.AuthorizeError as exc:
            return Response({"detail": exc.message}, status=400)

    def post(self, request):
        if too_many(f"oidc:authorize:{request.user.pk}", 30, 600):
            raise ValidationError({"detail": gettext("Zu viele Versuche. Bitte später erneut.")})
        try:
            return Response({"redirect": provider.authorize(request._request, request.data)})
        except provider.AuthorizeError as exc:
            return Response(
                {"detail": exc.message, "redirect": exc.redirect, "back": exc.back}, status=400
            )


# --- Einstellungen je Einheit ---


def clean_base_url(value: str) -> str:
    parts = urlsplit(str(value or "").strip())
    allow_http = settings.DEBUG and parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme != "https" and not (parts.scheme == "http" and allow_http):
        raise serializers.ValidationError(gettext("Bitte die Adresse mit https:// angeben."))
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise serializers.ValidationError(
            gettext("Bitte nur die Adresse der Nextcloud angeben, z. B. https://cloud.example.org")
        )
    path = parts.path.rstrip("/")
    if path.endswith("/index.php"):
        path = path[: -len("/index.php")]
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


class ClientSerializer(serializers.ModelSerializer):
    redirect_uri = serializers.SerializerMethodField()
    discovery_url = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "base_url",
            "client_id",
            "audience",
            "require_mfa",
            "groups_board",
            "groups_roles",
            "groups_units",
            "groups_members",
            "is_active",
            "created_at",
            "last_used_at",
            "redirect_uri",
            "discovery_url",
        ]
        read_only_fields = ["client_id", "created_at", "last_used_at"]

    def get_redirect_uri(self, obj) -> str:
        return obj.redirect_uris[0]

    def get_discovery_url(self, obj) -> str:
        return f"{provider.issuer()}/.well-known/openid-configuration"

    def validate_base_url(self, value):
        return clean_base_url(value)

    def validate(self, attrs):
        org = self.context["org"]
        if attrs.get("audience") == Client.Audience.MEMBERS and org.type != "club":
            raise serializers.ValidationError(
                {"audience": gettext("Mitgliederzugänge gibt es nur bei Vereinen.")}
            )
        return attrs


class ClientViewSet(OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    read_permission = ROLES_MANAGE
    write_permission = ROLES_MANAGE
    allowed_org_types = ("club", "federation")

    def get_queryset(self):
        return Client.objects.filter(organization=self.org)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx

    def get_create_kwargs(self) -> dict:
        draft = Client()
        self._secret = draft.set_secret()
        return {
            "organization": self.org,
            "created_by": self.request.user,
            "secret_hash": draft.secret_hash,
        }

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        # Das Geheimnis gibt es nur in dieser Antwort; gespeichert ist nur die Prüfsumme
        response.data["client_secret"] = self._secret
        return response

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def secret(self, request, *args, **kwargs):
        """Neues Geheimnis (das alte gilt sofort nicht mehr)."""
        client = self.get_object()
        secret = client.set_secret()
        client.save(update_fields=["secret_hash", "updated_at"])
        record(self.org, request.user, "update", client, {"Geheimnis": ["…", "neu"]})
        data = dict(self.get_serializer(client).data)
        data["client_secret"] = secret
        return Response(data)
