"""Anmeldung der App mit dem Geräteschlüssel (``Authorization: Bearer hpd_…``).

Der Schlüssel gilt nur für den Mitgliederbereich und die App-Schnittstelle, nie
für Vorstands- oder Plattformfunktionen. Für alle anderen Pfade meldet diese
Klasse niemanden an; dort bleibt es bei der Sitzung im Browser.
"""

from __future__ import annotations

import datetime
import hmac
import logging
import re

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication
from rest_framework.exceptions import APIException

from core.i18n import activate_for
from core.tenancy import set_rls

from . import devicekey
from .models import ADMIN_PREFIX, TOKEN_PREFIX, Device, hash_token

# Pfade, die die App mit dem Geräteschlüssel nutzen darf
ALLOWED_PREFIXES = ("/api/app/v1/", "/api/portal/", "/api/me/contexts/")
# Verwaltung (Schritt A8): nur mit dem Vorstandsschlüssel, nie mit dem Geräteschlüssel
# u/: Einheiten mit Rollen; d/: Untereinheiten mit Rollen nur dort (z. B. Zugführung);
# signature/: hinterlegte eigene Unterschrift für Quittungen
ADMIN_PATH = ("/api/app/v1/admin/u/", "/api/app/v1/admin/d/", "/api/app/v1/admin/signature/")
# Kopfzeile mit dem Geräteschlüssel neben dem Vorstandsschlüssel
DEVICE_HEADER = "X-Hubiplan-Device"
logger = logging.getLogger(__name__)

# „Zuletzt aktiv“ höchstens so oft schreiben
SEEN_EVERY = datetime.timedelta(hours=1)


class DeviceAuthFailed(APIException):
    """Immer 401 (DRF machte sonst ohne Anmeldeschema 403 daraus): App verbindet neu."""

    status_code = 401
    default_code = "device_not_authenticated"


def device_path(path: str) -> bool:
    return path.startswith(ALLOWED_PREFIXES) and not path.startswith(ADMIN_PATH)


# Erneuern geht auch mit einem Schlüssel, der für alles andere zu alt ist (Härtung H7)
RENEW_PATH = "/api/app/v1/devices/current/renew/"


def _copy_detected(device: Device) -> None:
    """Ein ausgemusterter Geräteschlüssel wurde benutzt: es gibt eine Kopie. Gerät sperren."""
    from . import notify

    set_rls(None, device.user_id)
    with transaction.atomic():
        updated = Device.objects.filter(pk=device.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now(),
            revoked_reason="Kopie des Geräteschlüssels erkannt",
            admin_token_hash="",
            admin_until=None,
            admin_key="",
        )
        if updated:
            logger.warning("Kopie des Geräteschlüssels erkannt: Gerät %s gesperrt", device.pk)
            notify.copy_detected(device.user, device)


def find_device(token: str) -> Device:
    """Gerät zum Geräteschlüssel; erkennt Vorgänger und Kopien."""
    digest = hash_token(token.strip())
    qs = Device.objects.select_related("user")
    device = qs.filter(token_hash=digest).first()
    now = timezone.now()
    if device is not None:
        if device.previous_token_hash and device.previous_until is None:
            # Erste Nutzung des neuen Schlüssels: der alte gilt nur noch kurz
            device.previous_until = now + datetime.timedelta(seconds=devicekey.GRACE_SECONDS)
            Device.objects.filter(pk=device.pk, previous_until__isnull=True).update(
                previous_until=device.previous_until
            )
        return device
    device = qs.filter(previous_token_hash=digest).first()
    if device is not None:
        if device.previous_until is None or device.previous_until > now:
            return device
        _copy_detected(device)
        raise DeviceAuthFailed(
            gettext("Das Gerät ist nicht mehr angemeldet. Bitte die App neu verbinden.")
        )
    device = qs.filter(retired_hashes__contains=[digest]).first()
    if device is not None:
        _copy_detected(device)
    raise DeviceAuthFailed(
        gettext("Das Gerät ist nicht mehr angemeldet. Bitte die App neu verbinden.")
    )


