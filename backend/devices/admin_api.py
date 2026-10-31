"""Verwaltung in der App (Schritt A8): Vorstandszugang und Schnittstelle ``/api/app/v1/admin/``.

Die App zeigt den Reiter „Verwaltung“ nur Konten mit Verwaltungsrechten. Daten gibt es erst
nach dem Freischalten mit Passwort und Zwei-Faktor-Code; dann gilt ein eigener Schlüssel
(``hpa_…``) nur für ``/api/app/v1/admin/u/<Einheit>/…``. Rechte und Datenbereich prüfen die
Ansichten wie im Browser (``OrgScopedMixin``, RLS); die App darf nie mehr als der Browser.
"""

from __future__ import annotations

import datetime
import logging

from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import (
    BILLING_EDIT,
    BILLING_VIEW,
    CARDS_MANAGE,
    DEPT_EVENTS_MANAGE,
    DEPT_MEMBERS_EDIT,
    DEPT_MEMBERS_VIEW,
    EVENTS_MANAGE,
    FINANCE_EDIT,
    FINANCE_VIEW,
    MEMBERS_EDIT,
    MEMBERS_VIEW,
    PHOTOS_MANAGE,
)
from access.permissions import organizations_for
from audit.log import current_via
from changes import tracking
from core.api_base import OrgScopedMixin
from core.ratelimit import too_many
from members.open_tasks import event_tasks, member_tasks

from .auth import AdminTokenAuthentication, DeviceTokenAuthentication
from .models import ADMIN_DAYS, Device, hash_token

logger = logging.getLogger(__name__)

# Rechte, für die es in der App etwas zu verwalten gibt
ADMIN_PERMISSIONS = (
    MEMBERS_VIEW,
    MEMBERS_EDIT,
    PHOTOS_MANAGE,
    CARDS_MANAGE,
    EVENTS_MANAGE,
    FINANCE_VIEW,
    FINANCE_EDIT,
    BILLING_VIEW,
    BILLING_EDIT,
)
# Untereinheiten (Rollen nur dort, z. B. Zugführung): Pfad /api/app/v1/admin/d/<Untereinheit>/
DEPT_ADMIN_PERMISSIONS = (DEPT_MEMBERS_VIEW, DEPT_MEMBERS_EDIT, DEPT_EVENTS_MANAGE)
# Freischalten: höchstens 5 Versuche je Gerät in 15 Minuten
UNLOCK_LIMIT = (5, 15 * 60)


def admin_units(user) -> list[dict]:
    units = []
    for org, perms in organizations_for(user):
        own = sorted(p for p in perms if p in ADMIN_PERMISSIONS)
        if own:
            units.append({"id": org.pk, "name": org.name, "type": org.type, "permissions": own})
    return sorted(units, key=lambda u: u["name"].lower())


def admin_departments(user) -> list[dict]:
    """Untereinheiten, in denen der Benutzer über eine Rolle dort etwas verwalten darf."""
    from portal.services import department_contexts

    rows = []
    for ctx in department_contexts(user).values():
        own = sorted(p for p in ctx.permissions if p in DEPT_ADMIN_PERMISSIONS)
        if own:
            rows.append(
                {
                    "id": ctx.department.pk,
                    "name": ctx.department.display_name or ctx.department.name,
                    "club_id": ctx.club.pk,
                    "club_name": ctx.club.name,
                    "events": "events" in (ctx.club.enabled_modules or []),
                    "permissions": own,
                }
            )
    return sorted(rows, key=lambda d: d["name"].lower())


def has_totp(user) -> bool:
    return Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists()


def admin_state(device: Device) -> dict:
    active = device.admin_active
    return {
        "unlocked": active,
        "until": device.admin_until if active else None,
        # Härtung H7: Anfragen müssen unterschrieben sein
        "signed": active and bool(device.admin_key),
    }


