"""Eingang der Verbund-Schnittstelle: /api/peering/v1/… (nur andere Instanzen).

Jede Anfrage ist verschlüsselt und unterschrieben (siehe transport.py). Die
Antwort ist für die anfragende Instanz verschlüsselt und unterschrieben.
"""

from __future__ import annotations

import datetime
import json
import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from core.ratelimit import client_ip, too_many
from core.tenancy import rls_bypass

from . import crypto, identity, services, transport
from .models import Peer

log = logging.getLogger(__name__)

MAX_SKEW = datetime.timedelta(minutes=5)
MAX_REQUEST = 20 * 1024 * 1024
# Anfragen je Minute und Absender-Instanz (zusätzlich zur Grenze je IP)
PER_SENDER = 300


def _plain(status: int, message: str) -> HttpResponse:
    return HttpResponse(
        json.dumps({"error": message}), status=status, content_type="application/json"
    )


class _Signed(APIView):
    """Gemeinsamer Ablauf: prüfen, entschlüsseln, verarbeiten, verschlüsselt antworten.

    Ohne Anmeldung und ohne CSRF: Wer anfragt, belegt die Unterschrift."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    # Darf eine noch unbekannte Instanz anfragen (Koppeln mit Code)?
    allow_unknown = False

    def dispatch(self, request, *args, **kwargs):
        with rls_bypass():
            return super().dispatch(request, *args, **kwargs)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses=OpenApiTypes.OBJECT,
        description="Verschlüsseltes, unterschriebenes Paket einer anderen Instanz.",
    )
    def post(self, request):
        if not services.enabled():
            raise Http404
        if too_many(f"peering:in:{client_ip(request)}", 600, 60):
            return _plain(429, "Zu viele Anfragen.")
        body = request.body
        if len(body) > MAX_REQUEST:
            return _plain(413, "Zu groß.")
        sender = request.headers.get(transport.H_INSTANCE, "")
        date = request.headers.get(transport.H_DATE, "")
        nonce = request.headers.get(transport.H_NONCE, "")
        signature = request.headers.get(transport.H_SIGNATURE, "")
        signatures = transport.signatures_of(request.headers)
        when = parse_datetime(date) if date else None
        if not (sender and when and nonce and signature) or len(nonce) > 64:
            return _plain(400, "Unterschrift fehlt.")
        if abs(timezone.now() - when) > MAX_SKEW:
            return _plain(400, "Zeitstempel außerhalb des erlaubten Bereichs.")
        if too_many(f"peering:in:sender:{sender[:64]}", PER_SENDER, 60):
            return _plain(429, "Zu viele Anfragen.")
        try:
            envelope = json.loads(body)
        except ValueError:
            return _plain(400, "Paket lässt sich nicht entschlüsseln.")
        if not isinstance(envelope, dict) or envelope.get("from") != sender:
            return _plain(400, "Absender passt nicht.")
        peer = Peer.objects.filter(instance_id=sender).first() if _is_uuid(sender) else None
        keys = services.keys_of(peer) if peer else None
        if keys is not None:
            # Bekannte Absenderin: erst die Unterschrift, dann (teuer) entschlüsseln
            if not crypto.verify_request_any(
                keys.accepted, "POST", request.path, date, nonce, body, signatures
            ):
                _bad_signature(peer)
                return _plain(403, "Unterschrift ungültig.")
        try:
            payload = crypto.open_sealed(envelope, identity.identity())
        except crypto.CryptoError:
            return _plain(400, "Paket lässt sich nicht entschlüsseln.")
        if keys is None and self.allow_unknown:
            # Koppeln: Code im Inhalt prüfen, dann erst die fremde Selbstauskunft holen
            try:
                keys = self.unknown_sender(payload, sender)
            except ValidationError as exc:
                return _plain(403, " ".join(exc.messages))
            except transport.PeerError as exc:
                return _plain(400, f"Absender nicht prüfbar: {exc}")
            if not crypto.verify_request_any(
                keys.accepted, "POST", request.path, date, nonce, body, signatures
            ):
                return _plain(403, "Unterschrift ungültig.")
        if keys is None:
            return _plain(403, "Unbekannte Instanz.")
        if not cache.add(f"peering:nonce:{sender}:{nonce}", 1, int(MAX_SKEW.total_seconds()) * 3):
            return _plain(409, "Anfrage schon verarbeitet.")
        if peer is not None:
            Peer.objects.filter(pk=peer.pk).update(last_seen_at=timezone.now())
        status = 200
        try:
            data = self.handle(peer, payload)
        except services.Refused as exc:
            status, data = exc.status, {"error": str(exc)}
        except ValidationError as exc:
            status, data = 422, {"error": " ".join(exc.messages)}
        # Schlüsselwechsel: Antwort schon für den neuen Schlüssel der Absenderin
        reply_keys = getattr(self, "reply_keys", None) or keys
        return self.respond(status, data, reply_keys, request.path, nonce)

    def unknown_sender(self, payload: dict, sender: str) -> transport.PeerKeys:
        raise ValidationError(gettext("Unbekannte Instanz."))

    def handle(self, peer, payload):  # pragma: no cover
        raise NotImplementedError

    def respond(self, status, data, keys: transport.PeerKeys, path, nonce) -> HttpResponse:
        ident = identity.identity()
        sealed = crypto.seal(
            data,
            sender=ident.instance_id,
            recipient=keys.instance_id,
            recipient_enc_key=keys.enc_public_key,
        )
        body = json.dumps(sealed).encode()
        date = timezone.now().isoformat()
        response = HttpResponse(body, status=status, content_type="application/json")
        response[transport.H_DATE] = date
        response[transport.H_INSTANCE] = ident.instance_id
        for header, value in transport.signed_headers(
            ident, f"RESPONSE {status}", path, date, nonce, body
        ).items():
            response[header] = value
        return response


# Ab so vielen ungültigen Unterschriften einer bekannten Instanz je Stunde: Alarm
BAD_SIGNATURES = 5


def _bad_signature(peer: Peer) -> None:
    """Gehäuft falsche Unterschriften: Schlüssel gestohlen, Wechsel verpasst oder Angriff."""
    key = f"peering:badsig:{peer.instance_id}"
    if too_many(key, BAD_SIGNATURES, 3600) and cache.add(f"{key}:alarm", 1, 3600):
        from core.alarm import send_alert

        send_alert(
            "Verbund: ungültige Unterschriften einer Gegenstelle",
            [
                f"Instanz: {peer.base_url} ({peer.instance_id})",
                f"Mindestens {BAD_SIGNATURES} Anfragen in einer Stunde mit falscher Unterschrift.",
                "Möglich: Die Gegenstelle hat ihren Schlüssel gewechselt (dann bestätigen),",
                "oder jemand gibt sich als sie aus.",
            ],
        )


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class _Pairing(_Signed):
    allow_unknown = True

    def unknown_sender(self, payload: dict, sender: str) -> transport.PeerKeys:
        # Erst den Code prüfen, dann erst die fremde Adresse abrufen
        services._code_for(str(payload.get("unit", "")), str(payload.get("secret", "")))
        info = transport.fetch_info(str(payload.get("base_url", "")))
        if str(info["instance_id"]) != sender:
            raise ValidationError(gettext("Die Selbstauskunft passt nicht zum Absender."))
        self.info = info
        return services.keys_of(info)


class PairInspectView(_Pairing):
    def handle(self, peer, payload):
        return services.handle_inspect(payload)


class PairRequestView(_Pairing):
    def handle(self, peer, payload):
        info = getattr(self, "info", None)
        if info is None:
            # Instanz ist schon bekannt (weitere Einheit derselben Instanz)
            info = transport.fetch_info(peer.base_url)
            if str(info["instance_id"]) != str(peer.instance_id):
                raise ValidationError(gettext("Die Selbstauskunft passt nicht zum Absender."))
            services._code_for(str(payload.get("unit", "")), str(payload.get("secret", "")))
        return services.handle_request(info, payload)


class InboxView(_Signed):
    def handle(self, peer, payload):
        return services.receive(peer, payload)


class StatusView(_Signed):
    def handle(self, peer, payload):
        return services.status_for(peer, payload)


class KeysView(_Signed):
    """Schlüsselwechsel einer Gegenstelle (H6), auch mit dem alten Schlüssel unterschrieben."""

    def handle(self, peer, payload):
        from . import keys

        result, new_keys = keys.receive(peer, payload)
        self.reply_keys = new_keys
        return result


class QueryView(_Signed):
    """Abfrage einer gekoppelten Einheit (P7: aktive Mitgliedschaft vorhanden?)."""

    def handle(self, peer, payload):
        from .register import answer_query

        coupling = services.find_coupling(peer, payload)
        return answer_query(coupling, payload)


inspect_view = PairInspectView.as_view()
request_view = PairRequestView.as_view()
inbox_view = InboxView.as_view()
status_view = StatusView.as_view()
query_view = QueryView.as_view()
keys_view = KeysView.as_view()
