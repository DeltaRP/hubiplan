"""App-Schnittstelle, Version 1 (``/api/app/v1/``).

Die App nutzt für Termine, Rückmeldungen, Rundschreiben und Profil die
Schnittstelle des Mitgliederbereichs (``/api/portal/<Zugang>/…``) mit ihrem
Geräteschlüssel. Hier liegen nur Anmeldung, Geräte und die Übersicht.
"""

from __future__ import annotations

import datetime
import logging
import secrets

from allauth.headless.internal.sessionkit import authenticate_by_x_session_token
from django.conf import settings
from django.contrib.sessions.backends.base import SessionBase
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ratelimit import client_ip, too_many
from core.tenancy import set_rls
from portal import services as portal_services
from portal.models import LoginLink
from portal.models import hash_token as link_hash
from portal.views import portal_summary

from . import devicekey, notify, webpush
from .auth import DeviceTokenAuthentication
from .models import PAIRING_MINUTES, Device, PairingCode, hash_token

logger = logging.getLogger(__name__)

API_VERSION = 1
# Älteste App-Version (versionCode), die diese Schnittstelle noch bedient
MIN_APP_VERSION = 1
RATE = (10, 15 * 60)  # 10 Versuche je 15 Minuten und IP
MAX_DEVICES = 10  # je Konto


def _rate_limited(request, kind: str) -> bool:
    return too_many(f"app:{kind}:{client_ip(request)}", RATE[0], RATE[1])


def device_data(device: Device, current: Device | None = None) -> dict:
    return {
        "id": device.pk,
        "name": device.name,
        "platform": device.platform,
        "app_version": device.app_version,
        "push": device.push_kind,
        "created_at": device.created_at,
        "last_seen_at": device.last_seen_at,
        "current": current is not None and current.pk == device.pk,
        # Verwaltung in der App freigeschaltet (Schritt A8)
        "admin_until": device.admin_until if device.admin_active else None,
        # Härtung H7: Schlüsselpaar gemeldet, Geräteschlüssel bald erneuern
        "key": bool(device.device_key),
        "renew_due": device.renew_due,
    }


class DeviceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    platform = serializers.ChoiceField(choices=Device.Platform.choices, default="android")
    app_version = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    # Härtung H7: öffentlicher Teil des Schlüsselpaars im Keystore (ältere Apps: leer)
    device_key = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")

    def validate_device_key(self, value):
        if value and not devicekey.valid_public_key(value):
            raise serializers.ValidationError("Ungültiger Schlüssel.")
        return value


def _create_device(user, data: dict) -> tuple[Device, str]:
    token = Device.new_token()
    with transaction.atomic():
        device = Device.objects.create(
            user=user,
            name=data["name"],
            platform=data["platform"],
            app_version=data.get("app_version", ""),
            token_hash=hash_token(token),
            device_key=data.get("device_key", ""),
            token_issued_at=timezone.now(),
        )
        # Höchstens MAX_DEVICES aktive Geräte: die am längsten nicht genutzten fallen weg
        active = Device.objects.filter(user=user, revoked_at__isnull=True).order_by(
            "-last_seen_at", "-pk"
        )
        old = list(active.values_list("pk", flat=True)[MAX_DEVICES:])
        if old:
            Device.objects.filter(pk__in=old).update(revoked_at=timezone.now())
        notify.device_added(user, device)
    return device, token


def _paired(user, device: Device, token: str) -> Response:
    return Response(
        {
            "token": token,
            "device": device_data(device, device),
            "user": {"email": user.email, "display": user.get_full_name() or user.email},
        },
        status=201,
    )


def push_ways() -> list[dict]:
    ways = [{"kind": Device.Push.UNIFIEDPUSH, "vapid_public_key": webpush.vapid_public_key()}]
    gateway = getattr(settings, "PUSH_GATEWAY_URL", "")
    if gateway:
        # Die App bindet den Endpunkt an diesen Schlüssel (/fcm/<Token>/<Kennung>)
        ways.append(
            {
                "kind": Device.Push.FCM,
                "gateway": gateway,
                "vapid_public_key": webpush.vapid_public_key(),
            }
        )
    return ways


