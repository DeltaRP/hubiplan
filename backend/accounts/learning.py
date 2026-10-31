"""Lernhilfen: Schalter und ausgeblendete „Warum?“-Erklärungen am eigenen Konto.

Die Texte liegen im Frontend (src/learning/content.ts). Hier steht nur die Liste
der Schlüssel, die man ausblenden kann (learning_keys.json); ein Test im Frontend
prüft, dass beide Listen übereinstimmen.

Gespeichert wird nichts außer dem Schalter und der Liste der Schlüssel: kein
Protokoll, welche Hilfe wie oft geöffnet wurde.
"""

import json
from pathlib import Path

from django.db import transaction
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User

DECISION_KEYS: frozenset[str] = frozenset(
    json.loads((Path(__file__).with_name("learning_keys.json")).read_text("utf-8"))["decisions"]
)


def hidden_keys(user: User) -> list[str]:
    # Nur bekannte Schlüssel zurückgeben: gestrichene Erklärungen fallen still heraus
    return sorted(k for k in (user.learning_hidden or []) if k in DECISION_KEYS)


def learning_data(user: User) -> dict:
    return {"learning_aids": user.learning_aids, "learning_hidden": hidden_keys(user)}


class LearningSerializer(serializers.Serializer):
    learning_aids = serializers.BooleanField(required=False)
    # Nur das Zurücksetzen ist erlaubt; einzelne Schlüssel laufen über die Endpunkte unten
    learning_hidden = serializers.ListField(child=serializers.CharField(), required=False)

    def validate_learning_hidden(self, value):
        if value:
            raise serializers.ValidationError("Nur das Zurücksetzen (leere Liste) ist möglich.")
        return value


class LearningStateSerializer(serializers.Serializer):
    learning_aids = serializers.BooleanField()
    learning_hidden = serializers.ListField(child=serializers.CharField())


class LearningKeySerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    learning_hidden = serializers.ListField(child=serializers.CharField())


class LearningView(APIView):
    """GET: Schalter und ausgeblendete Erklärungen · PATCH: Schalter setzen oder Liste leeren."""

    @extend_schema(responses=LearningStateSerializer)
    def get(self, request):
        return Response(learning_data(request.user))

    @extend_schema(request=LearningSerializer, responses=LearningStateSerializer)
    def patch(self, request):
        data = LearningSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        fields = []
        if "learning_aids" in data.validated_data:
            user.learning_aids = data.validated_data["learning_aids"]
            fields.append("learning_aids")
        if "learning_hidden" in data.validated_data:
            user.learning_hidden = None
            fields.append("learning_hidden")
        if fields:
            user.save(update_fields=fields)
        return Response(learning_data(user))


def _known(key: str) -> str:
    if key not in DECISION_KEYS:
        raise Http404("Unbekannte Erklärung.")
    return key


class LearningHideView(APIView):
    """POST: eine „Warum?“-Erklärung für das eigene Konto ausblenden."""

    @extend_schema(request=None, responses=LearningKeySerializer)
    @transaction.atomic
    def post(self, request, key: str):
        _known(key)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        keys = set(user.learning_hidden or [])
        if key not in keys:
            user.learning_hidden = sorted(keys | {key})
            user.save(update_fields=["learning_hidden"])
        return Response({"ok": True, "learning_hidden": hidden_keys(user)})


class LearningShowView(APIView):
    """POST: eine ausgeblendete Erklärung wieder zeigen (Rückgängig)."""

    @extend_schema(request=None, responses=LearningKeySerializer)
    @transaction.atomic
    def post(self, request, key: str):
        _known(key)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        keys = set(user.learning_hidden or [])
        if key in keys:
            user.learning_hidden = sorted(keys - {key}) or None
            user.save(update_fields=["learning_hidden"])
        return Response({"ok": True, "learning_hidden": hidden_keys(user)})
