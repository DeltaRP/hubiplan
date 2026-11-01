"""Sprache des eigenen Kontos wählen (Mein Konto › Profil) und vor der Anmeldung umschalten."""

from __future__ import annotations

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import i18n


def language_data(user=None) -> dict:
    names = dict(settings.LANGUAGES)
    data = {
        "languages": [{"code": code, "name": names[code]} for code in i18n.available()],
        "default": i18n.DEFAULT,
    }
    if user is not None and user.is_authenticated:
        data["language"] = i18n.user_language(user)
    return data


class LanguageChoiceSerializer(serializers.Serializer):
    language = serializers.CharField(max_length=5)

    def validate_language(self, value):
        if value not in i18n.available():
            raise serializers.ValidationError(_("Diese Sprache gibt es nicht."))
        return value


class LanguageOptionSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class LanguageStateSerializer(serializers.Serializer):
    languages = LanguageOptionSerializer(many=True)
    default = serializers.CharField()
    language = serializers.CharField(required=False)


class MyLanguageView(APIView):
    """GET: wählbare Sprachen und die eigene · PATCH: eigene Sprache setzen."""

    @extend_schema(responses=LanguageStateSerializer)
    def get(self, request):
        return Response(language_data(request.user))

    @extend_schema(request=LanguageChoiceSerializer, responses=LanguageStateSerializer)
    def patch(self, request):
        data = LanguageChoiceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        user.language = data.validated_data["language"]
        user.save(update_fields=["language"])
        translation.activate(user.language)
        response = Response(language_data(user))
        if not request.path.startswith("/api/app/"):
            i18n.set_cookie(response, user.language)
        return response


class PublicLanguagesView(APIView):
    """Wählbare Sprachen für den Umschalter vor der Anmeldung (ohne Anmeldung)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses=LanguageStateSerializer)
    def get(self, request):
        return Response(language_data())