class _CodedError(APIException):
    """401 mit ``code`` im Inhalt, damit die App den Grund erkennt."""

    status_code = 401

    def __init__(self, detail=None):
        super().__init__({"detail": detail or self.default_detail, "code": self.default_code})


class DeviceRenewRequired(_CodedError):
    """Geräteschlüssel zu alt: die App erneuert ihn (mit dem Schlüsselpaar) und versucht erneut."""

    default_code = "device_renew"
    default_detail = gettext_lazy("Der Geräteschlüssel muss erneuert werden.")


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme != self.keyword or not token.startswith(TOKEN_PREFIX):
            return None
        if not device_path(request.path):
            raise DeviceAuthFailed(gettext("Mit dem Geräteschlüssel ist das nicht erreichbar."))
        device = find_device(token)
        if not device.is_active or not device.user.is_active:
            raise DeviceAuthFailed(
                gettext("Das Gerät ist nicht mehr angemeldet. Bitte die App neu verbinden.")
            )
        if device.renew_required and request.path != RENEW_PATH:
            raise DeviceRenewRequired()
        now = timezone.now()
        if device.last_seen_at < now - SEEN_EVERY:
            Device.objects.filter(pk=device.pk).update(last_seen_at=now)
            device.last_seen_at = now
        # Die Middleware kennt nur die Sitzung; Datenbereich des Benutzers setzen
        set_rls(None, device.user_id)
        activate_for(request, device.user)
        return device.user, device


