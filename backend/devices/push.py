"""Push an die Geräte eines Kontos: wer ist per App erreichbar, Nachricht zustellen."""

from __future__ import annotations

import datetime
import logging

from django.db.models import Q
from django.utils import timezone

from core.tenancy import rls_bypass

from . import webpush
from .models import IDLE_DAYS, Device

logger = logging.getLogger(__name__)


def push_devices(user_ids):
    """Aktive Geräte mit Push-Endpunkt (ohne RLS: nur im Hintergrund oder geprüft nutzen)."""
    since = timezone.now() - datetime.timedelta(days=IDLE_DAYS)
    return (
        Device.objects.filter(user_id__in=user_ids, revoked_at__isnull=True, last_seen_at__gt=since)
        .exclude(push_kind=Device.Push.NONE)
        .exclude(Q(push_endpoint="") | Q(push_p256dh="") | Q(push_auth=""))
    )


def app_accesses(membership_ids) -> dict[int, int]:
    """Mitgliedschaften, deren Zugang ein Gerät mit Push hat: Mitgliedschaft → Zugang."""
    from portal.models import PortalAccess

    ids = [m for m in membership_ids if m]
    if not ids:
        return {}
    with rls_bypass():
        rows = list(
            PortalAccess.objects.filter(membership_id__in=ids, user__is_active=True).values_list(
                "membership_id", "pk", "user_id"
            )
        )
        with_push = set(
            push_devices({u for _, _, u in rows}).values_list("user_id", flat=True).distinct()
        )
    return {m: a for m, a, u in rows if u in with_push}


def send_to_user(user_id: int, data: dict, *, urgent: bool = True) -> int:
    """Nachricht an alle Push-Geräte eines Kontos; gibt die Zahl der zugestellten zurück."""
    delivered = 0
    with rls_bypass():
        devices = list(push_devices([user_id]))
    for device in devices:
        try:
            limit = (
                webpush.MAX_PAYLOAD_FCM
                if device.push_kind == Device.Push.FCM
                else webpush.MAX_PAYLOAD
            )
            result = webpush.send(
                device.push_endpoint,
                device.push_p256dh,
                device.push_auth,
                data,
                urgent=urgent,
                max_payload=limit,
            )
        except webpush.PushError as exc:
            logger.info("Push an Gerät %s nicht zugestellt: %s", device.pk, exc)
            continue
        if result.ok:
            delivered += 1
        elif result.gone:
            # Endpunkt gibt es nicht mehr: bis zur nächsten Anmeldung der App nur Abruf
            with rls_bypass():
                Device.objects.filter(pk=device.pk).update(
                    push_kind=Device.Push.NONE, push_endpoint="", push_p256dh="", push_auth=""
                )
        else:
            logger.info("Push an Gerät %s abgelehnt (HTTP %s)", device.pk, result.status)
    return delivered


def notify_membership(membership_id: int | None, title: str, text: str) -> None:
    """Nach dem Speichern einen Hinweis an die App des Mitglieds schicken (falls vorhanden)."""
    if not membership_id or not app_accesses([membership_id]):
        return
    from django.db import transaction

    from .tasks import notify_membership as task

    transaction.on_commit(lambda: task.delay(membership_id, title, text))
