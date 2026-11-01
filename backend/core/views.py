from django.db import connection
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


@extend_schema(
    responses=inline_serializer(
        "Health",
        {
            "status": serializers.CharField(),
            "database": serializers.CharField(),
            "keys": serializers.CharField(),
        },
    )
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Lebenszeichen für Docker/Monitoring, prüft auch die Datenbank."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "fehler"
    # Hauptschlüssel lesbar bzw. Schlüsseldienst erreichbar (core/crypto.py)? Sonst sind
    # verschlüsselte Daten nicht lesbar; beim Ausrollen geht es dann zurück.
    from . import crypto

    keys = "ok" if crypto.ready() else "fehler"
    ok = db == "ok" and keys == "ok"
    return Response(
        {"status": "ok" if ok else "fehler", "database": db, "keys": keys}, 200 if ok else 503
    )


@extend_schema(responses=inline_serializer("Csrf", {"csrfToken": serializers.CharField()}))
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request: Request) -> Response:
    """Setzt das CSRF-Cookie, das das Frontend für schreibende Aufrufe braucht."""
    return Response({"csrfToken": get_token(request)})


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


@extend_schema(responses=MeSerializer)
@api_view(["GET"])
def me(request: Request) -> Response:
    """Daten des angemeldeten Benutzers."""
    return Response(MeSerializer(request.user).data)