class AdminTokenAuthentication(authentication.BaseAuthentication):
    """Vorstandszugang der App (``Authorization: Bearer hpa_…``), nur unter ``ADMIN_PATH``.

    Gilt nur, solange das Gerät angemeldet und die Verwaltung freigeschaltet ist (höchstens
    30 Tage, verfällt nach 14 Tagen ohne Nutzung). Die Rechte prüft jede Ansicht live.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme != self.keyword or not token.startswith(ADMIN_PREFIX):
            return None
        if not request.path.startswith(ADMIN_PATH):
            raise DeviceAuthFailed(gettext("Mit dem Vorstandszugang ist das nicht erreichbar."))
        device = (
            Device.objects.select_related("user")
            .filter(admin_token_hash=hash_token(token.strip()))
            .first()
        )
        if device is None or not device.is_active or not device.user.is_active:
            raise DeviceAuthFailed(
                gettext("Das Gerät ist nicht mehr angemeldet. Bitte die App neu verbinden.")
            )
        # Nur zusammen mit dem Geräteschlüssel desselben Geräts (ein Schlüssel allein reicht nie);
        # während der Erneuerung gilt auch der Vorgänger
        device_token = request.headers.get(DEVICE_HEADER, "").strip()
        if not device_token.startswith(TOKEN_PREFIX) or not _same_device(device, device_token):
            raise DeviceAuthFailed(
                gettext(
                    "Der Vorstandszugang gilt nur zusammen mit dem Geräteschlüssel dieses Geräts."
                )
            )
        if device.renew_required:
            raise DeviceRenewRequired()
        if not device.admin_active:
            raise AdminLocked()
        # Fachfrage 3 (31.10.b): ohne Vorstands-Schlüsselpaar keine Verwaltung mehr
        if not device.admin_key:
            raise AdminLocked()
        check_admin_signature(request, device)
        now = timezone.now()
        if device.admin_used_at is None or device.admin_used_at < now - SEEN_EVERY:
            Device.objects.filter(pk=device.pk).update(admin_used_at=now, last_seen_at=now)
            device.admin_used_at = device.last_seen_at = now
        set_rls(None, device.user_id)
        activate_for(request, device.user)
        return device.user, device

    def authenticate_header(self, request):
        # Ohne gültigen Schlüssel 401 (nicht 403): die App fragt dann nach der Freischaltung
        return self.keyword


def _same_device(device: Device, token: str) -> bool:
    digest = hash_token(token)
    if hmac.compare_digest(device.token_hash, digest):
        return True
    return bool(
        device.previous_token_hash
        and hmac.compare_digest(device.previous_token_hash, digest)
        and (device.previous_until is None or device.previous_until > timezone.now())
    )


_NONCE = re.compile(r"[A-Za-z0-9_-]{16,100}")


class AdminSignatureFailed(_CodedError):
    default_code = "admin_signature"
    default_detail = gettext_lazy(
        "Die Anfrage ist nicht gültig unterschrieben. Bitte die App neu freischalten."
    )


def check_admin_signature(request, device: Device) -> None:
    """Jede Vorstandsanfrage trägt Zeit und Unterschrift des Vorstands-Schlüsselpaars (H7).

    Ohne das Telefon und dessen Entsperren ist ein abgegriffener ``hpa_…`` so wertlos.
    Jede Unterschrift gilt nur einmal (Schutz vor Wiederholung)."""
    timestamp = request.headers.get(devicekey.TIME_HEADER, "").strip()
    signature = request.headers.get(devicekey.SIGNATURE_HEADER, "").strip()
    try:
        skew = abs(timezone.now().timestamp() - int(timestamp))
    except ValueError:
        raise AdminSignatureFailed() from None
    if skew > devicekey.MAX_SKEW or not signature:
        raise AdminSignatureFailed(
            gettext("Die Uhrzeit des Telefons weicht zu stark ab oder die Unterschrift fehlt.")
        )
    try:
        body = devicekey.request_body(request)
    except devicekey.BodyTooLarge:
        raise AdminSignatureFailed(gettext("Die Anfrage ist zu groß.")) from None
    nonce = request.headers.get(devicekey.NONCE_HEADER, "").strip()
    if nonce and not _NONCE.fullmatch(nonce):
        raise AdminSignatureFailed()
    message = devicekey.admin_message(
        request.method,
        request.get_full_path(),
        timestamp,
        body,
        nonce=nonce,
        idempotency=request.headers.get(devicekey.IDEMPOTENCY_HEADER, "").strip(),
    )
    if not devicekey.verify(device.admin_key, message, signature):
        raise AdminSignatureFailed()
    # Einmaligkeit: je Gerät über die Zufallskennung (Format 2), sonst über Nachricht und
    # eindeutige Form der Unterschrift. Der Cache ist Redis (alle Prozesse gemeinsam);
    # fällt er aus, scheitert die Anfrage (kein Durchlassen ohne Prüfung).
    if nonce:
        replay_key = f"app-admin-nonce:{device.pk}:{nonce}"
    else:
        replay_key = f"app-admin-sig:{device.pk}:" + devicekey.replay_id(message, signature)
    if not cache.add(replay_key, 1, 2 * devicekey.MAX_SKEW + 60):
        raise AdminSignatureFailed(gettext("Diese Anfrage wurde schon einmal geschickt."))


class AdminLocked(APIException):
    """Vorstandszugang abgelaufen oder gesperrt: App fragt Passwort und 2FA neu ab."""

    status_code = 401
    default_code = "admin_locked"
    default_detail = gettext_lazy(
        "Die Verwaltung ist gesperrt. Bitte mit Passwort und Zwei-Faktor-Code freischalten."
    )


class DeviceTokenScheme(OpenApiAuthenticationExtension):
    """OpenAPI: Geräteschlüssel der App."""

    target_class = "devices.auth.DeviceTokenAuthentication"
    name = "geraeteschluessel"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "hpd_…"}


class AdminTokenScheme(OpenApiAuthenticationExtension):
    """OpenAPI: Vorstandszugang der App (Verwaltung, Schritt A8)."""

    target_class = "devices.auth.AdminTokenAuthentication"
    name = "vorstandsschluessel"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "hpa_…"}


class AppSessionScheme(OpenApiAuthenticationExtension):
    """OpenAPI: Sitzung der Passwort-Anmeldung in der App (allauth, Client „app“)."""

    target_class = "devices.views._AppSessionAuthentication"
    name = "app_sitzung"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Session-Token"}
