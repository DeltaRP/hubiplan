"""Öffentliche Verbund-Schnittstelle: /api/peering/v1/…"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ratelimit import client_ip, too_many

from . import identity

API_VERSIONS = [1]
SOFTWARE = "HUBIplan"


class InstanceInfoView(APIView):
    """Selbstauskunft dieser Instanz: wer sie ist und welchen Schlüssel sie nutzt.

    Andere Instanzen holen sie beim Koppeln und vergleichen den Fingerabdruck
    mit dem aus dem Kopplungscode. Enthält keine Daten von Einheiten.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        if too_many(f"peering:info:{client_ip(request)}", 120, 60):
            from rest_framework.exceptions import Throttled

            raise Throttled()
        ident = identity.identity()
        return Response(
            {
                "software": SOFTWARE,
                "format": identity.FORMAT,
                "instance_id": ident.instance_id,
                "base_url": identity.base_url(),
                "public_key": ident.public_key,
                "enc_public_key": ident.enc_public_key,
                "fingerprint": ident.fingerprint,
                "versions": API_VERSIONS,
                "country": settings.PEERING_COUNTRY,
            }
        )