class AdminOverviewView(APIView):
    """Einheiten mit Verwaltungsrechten und Stand der Freischaltung (ohne Daten)."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=dict)
    def get(self, request):
        device: Device = request.auth
        return Response(
            {
                "units": admin_units(request.user),
                # B4: neu, ältere Apps lesen das Feld nicht
                "departments": admin_departments(request.user),
                "two_factor": has_totp(request.user),
                **admin_state(device),
            }
        )


class UnlockSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=200, trim_whitespace=False)
    code = serializers.CharField(max_length=20)
    # Härtung H7: öffentlicher Teil des Vorstands-Schlüsselpaars (nur nach Entsperren nutzbar)
    admin_key = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")

    def validate_admin_key(self, value):
        from .devicekey import valid_public_key

        if value and not valid_public_key(value):
            raise serializers.ValidationError("Ungültiger Schlüssel.")
        return value


class AdminUnlockView(APIView):
    """Verwaltung freischalten (Passwort + 2FA) bzw. auf diesem Gerät sperren."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(request=UnlockSerializer, responses=dict)
    def post(self, request):
        device: Device = request.auth
        user = request.user
        if too_many(f"app-admin-unlock:{device.pk}", *UNLOCK_LIMIT):
            raise Throttled(detail="Zu viele Versuche. Bitte in einer Viertelstunde erneut.")
        if not admin_units(user) and not admin_departments(user):
            raise ValidationError({"detail": "Dein Konto hat keine Verwaltungsrechte."})
        totp = Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).first()
        if totp is None:
            raise ValidationError(
                {
                    "detail": "Für die Verwaltung in der App ist die Zwei-Faktor-Anmeldung nötig. "
                    "Bitte zuerst im Browser unter „Mein Konto“ einrichten."
                }
            )
        data = UnlockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # Fachfrage 3 (31.10.b): Verwaltung nur mit Schlüsselbindung (Gerät und Vorstand)
        if not device.device_key or not data.validated_data["admin_key"]:
            raise ValidationError(
                {
                    "detail": "Für die Verwaltung in der App ist eine aktuelle App-Version nötig. "
                    "Bitte die App aktualisieren."
                }
            )
        code = data.validated_data["code"].replace(" ", "")
        if not user.check_password(data.validated_data["password"]) or not TOTP(totp).validate_code(
            code
        ):
            if too_many(f"app-admin-unlock-fail:{device.pk}", 3, 60 * 60):
                from . import notify

                notify.admin_unlock_failed(user, device)
            raise ValidationError({"detail": "Passwort oder Code stimmt nicht."})
        token = Device.new_admin_token()
        now = timezone.now()
        device.admin_token_hash = hash_token(token)
        device.admin_until = now + datetime.timedelta(days=ADMIN_DAYS)
        device.admin_used_at = now
        # Mit Schlüsselpaar muss ab jetzt jede Anfrage unterschrieben sein
        device.admin_key = data.validated_data["admin_key"]
        device.save(update_fields=["admin_token_hash", "admin_until", "admin_used_at", "admin_key"])
        logger.info("Verwaltung in der App freigeschaltet: Gerät %s", device.pk)
        from . import notify

        notify.admin_unlocked(user, device)
        return Response({"token": token, **admin_state(device)}, status=201)

    def delete(self, request):
        device: Device = request.auth
        device.lock_admin()
        return Response(admin_state(device))


class AppAdminAccess:
    """Baustein für Ansichten unter ``/api/app/v1/admin/u/…``: nur mit Vorstandsschlüssel.

    Die Ansichten selbst (Rechte, Prüfungen, Protokoll, Rückgängig) sind dieselben wie im
    Browser; hier kommen nur Anmeldung, Begrenzung und die Herkunft „App (Gerät)“ dazu.
    """

    authentication_classes = [AdminTokenAuthentication]

    def initial(self, request, *args, **kwargs):
        device = request.auth  # meldet an
        if device is not None:
            if too_many(f"app-admin:{device.pk}", 600, 60 * 60):
                raise Throttled(detail="Zu viele Anfragen. Bitte etwas später erneut.")
            # Änderungspaket gehört der Person (für Rückgängig), Protokoll nennt das Gerät
            ctx = tracking.active()
            if ctx is not None:
                ctx.user_id = request.user.pk
            self._via = current_via.set(f"App ({device.name})"[:100])
        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        token = getattr(self, "_via", None)
        if token is not None:
            current_via.reset(token)
            self._via = None
        return super().finalize_response(request, response, *args, **kwargs)


class AdminScopedMixin(AppAdminAccess, OrgScopedMixin):
    """Ansicht der Verwaltung in der App: nur mit Vorstandsschlüssel, Rechte wie im Browser."""

    permission_classes = [IsAuthenticated]


def for_app(view_cls: type, read_only: bool = False) -> type:
    """Browser-Ansicht für die Verwaltung in der App (gleiche Logik, Vorstandsschlüssel).

    ``read_only``: nur lesen (Auswahllisten wie Mitgliedsarten, Untereinheiten)."""
    attrs = {"__module__": view_cls.__module__, "__doc__": view_cls.__doc__}
    if read_only:
        attrs["http_method_names"] = ["get", "head", "options"]
    return type(f"App{view_cls.__name__}", (AppAdminAccess, view_cls), attrs)


class AdminTasksView(AdminScopedMixin, APIView):
    """Offene Aufgaben der Einheit (wie auf der Startseite im Browser)."""

    @extend_schema(responses=dict)
    def get(self, request, org_id: int):
        org, perms = self.org, self.org_permissions
        items: list[dict] = []
        if org.keeps_members and "members" in (org.enabled_modules or []):
            items += member_tasks(org, perms)
        items += event_tasks(org, perms)
        return Response({"items": items})