class InstanceView(APIView):
    """Selbstauskunft der Instanz für die App (ohne Anmeldung)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "product": "HUBIplan",
                "api_version": API_VERSION,
                "min_app_version": MIN_APP_VERSION,
                "url": settings.FRONTEND_URL,
                # Push-Wege der Instanz; Abruf geht immer
                "push": push_ways(),
            }
        )


class PairingCodeView(APIView):
    """Im Browser (Mein Konto): QR-Code zum Verbinden der App erzeugen."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if too_many(f"app:pairing:{request.user.pk}", RATE[0], RATE[1]):
            return Response({"detail": "Zu viele Versuche. Bitte später erneut."}, status=429)
        if not portal_services.portal_accesses(request.user):
            raise ValidationError(
                "Die App gibt es für den Mitgliederbereich. Für dieses Konto ist kein "
                "Mitgliederbereich freigeschaltet."
            )
        now = timezone.now()
        # Ältere offene Codes gelten nicht mehr
        PairingCode.objects.filter(user=request.user, used_at__isnull=True).update(used_at=now)
        token = PairingCode.new_token()
        code = PairingCode.objects.create(
            user=request.user,
            token_hash=hash_token(token),
            expires_at=now + datetime.timedelta(minutes=PAIRING_MINUTES),
        )
        # Im Fragment (#), damit der Code in keinem Server-Protokoll landet
        url = f"{settings.FRONTEND_URL}/app/verbinden#code={token}"
        return Response({"id": code.pk, "url": url, "expires_at": code.expires_at}, status=201)


class PairingStatusView(APIView):
    """Im Browser: Wurde der QR-Code benutzt, und von welchem Gerät?"""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        code = PairingCode.objects.filter(user=request.user, pk=pk).select_related("device").first()
        if code is None:
            raise NotFound()
        return Response(
            {
                "used": code.used_at is not None and code.device_id is not None,
                "device": code.device.name if code.device else None,
                "expires_at": code.expires_at,
            }
        )


class PairSerializer(DeviceSerializer):
    code = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    login_link = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class PairView(APIView):
    """App: mit QR-Code oder Anmeldelink verbinden und Geräteschlüssel erhalten."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        if _rate_limited(request, "pair"):
            return Response({"detail": "Zu viele Versuche. Bitte später erneut."}, status=429)
        data = PairSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if bool(v["code"]) == bool(v["login_link"]):
            raise ValidationError("Bitte den QR-Code scannen oder einen Anmeldelink öffnen.")
        with transaction.atomic():
            if v["code"]:
                item = (
                    PairingCode.objects.select_for_update()
                    .select_related("user")
                    .filter(token_hash=hash_token(v["code"]))
                    .first()
                )
            else:
                item = (
                    LoginLink.objects.select_for_update(of=("self",))
                    .select_related("user")
                    .filter(token_hash=link_hash(v["login_link"]))
                    .first()
                )
            if item is None or not item.is_open or not item.user.is_active:
                raise NotFound("Der Code ist ungültig oder abgelaufen. Bitte einen neuen erzeugen.")
            user = item.user
            set_rls(None, user.pk)
            # Anmeldelinks gelten wie im Browser nicht für Vorstände und Konten mit 2FA
            if v["login_link"] and not portal_services.link_login_allowed(user):
                raise PermissionDenied(
                    "Für dieses Konto bitte mit Passwort oder QR-Code aus „Mein Konto“ anmelden."
                )
            if not portal_services.portal_accesses(user):
                raise PermissionDenied(
                    "Für dieses Konto ist kein Mitgliederbereich freigeschaltet."
                )
            device, token = _create_device(user, v)
            item.used_at = timezone.now()
            fields = ["used_at"]
            if isinstance(item, PairingCode):
                item.device = device
                fields.append("device")
            item.save(update_fields=fields)
        return _paired(user, device, token)


class _AppSessionAuthentication(BaseAuthentication):
    """Sitzung aus der Anmeldung mit Passwort (allauth, Client „app“)."""

    def authenticate(self, request):
        token = request.headers.get("X-Session-Token")
        if not token:
            return None
        return authenticate_by_x_session_token(token)


class DeviceListView(APIView):
    """GET: eigene Geräte (Browser oder App) · POST: Gerät nach Passwort-Anmeldung."""

    authentication_classes = [
        SessionAuthentication,
        DeviceTokenAuthentication,
        _AppSessionAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        current = request.auth if isinstance(request.auth, Device) else None
        devices = Device.objects.filter(user=request.user, revoked_at__isnull=True)
        return Response(
            [device_data(d, current) for d in devices if d.is_active],
        )

    def post(self, request):
        # Nur direkt nach der Anmeldung in der App (X-Session-Token), nicht aus dem Browser
        if not isinstance(request.auth, SessionBase):
            raise PermissionDenied("Geräte werden in der App angemeldet.")
        data = DeviceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        set_rls(None, request.user.pk)
        if not portal_services.portal_accesses(request.user):
            raise PermissionDenied("Für dieses Konto ist kein Mitgliederbereich freigeschaltet.")
        device, token = _create_device(request.user, data.validated_data)
        # Die Sitzung der Anmeldung wird nicht mehr gebraucht
        request.auth.delete()
        return _paired(request.user, device, token)


class DeviceDetailView(APIView):
    """DELETE: Gerät abmelden (eigenes Konto; in der App auch das Gerät selbst)."""

    authentication_classes = [SessionAuthentication, DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk: int):
        device = Device.objects.filter(pk=pk, user=request.user, revoked_at__isnull=True).first()
        if device is None:
            raise NotFound()
        device.revoked_at = timezone.now()
        device.save(update_fields=["revoked_at"])
        return Response(status=204)


class DeviceAdminLockView(APIView):
    """Mein Konto: Verwaltung in der App auf diesem Gerät sperren (Gerät bleibt angemeldet)."""

    authentication_classes = [SessionAuthentication, DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk: int):
        device = Device.objects.filter(pk=pk, user=request.user, revoked_at__isnull=True).first()
        if device is None:
            raise NotFound()
        device.lock_admin()
        return Response(
            device_data(device, request.auth if isinstance(request.auth, Device) else None)
        )


class MeView(APIView):
    """App: Konto, dieses Gerät und die Zugänge zum Mitgliederbereich."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response(
            {
                "user": {"email": user.email, "display": user.get_full_name() or user.email},
                "device": device_data(request.auth, request.auth),
                "portal": [portal_summary(a) for a in portal_services.portal_accesses(user)],
            }
        )


class PushSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[Device.Push.UNIFIEDPUSH, Device.Push.FCM])
    endpoint = serializers.CharField(max_length=1000)
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=100)

    def validate_endpoint(self, value):
        try:
            webpush.check_endpoint(value)
        except webpush.PushError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate(self, attrs):
        if attrs["kind"] == Device.Push.FCM:
            # Google-Push nur über das eingestellte Gateway dieser Instanz
            gateway = getattr(settings, "PUSH_GATEWAY_URL", "").rstrip("/")
            if not gateway or not attrs["endpoint"].startswith(gateway + "/fcm/"):
                raise serializers.ValidationError(
                    {"endpoint": "Diese Instanz nimmt keinen Google-Push über dieses Gateway an."}
                )
        return attrs

    def validate_p256dh(self, value):
        if not webpush.valid_p256dh(value):
            raise serializers.ValidationError("Ungültiger Schlüssel.")
        return value

    def validate_auth(self, value):
        if not webpush.valid_auth(value):
            raise serializers.ValidationError("Ungültiger Schlüssel.")
        return value


class PushView(APIView):
    """App: Push-Endpunkt dieses Geräts melden (PUT) oder abmelden (DELETE, dann nur Abruf)."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request):
        data = PushSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        device: Device = request.auth
        device.push_kind = v["kind"]
        device.push_endpoint = v["endpoint"]
        device.push_p256dh = v["p256dh"]
        device.push_auth = v["auth"]
        device.save(update_fields=["push_kind", "push_endpoint", "push_p256dh", "push_auth"])
        return Response(device_data(device, device))

    def delete(self, request):
        device: Device = request.auth
        device.push_kind = Device.Push.NONE
        device.push_endpoint = device.push_p256dh = device.push_auth = ""
        device.save(update_fields=["push_kind", "push_endpoint", "push_p256dh", "push_auth"])
        return Response(device_data(device, device))


class DeviceKeySerializer(serializers.Serializer):
    device_key = serializers.CharField(max_length=120)

    def validate_device_key(self, value):
        if not devicekey.valid_public_key(value):
            raise serializers.ValidationError("Ungültiger Schlüssel.")
        return value


class DeviceKeyView(APIView):
    """App (ältere Verbindung): Schlüsselpaar nachmelden. Nur einmal, nie überschreiben."""

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request):
        data = DeviceKeySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        device: Device = request.auth
        key = data.validated_data["device_key"]
        if device.device_key and device.device_key != key:
            return Response(
                {"detail": "Für dieses Gerät ist schon ein anderer Schlüssel gemeldet."},
                status=409,
            )
        updated = Device.objects.filter(pk=device.pk, device_key="").update(
            device_key=key, token_issued_at=timezone.now()
        )
        device.refresh_from_db()
        if not updated and device.device_key != key:
            return Response(
                {"detail": "Für dieses Gerät ist schon ein anderer Schlüssel gemeldet."},
                status=409,
            )
        return Response(device_data(device, device))


class RenewSerializer(serializers.Serializer):
    challenge = serializers.CharField(max_length=100)
    signature = serializers.CharField(max_length=200)


class DeviceRenewView(APIView):
    """App: Geräteschlüssel erneuern (Härtung H7).

    1. ``POST`` ohne Inhalt: Aufgabe (``challenge``), 5 Minuten gültig.
    2. ``POST`` mit ``challenge`` und ``signature`` (Unterschrift des Schlüsselpaars über
       ``hubiplan-renew\n<Gerät>\n<Aufgabe>``): neuer Geräteschlüssel. Der alte gilt bis kurz
       nach der ersten Nutzung des neuen; danach führt seine Nutzung zur Sperre (Kopie).
    """

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.core.cache import cache

        device: Device = request.auth
        if not device.device_key:
            raise ValidationError({"detail": "Für dieses Gerät ist kein Schlüsselpaar gemeldet."})
        cache_key = f"app-renew:{device.pk}"
        if not request.data:
            if _rate_limited(request, "renew"):
                return Response({"detail": "Zu viele Versuche. Bitte später erneut."}, status=429)
            challenge = secrets.token_urlsafe(24)
            cache.set(cache_key, challenge, devicekey.CHALLENGE_SECONDS)
            return Response(
                {"challenge": challenge, "expires_in": devicekey.CHALLENGE_SECONDS}, status=201
            )
        data = RenewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        expected = cache.get(cache_key)
        # Jede Aufgabe nur einmal
        cache.delete(cache_key)
        if not expected or expected != v["challenge"]:
            raise ValidationError({"detail": "Die Aufgabe ist abgelaufen. Bitte erneut."})
        if not devicekey.verify(
            device.device_key, devicekey.renew_message(device.pk, expected), v["signature"]
        ):
            logger.warning("Erneuerung mit falscher Unterschrift: Gerät %s", device.pk)
            raise PermissionDenied("Die Unterschrift stimmt nicht.")
        token = Device.new_token()
        with transaction.atomic():
            current = Device.objects.select_for_update().get(pk=device.pk)
            used = hash_token(request.headers.get("Authorization", "").partition(" ")[2].strip())
            if used == current.previous_token_hash and current.previous_until is not None:
                return Response(
                    {"detail": "Bitte mit dem neuen Geräteschlüssel erneuern."}, status=409
                )
            if used == current.previous_token_hash:
                # Antwort der letzten Erneuerung kam nicht an: der nie genutzte Schlüssel
                # fällt weg, der bisherige bleibt Vorgänger
                pass
            else:
                retired = list(current.retired_hashes or [])
                if current.previous_token_hash:
                    retired.insert(0, current.previous_token_hash)
                current.retired_hashes = retired[: devicekey.RETIRED_KEEP]
                current.previous_token_hash = current.token_hash
            current.previous_until = None
            current.token_hash = hash_token(token)
            current.token_issued_at = timezone.now()
            current.save(
                update_fields=[
                    "retired_hashes",
                    "previous_token_hash",
                    "previous_until",
                    "token_hash",
                    "token_issued_at",
                ]
            )
        return Response({"token": token, "device": device_data(current, current)}, status=201)
